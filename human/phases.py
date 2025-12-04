"""
Game Phases Module - Night and Vote phase execution logic
"""
import asyncio
from typing import List, Optional
import httpx

from models import Player
from network import AgentCommunicator
from encryption_handler import EncryptionHandler
from config import NETWORK_CONFIG
from agent_lifecycle import AgentLifecycleManager

import sys
sys.path.append('../agent')
from security import create_zero_vector, serialize_encrypted_vector


class PhaseExecutor:
    """Executes game phases (night, vote)"""
    
    def __init__(
        self, 
        players: List[Player],
        encryption_handler: EncryptionHandler,
        chat_history,
        game_log: List[str],
        lifecycle_manager: Optional[AgentLifecycleManager] = None
    ):
        self.players = players
        self.encryption = encryption_handler
        self.chat_history = chat_history
        self.game_log = game_log
        self.lifecycle = lifecycle_manager or AgentLifecycleManager()
        self.day_number = 0
        self.last_killed: List[int] = []
        self.last_voted_out: Optional[int] = None
        
        # Human action targets
        self.human_night_target: Optional[int] = None
        self.human_vote_target: Optional[int] = None
        self.human_player_index = 0
    
    def get_survivors(self) -> List[int]:
        """Get list of alive player indices"""
        return [p.index for p in self.players if p.alive]
    
    def get_dead_players(self) -> List[int]:
        """Get list of dead player indices"""
        return [p.index for p in self.players if not p.alive]
    
    async def collect_encrypted_actions(self, phase: str, message: str) -> List[str]:
        """
        Collect encrypted actions from all players (AI and human).
        
        This implements the Uniform Action Protocol - EVERY player sends data.
        Also handles chat messages from AI agents.
        
        Returns:
            List of base64-encoded encrypted vectors
        """
        survivors = self.get_survivors()
        dead = self.get_dead_players()
        num_players = len(self.players)
        encrypted_actions = [None] * num_players
        
        # Collect from AI agents
        async with httpx.AsyncClient(timeout=NETWORK_CONFIG["action_request_timeout"]) as client:
            tasks = []
            for player in self.players:
                if not player.is_human:
                    tasks.append(AgentCommunicator.request_agent_action(
                        client, player, phase, message, survivors, dead
                    ))
            
            results = await asyncio.gather(*tasks, return_exceptions=True)
            
            for player, result in zip([p for p in self.players if not p.is_human], results):
                if not isinstance(result, Exception):
                    encrypted_action, chat_messages = result
                    encrypted_actions[player.index] = encrypted_action
                    
                    # Broadcast any chat messages from this agent
                    for msg in chat_messages:
                        print(f"[{player.name}] {msg}")
                        await self.broadcast_chat_message(player.index, msg)
                else:
                    # Agent failed - use zero vector
                    print(f"[Engine] {player.name} failed to respond, using zero vector")
                    zero_vec = create_zero_vector(num_players, self.encryption.context)
                    encrypted_actions[player.index] = serialize_encrypted_vector(zero_vec)
        
        # Get human action
        human_player = self.players[self.human_player_index]
        if human_player.alive and phase in ["night", "vote"]:
            human_action = self.get_human_action(phase, survivors)
            encrypted_actions[self.human_player_index] = human_action
        else:
            # Human dead or no action - zero vector
            zero_vec = create_zero_vector(num_players, self.encryption.context)
            encrypted_actions[self.human_player_index] = serialize_encrypted_vector(zero_vec)
        
        # Ensure all slots filled with zero vectors if missing
        for i in range(num_players):
            if encrypted_actions[i] is None:
                zero_vec = create_zero_vector(num_players, self.encryption.context)
                encrypted_actions[i] = serialize_encrypted_vector(zero_vec)
        
        return encrypted_actions
    
    def get_human_action(self, phase: str, survivors: List[int]) -> str:
        """Get encrypted action from human player"""
        human = self.players[self.human_player_index]
        
        # Check if human can act
        can_act = False
        allow_self_target = False
        
        if phase == "night" and human.role in ["mafia", "doctor", "police"]:
            can_act = True
            # Doctor can heal themselves
            if human.role == "doctor":
                allow_self_target = True
        elif phase == "vote":
            can_act = True
        
        if not can_act:
            return self.encryption.create_action_vector(None, self.human_player_index, survivors, allow_self_target)
        
        # Check if target was set by TUI
        target = self.human_night_target if phase == "night" else self.human_vote_target
        
        return self.encryption.create_action_vector(target, self.human_player_index, survivors, allow_self_target)
    
    async def broadcast_chat_message(self, sender_index: int, message: str):
        """Broadcast a chat message to all AI agents"""
        # Store in local chat history and get the msg_id
        msg_id = self.chat_history.add_message(sender_index, "day", message, self.day_number)
        
        chat_data = {
            "msg_id": msg_id,
            "player_index": sender_index,
            "phase": "day",
            "message": message,
            "turn": self.day_number
        }
        
        await AgentCommunicator.broadcast_chat_message(self.players, chat_data)
    
    async def execute_night_phase(self):
        """Execute night phase with homomorphic encryption"""
        self.day_number += 1
        
        print(f"\n{'#'*60}")
        print(f"NIGHT {self.day_number}")
        print(f"{'#'*60}")
        
        message = f"Night {self.day_number} has begun. Mafia chooses a target, Doctor can save someone, Police can investigate."
        self.game_log.append(message)
        
        survivors = self.get_survivors()
        dead = self.get_dead_players()
        await AgentCommunicator.broadcast_update(self.players, "night", message, survivors, dead)
        
        # Collect encrypted actions
        print("[Engine] Collecting encrypted actions from all players...")
        encrypted_actions = await self.collect_encrypted_actions("night", message)
        
        # Process night actions
        killed_vector, attack_plain, heal_plain = self.encryption.process_night_actions(
            encrypted_actions, self.players
        )
        
        # Update player states
        self.last_killed = []
        for i, killed in enumerate(killed_vector):
            if killed > 0 and self.players[i].alive:
                self.players[i].alive = False
                self.last_killed.append(i)
        
        # Handle Police investigation
        from security import deserialize_encrypted_vector
        vectors = [deserialize_encrypted_vector(enc, self.encryption.context) for enc in encrypted_actions]
        self.encryption.handle_police_investigation(vectors, self.players)
        
        # Announce results
        await self.announce_night_results()
    
    async def announce_night_results(self):
        """Announce what happened during the night"""
        print(f"\n{'='*60}")
        print("NIGHT RESULTS")
        print(f"{'='*60}")
        
        # Build detailed night result message
        night_summary = f"Night {self.day_number} has ended.\n"
        
        if self.last_killed:
            killed_names = []
            agents_to_shutdown = []
            
            for victim_index in self.last_killed:
                victim = self.players[victim_index]
                killed_names.append(f"Player {victim_index}")
                message = f"{victim.name} (Player {victim_index}) was killed during the night!"
                print(f"💀 {message}")
                self.game_log.append(message)
                
                # Collect agent addresses to shutdown
                if not victim.is_human and victim.address:
                    agents_to_shutdown.append(victim.address)
            
            night_summary += f"💀 Killed: {', '.join(killed_names)}\n"
            night_summary += "The village wakes up to find tragedy..."
            
            # Shutdown dead agents
            if agents_to_shutdown:
                print(f"[Engine] Shutting down {len(agents_to_shutdown)} dead agent(s)...")
                await self.lifecycle.shutdown_multiple_agents(agents_to_shutdown)
        else:
            message = "No one was killed during the night."
            print(f"✓ {message}")
            self.game_log.append(message)
            night_summary += "✅ No one died. The doctor may have saved someone, or mafia failed to act."
        
        # Broadcast detailed night results to all agents with death info
        survivors = self.get_survivors()
        dead = self.get_dead_players()
        await AgentCommunicator.broadcast_update(
            self.players, "day_start", night_summary, survivors, dead,
            recently_killed=self.last_killed
        )
    
    async def execute_vote_phase(self):
        """Execute voting phase"""
        print(f"\n{'='*60}")
        print(f"VOTE PHASE - Day {self.day_number}")
        print(f"{'='*60}")
        
        survivors = self.get_survivors()
        dead = self.get_dead_players()
        message = f"Day {self.day_number} vote: Eliminate a suspected Mafia member."
        self.game_log.append(message)
        
        await AgentCommunicator.broadcast_update(self.players, "vote", message, survivors, dead)
        
        # Collect votes
        print("[Engine] Collecting encrypted votes...")
        encrypted_votes = await self.collect_encrypted_actions("vote", message)
        
        # Process votes
        vote_counts = self.encryption.process_votes(encrypted_votes)
        
        # Find player with most votes
        max_votes = max(vote_counts)
        if max_votes > 0:
            eliminated = vote_counts.index(max_votes)
            self.players[eliminated].alive = False
            self.last_voted_out = eliminated
            
            print(f"\n{'='*60}")
            print(f"VOTE RESULTS")
            print(f"{'='*60}")
            for i, count in enumerate(vote_counts):
                if count > 0:
                    print(f"Player {i} ({self.players[i].name}): {count} votes")
            
            message = f"{self.players[eliminated].name} (Player {eliminated}) was voted out!"
            print(f"\n💀 {message}")
            self.game_log.append(message)
            
            # Shutdown eliminated agent
            eliminated_player = self.players[eliminated]
            if not eliminated_player.is_human and eliminated_player.address:
                print(f"[Engine] Shutting down voted-out agent...")
                await self.lifecycle.shutdown_agent(eliminated_player.address)
        else:
            message = "No one was eliminated (no votes cast)."
            print(f"\n✓ {message}")
            self.game_log.append(message)
            self.last_voted_out = None
        
        # Update survivors after vote
        survivors = self.get_survivors()
        await AgentCommunicator.broadcast_update(
            self.players, "day", "Vote phase ended.", survivors, dead,
            recently_voted_out=self.last_voted_out if self.last_voted_out else -1
        )
