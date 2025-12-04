"""
Game Engine Module - Core game logic with Homomorphic Encryption

This module contains:
- GameEngine: Main game state and logic manager

Entry point: app.py (TUI application)
"""
import random
from typing import List, Optional
import sys

# Import from agent directory (security utilities)
sys.path.append('../agent')
from chat import GameChatHistory

from config import GAME_CONFIG
from models import Player
from network import AgentCommunicator, spawn_agents_from_lobbies, check_agent_health
from encryption_handler import EncryptionHandler
from phases import PhaseExecutor
from agent_lifecycle import AgentLifecycleManager


# ============================================================================
# Game Engine
# ============================================================================

class GameEngine:
    """Main game engine with homomorphic encryption"""
    
    def __init__(self):
        self.game_id: Optional[str] = None  # Short UUID for game session
        self.players: List[Player] = []
        self.num_players = 0
        self.human_player_index = 0
        self.phase = "setup"  # setup, night, day, vote, end
        self.game_log: List[str] = []
        self.chat_message_id_counter = 0
        self.chat_history = GameChatHistory()
        self.last_displayed_msg_id = -1
        self.lobby_addresses: List[str] = []  # Track lobby addresses
        
        # Initialize sub-modules
        self.encryption = EncryptionHandler()
        self.lifecycle = AgentLifecycleManager()
        self.phase_executor: Optional[PhaseExecutor] = None
        
    def setup_game(self, num_ai_agents: int, ai_addresses: List[str], game_id: str, lobby_addresses: List[str] = None):
        """
        Initialize the game with players and roles.
        
        Args:
            num_ai_agents: Number of AI agents
            ai_addresses: List of AI agent URLs
            game_id: Short UUID to identify this game session
            lobby_addresses: List of lobby URLs (for agent cleanup)
        """
        self.game_id = game_id
        self.num_players = num_ai_agents + 1  # +1 for human
        self.lobby_addresses = lobby_addresses or []
        
        # Create cryptographic context
        self.encryption.initialize_context(self.num_players)
        
        # Distribute roles
        role_dist = GAME_CONFIG["role_distribution"][self.num_players]
        roles = []
        for role, count in role_dist.items():
            roles.extend([role] * count)
        
        print(f"[Engine] Role distribution for {self.num_players} players: {role_dist}")
        print(f"[Engine] Total roles to assign: {len(roles)}")
        
        random.shuffle(roles)
        
        # Assign human player (always index 0)
        self.human_player_index = 0
        human_role = roles[0]
        self.players.append(Player(0, human_role, is_human=True))
        
        # Assign AI agents and register with lifecycle manager
        for i in range(num_ai_agents):
            player_index = i + 1
            agent_address = ai_addresses[i]
            self.players.append(Player(
                player_index,
                roles[player_index],
                is_human=False,
                address=agent_address
            ))
            
            # Register agent with its lobby for cleanup
            if i < len(self.lobby_addresses):
                self.lifecycle.register_agent(agent_address, self.lobby_addresses[i])
        
        # Initialize phase executor with lifecycle manager
        self.phase_executor = PhaseExecutor(
            self.players,
            self.encryption,
            self.chat_history,
            self.game_log,
            self.lifecycle
        )
        
        # Debug: Print all assigned roles
        print(f"[Engine] Game initialized with {self.num_players} players")
        print(f"[Engine] Your role: {human_role.upper()}")
        role_summary = {}
        for p in self.players:
            role_summary[p.role] = role_summary.get(p.role, 0) + 1
        print(f"[Engine] Final role counts: {role_summary}")
        self.log_message(f"Game started with {self.num_players} players")
        
    async def initialize_agents(self):
        """Send initialization data to all AI agents"""
        public_context = self.encryption.get_public_context()
        await AgentCommunicator.initialize_agents(
            self.players, public_context, self.game_id, self.num_players
        )
    
    def log_message(self, message: str):
        """Add message to game log"""
        self.game_log.append(message)
        
    def get_survivors(self) -> List[int]:
        """Get list of alive player indices"""
        return [p.index for p in self.players if p.alive]
    
    def get_dead_players(self) -> List[int]:
        """Get list of dead player indices"""
        return [p.index for p in self.players if not p.alive]
    
    def check_win_condition(self) -> Optional[str]:
        """
        Check if any team has won.
        
        Returns:
            "mafia" if mafia wins, "citizens" if citizens win, None if game continues
        """
        alive_mafia = sum(1 for p in self.players if p.alive and p.role == "mafia")
        alive_citizens = sum(1 for p in self.players if p.alive and p.role != "mafia")
        
        if alive_mafia == 0:
            return "citizens"
        elif alive_mafia >= alive_citizens:
            return "mafia"
        else:
            return None
    
    async def broadcast_update(self, phase: str, message: str):
        """Send game state update to all AI agents"""
        survivors = self.get_survivors()
        dead = self.get_dead_players()
        await AgentCommunicator.broadcast_update(self.players, phase, message, survivors, dead)
    
    async def broadcast_chat_message(self, sender_index: int, message: str):
        """
        Broadcast a chat message to all AI agents.
        
        Args:
            sender_index: Index of the player sending the message
            message: The chat message content
        """
        # Store in local chat history and get the msg_id
        msg_id = self.chat_history.add_message(sender_index, self.phase, message, self.phase_executor.day_number)
        
        chat_data = {
            "msg_id": msg_id,
            "player_index": sender_index,
            "phase": self.phase,
            "message": message,
            "turn": self.phase_executor.day_number
        }
        
        await AgentCommunicator.broadcast_chat_message(self.players, chat_data)
    
    async def start_agent_chat_phase(self, duration_seconds: int = 300):
        """Start chat phase for all agents"""
        survivors = self.get_survivors()
        await AgentCommunicator.start_agent_chat_phase(
            self.players, duration_seconds, survivors, self.phase_executor.day_number
        )
    
    async def stop_agent_chat_phase(self):
        """Stop chat phase for all agents"""
        await AgentCommunicator.stop_agent_chat_phase(self.players, self.phase_executor.day_number)
    
    async def execute_night_phase(self):
        """Execute night phase with homomorphic encryption"""
        self.phase = "night"
        await self.phase_executor.execute_night_phase()
        # Sync state back
        self.game_log = self.phase_executor.game_log
    
    async def execute_vote_phase(self):
        """Execute voting phase"""
        self.phase = "vote"
        await self.phase_executor.execute_vote_phase()
        # Sync state back
        self.game_log = self.phase_executor.game_log
    
    async def end_game(self, winner: str):
        """End the game and reveal roles"""
        self.phase = "end"
        
        print(f"\n{'#'*60}")
        print(f"GAME OVER - {winner.upper()} WIN!")
        print(f"{'#'*60}\n")
        
        print("FINAL ROLES:")
        for player in self.players:
            status = "ALIVE" if player.alive else "DEAD"
            print(f"  Player {player.index} ({player.name}): {player.role.upper()} - {status}")
        
        self.log_message(f"Game ended: {winner} win!")
        
        await self.broadcast_update("end", f"Game over! {winner} team wins!")
    
    # Properties to access phase executor attributes
    @property
    def day_number(self) -> int:
        return self.phase_executor.day_number if self.phase_executor else 0
    
    @property
    def last_killed(self) -> List[int]:
        return self.phase_executor.last_killed if self.phase_executor else []
    
    @property
    def last_voted_out(self) -> Optional[int]:
        return self.phase_executor.last_voted_out if self.phase_executor else None
    
    @property
    def human_night_target(self) -> Optional[int]:
        return self.phase_executor.human_night_target if self.phase_executor else None
    
    @human_night_target.setter
    def human_night_target(self, value: Optional[int]):
        if self.phase_executor:
            self.phase_executor.human_night_target = value
    
    @property
    def human_vote_target(self) -> Optional[int]:
        return self.phase_executor.human_vote_target if self.phase_executor else None
    
    @human_vote_target.setter
    def human_vote_target(self, value: Optional[int]):
        if self.phase_executor:
            self.phase_executor.human_vote_target = value


# ============================================================================
# Export helper functions
# ============================================================================
__all__ = ['GameEngine', 'spawn_agents_from_lobbies', 'check_agent_health']
