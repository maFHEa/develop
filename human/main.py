"""
Game Engine - Orchestrates game flow using modular components
Simplified main file that delegates to specialized managers
"""
import asyncio
import sys
from typing import List, Optional
import httpx
import threading
import uvicorn

from service.dkg.coordinator import DKGCoordinator
from service.crypto_ops import CryptoOperations
from game_phases import GamePhases
from game_logger import GameLogger
from config import NETWORK_CONFIG
from model import Player

# Import chat history from agent directory
sys.path.append('../agent/model')
from chat import GameChatHistory


class GameEngine:
    """Main game engine - orchestrates DKG, phases, and player management"""

    def __init__(self, http_port: int = 9000):
        self.game_id: Optional[str] = None
        self.players: List[Player] = []
        self.num_players = 0
        self.human_player_index = 0
        self.human_role: Optional[str] = None
        self.phase = "setup"
        self.game_log: List[str] = []
        self.chat_message_id_counter = 0
        self.chat_history = GameChatHistory()  # Initialize chat history
        self.last_displayed_msg_id = -1  # Track last displayed message in TUI
        
        # TUI integration: Store action from TUI
        self.pending_human_action: Optional[int] = None
        self.human_action_ready = False
        
        # HTTP server
        self.http_port = http_port
        self.http_address = f"http://localhost:{http_port}"
        self.http_server_thread = None
        
        # Managers (initialized during setup)
        self.dkg_coordinator: Optional[DKGCoordinator] = None
        self.crypto_ops: Optional[CryptoOperations] = None
        self.game_phases: Optional[GamePhases] = None
        self.logger: Optional[GameLogger] = None

    # ========================================================================
    # Game Setup
    # ========================================================================

    def _start_http_server(self, cc, keypair, role):
        """Start HTTP server in background thread"""
        from http_server import app, initialize_server
        
        # Initialize server state
        initialize_server(cc, keypair, role)
        
        def run_server():
            uvicorn.run(app, host="0.0.0.0", port=self.http_port, log_level="warning")
        
        self.http_server_thread = threading.Thread(target=run_server, daemon=True)
        self.http_server_thread.start()
        print(f"[Engine] HTTP server started at {self.http_address}")

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
        self.dkg_coordinator = DKGCoordinator()
        cc, keypair, joint_pk = await self.dkg_coordinator.run_dkg_protocol(
            self.num_players, ai_addresses, game_id
        )

        # Assign roles blindly
        self.human_role, human_encrypted_role, all_encrypted_roles = await self.dkg_coordinator.assign_roles_blindly(
            self.num_players, ai_addresses
        )
        # 역할은 비밀 - 로그에 출력하지 않음

        # Start HTTP server in background
        self._start_http_server(cc, keypair, self.human_role)

        # Create players
        self.players.append(Player(0, is_human=True, address=self.http_address))
        for i, address in enumerate(ai_addresses):
            self.players.append(Player(i + 1, is_human=False, address=address))

        # Initialize crypto operations manager
        self.crypto_ops = CryptoOperations(cc, keypair, joint_pk, self.num_players)
        self.crypto_ops.human_encrypted_role = human_encrypted_role  # Store for investigation
        self.crypto_ops.update_encrypted_roles(all_encrypted_roles)  # Update vector factory
        
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

        승리 조건:
        - 마피아가 모두 죽으면 시민 승리
        - 시민(의사, 경찰 포함) 수가 마피아 수 이하이면 마피아 승리

        사람이 죽어도 게임은 계속됨 (관전 모드)
        """
        # 살아있는 플레이어들의 역할 수집
        alive_mafia = 0
        alive_citizens = 0  # 시민, 의사, 경찰 모두 포함

        import httpx

        # 사람 플레이어 역할 체크
        human_player = self.players[self.human_player_index]
        if human_player.alive:
            if self.human_role == "mafia":
                alive_mafia += 1
            else:
                alive_citizens += 1

        # 에이전트들 역할 체크
        async with httpx.AsyncClient(timeout=5.0) as client:
            for player in self.players:
                if not player.is_human and player.alive:
                    try:
                        response = await client.get(f"{player.address}/reveal_role")
                        if response.status_code == 200:
                            data = response.json()
                            role = data.get("role", "").lower()
                            if role == "mafia":
                                alive_mafia += 1
                            else:
                                alive_citizens += 1
                    except:
                        # 연결 실패 시 시민으로 가정
                        alive_citizens += 1

        print(f"[Engine] 승리 조건 체크: 마피아 {alive_mafia}명, 시민 {alive_citizens}명")

        # 마피아가 모두 죽으면 시민 승리
        if alive_mafia == 0:
            return "citizens"

        # 시민 수가 마피아 수 이하이면 마피아 승리
        if alive_citizens <= alive_mafia:
            return "mafia"

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
        
        # Add message to chat history first so it appears in UI
        # Parameters: player_index, phase, message, turn
        # Chat messages always happen during "day" or "chat" phase
        current_phase = "chat"
        current_turn = self.game_phases.day_number if hasattr(self, 'game_phases') and self.game_phases else 1
        self.chat_history.add_message(sender_index, current_phase, message, current_turn)

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
            # Use async version for police to get investigation result
            if role == "police" and phase == "night" and target >= 0:
                return await self.crypto_ops.create_human_action_vectors_async(
                    target, role, phase, self.players
                )
            return self.crypto_ops.create_human_action_vectors(target, role, phase)

        # CLI mode fallback
        human = self.players[self.human_player_index]

        print(f"\n{'='*60}")
        print(f"YOUR TURN - {phase.upper()} PHASE")
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
                    # Use async version for police to get investigation result
                    if role == "police" and phase == "night":
                        return await self.crypto_ops.create_human_action_vectors_async(
                            target, role, phase, self.players
                        )
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

    async def decrypt_all_roles(self) -> List[str]:
        """
        게임 종료 시 모든 플레이어의 역할을 DKG threshold decryption으로 복호화.
        Returns: List of role strings in player order
        """
        if self.dkg_coordinator:
            return await self.dkg_coordinator.decrypt_all_roles_for_game_end()
        return []
    
    async def relay_decrypt_for_player(
        self,
        ciphertext_b64: str,
        requester_index: int
    ) -> List[int]:
        """
        Relay decryption: requester sends encrypted data, others decrypt sequentially.
        Used for police investigation where only the police should see the result.
        """
        return await self.crypto_ops.decryption_service.relay_decrypt(
            ciphertext_b64,
            requester_index,
            self.players
        )


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
