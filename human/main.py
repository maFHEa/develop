"""
Game Engine - Orchestrates game flow using modular components
Simplified main file that delegates to specialized managers
"""
import asyncio
import sys
from typing import List, Optional
import httpx

from dkg_manager import DKGManager
from crypto_operations import CryptoOperations
from game_phases import GamePhases
from game_logger import GameLogger
from config import NETWORK_CONFIG
from models import Player


class GameEngine:
    """Main game engine - orchestrates DKG, phases, and player management"""

    def __init__(self):
        self.game_id: Optional[str] = None
        self.players: List[Player] = []
        self.num_players = 0
        self.human_player_index = 0
        self.human_role: Optional[str] = None
        self.phase = "setup"
        self.game_log: List[str] = []
        self.chat_message_id_counter = 0
        
        # TUI integration: Store action from TUI
        self.pending_human_action: Optional[int] = None
        self.human_action_ready = False
        
        # Managers (initialized during setup)
        self.dkg_manager: Optional[DKGManager] = None
        self.crypto_ops: Optional[CryptoOperations] = None
        self.game_phases: Optional[GamePhases] = None
        self.logger: Optional[GameLogger] = None

    # ========================================================================
    # Game Setup
    # ========================================================================

    async def setup_game(self, num_ai_agents: int, ai_addresses: List[str], game_id: str):
        """
        Initialize the game with DKG-based role assignment.
        """
        self.game_id = game_id
        self.num_players = num_ai_agents + 1  # +1 for human
        self.human_player_index = 0
        
        # Initialize game logger (clears previous log)
        self.logger = GameLogger(game_id)
        self.logger.log(f"Game setup started with {self.num_players} players")

        # Initialize DKG Manager and run protocol
        self.dkg_manager = DKGManager()
        cc, keypair, joint_pk = await self.dkg_manager.run_dkg_protocol(
            self.num_players, ai_addresses, game_id
        )

        # Assign roles blindly
        self.human_role = await self.dkg_manager.assign_roles_blindly(
            self.num_players, ai_addresses
        )
        self.logger.log(f"Human assigned role: {self.human_role}")

        # Create players
        self.players.append(Player(0, is_human=True))
        for i, address in enumerate(ai_addresses):
            self.players.append(Player(i + 1, is_human=False, address=address))

        # Initialize crypto operations manager
        self.crypto_ops = CryptoOperations(cc, keypair, joint_pk, self.num_players)
        
        # Initialize game phases manager with logger
        self.game_phases = GamePhases(self.crypto_ops, self.logger)

        print(f"[Engine] Game initialized with {self.num_players} players")
        self.log_message(f"Game started with {self.num_players} players")

    # ========================================================================
    # Game Logic
    # ========================================================================

    def log_message(self, message: str):
        self.game_log.append(message)

    def get_survivors(self) -> List[int]:
        return [p.index for p in self.players if p.alive]

    def get_dead_players(self) -> List[int]:
        return [p.index for p in self.players if not p.alive]

    async def check_win_condition(self) -> Optional[str]:
        """
        Check win condition.
        
        PROBLEM: Server doesn't know anyone's role!
        TODO: Implement proper encrypted role aggregation
        For now, game continues until manual stop.
        """
        alive_count = sum(1 for p in self.players if p.alive)
        
        if alive_count <= 1:
            return "draw"  # Only 1 or 0 players left
        
        return None

    async def broadcast_update(self, phase: str, message: str):
        survivors = self.get_survivors()
        dead = self.get_dead_players()

        async with httpx.AsyncClient(timeout=NETWORK_CONFIG["connection_timeout"]) as client:
            tasks = []
            for player in self.players:
                if not player.is_human:
                    tasks.append(
                        self._update_single_agent(client, player, phase, message, survivors, dead)
                    )
            await asyncio.gather(*tasks, return_exceptions=True)

    async def _update_single_agent(self, client, player, phase, message, survivors, dead):
        try:
            await client.post(
                f"{player.address}/update",
                json={
                    "phase": phase, 
                    "message": message, 
                    "survivors": survivors, 
                    "dead_players": dead
                }
            )
        except Exception as e:
            print(f"[Engine] Error updating {player.name}: {e}")

    async def broadcast_chat_message(self, sender_index: int, message: str):
        self.chat_message_id_counter += 1
        msg_id = self.chat_message_id_counter

        async with httpx.AsyncClient(timeout=NETWORK_CONFIG["connection_timeout"]) as client:
            tasks = []
            for player in self.players:
                if not player.is_human and player.alive:
                    tasks.append(
                        self._send_chat_to_agent(client, player, sender_index, message, msg_id)
                    )
            await asyncio.gather(*tasks, return_exceptions=True)

    async def _send_chat_to_agent(self, client, player, sender_index, message, msg_id):
        try:
            await client.post(
                f"{player.address}/chat",
                json={
                    "sender_index": sender_index,
                    "message": message,
                    "message_id": msg_id
                }
            )
        except Exception as e:
            print(f"[Engine] Error sending chat to {player.name}: {e}")

    # ========================================================================
    # Game Phases
    # ========================================================================

    async def execute_night_phase(self):
        """Execute night phase using GamePhases manager"""
        await self.game_phases.execute_night_phase(
            self.players,
            self.human_player_index,
            self.human_role,
            self.get_survivors,
            self.get_dead_players,
            self.get_human_action,
            self.broadcast_update,
            self.log_message
        )

    async def execute_day_phase(self):
        """Execute day phase"""
        self.phase = "day"
        await self.game_phases.execute_day_phase(self.broadcast_update)

    async def execute_vote_phase(self):
        """Execute vote phase using GamePhases manager"""
        self.phase = "vote"
        await self.game_phases.execute_vote_phase(
            self.players,
            self.human_player_index,
            self.human_role,
            self.get_survivors,
            self.get_dead_players,
            self.get_human_action,
            self.broadcast_update,
            self.log_message
        )

    async def get_human_action(self, phase: str, survivors: List[int], role: str) -> tuple:
        """
        Get human player action.
        
        BLIND PROTOCOL: Returns 3 vectors (attack, heal, investigate).
        Only the role-appropriate vector contains real action, others are dummies.
        
        TUI MODE: If human_action_ready is set, returns the pending_human_action from TUI.
        CLI MODE: Prompts for input.
        """
        # Check if TUI has already provided an action
        if self.human_action_ready:
            target = self.pending_human_action if self.pending_human_action is not None else -1
            self.human_action_ready = False  # Reset for next time
            self.pending_human_action = None
            print(f"[You] Using TUI action: target={target}")
            return self.crypto_ops.create_human_action_vectors(target, role, phase)
        
        # CLI mode fallback
        human = self.players[self.human_player_index]

        print(f"\n{'='*60}")
        print(f"YOUR TURN - {phase.upper()} PHASE")
        print(f"Your Role: {role.upper()}")
        print(f"Survivors: {survivors}")
        print(f"{'='*60}")

        # Determine if human can act
        can_act = False
        action_type = None
        
        if phase == "night":
            if role == "mafia":
                can_act = True
                action_type = "attack"
            elif role == "doctor":
                can_act = True
                action_type = "heal"
            elif role == "police":
                can_act = True
                action_type = "investigate"
        elif phase == "vote":
            can_act = True
            action_type = "vote"

        if not can_act:
            print("[You] You have no action this phase")
            return self.crypto_ops.create_human_action_vectors(-1, role, phase)

        valid_targets = [i for i in survivors if i != self.human_player_index]
        action_name = action_type if phase == "night" else "vote for"

        while True:
            try:
                print(f"\nValid targets: {valid_targets}")
                target_input = input(f"Enter player index to {action_name} (or -1 to skip): ")
                target = int(target_input)

                if target == -1:
                    return self.crypto_ops.create_human_action_vectors(-1, role, phase)

                if target in valid_targets:
                    print(f"[You] Action encrypted and submitted")
                    return self.crypto_ops.create_human_action_vectors(target, role, phase)
                else:
                    print(f"Invalid target. Choose from {valid_targets}")

            except ValueError:
                print("Please enter a valid number")
            except KeyboardInterrupt:
                print("\nGame interrupted")
                sys.exit(0)

    # ========================================================================
    # Game Loop
    # ========================================================================

    async def run_game_loop(self):
        print("\n[Engine] Starting game loop...")

        while True:
            await self.execute_night_phase()

            winner = await self.check_win_condition()
            if winner:
                await self.end_game(winner)
                break

            await self.execute_day_phase()
            await self.execute_vote_phase()

            winner = await self.check_win_condition()
            if winner:
                await self.end_game(winner)
                break

    async def end_game(self, winner: str):
        self.phase = "end"

        print(f"\n{'='*60}")
        print("GAME OVER")
        print(f"{'='*60}")
        print(f"Winner: {winner.upper()}")
        print(f"{'='*60}\n")

        # Log game end to file
        survivors = self.get_survivors()
        if self.logger:
            self.logger.log_game_end(winner, survivors, self.game_phases.day_number)

        self.log_message(f"Game ended. Winner: {winner}")
        await self.broadcast_update("end", f"Game over! {winner} wins!")


# ============================================================================
# Main Entry Point
# ============================================================================

async def main():
    """Simple CLI game for testing"""
    engine = GameEngine()
    
    # Example setup
    ai_addresses = [
        "http://localhost:8001",
        "http://localhost:8002",
        "http://localhost:8003",
        "http://localhost:8004"
    ]
    
    await engine.setup_game(len(ai_addresses), ai_addresses, "test_game_123")
    await engine.run_game_loop()


if __name__ == "__main__":
    asyncio.run(main())
