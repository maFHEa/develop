"""
Human Host & Player - Game Engine with Threshold Homomorphic Encryption
Acts as both the Game Server (Engine) and a Human Player
Supports DKG (Distributed Key Generation) for secure role assignment
"""
import asyncio
import random
import sys
from typing import List, Dict, Optional, Tuple
import httpx

# Import from agent directory (security utilities)
sys.path.append('../agent')
from security import (
    create_openfhe_context,
    serialize_crypto_context,
    deserialize_crypto_context,
    serialize_public_key,
    deserialize_public_key,
    serialize_ciphertext,
    deserialize_ciphertext,
    dkg_keygen_lead,
    dkg_keygen_join,
    partial_decrypt_lead,
    partial_decrypt_main,
    fusion_decrypt,
    create_one_hot_vector,
    create_zero_vector,
    aggregate_encrypted_vectors,
    compute_killed_vector,
    encode_roles,
    decode_roles,
    ROLE_ENCODING
)

from config import GAME_CONFIG, NETWORK_CONFIG

# Import after sys.path.append to find agent modules
from chat import GameChatHistory


# ============================================================================
# Game State
# ============================================================================

class Player:
    """Represents a player in the game"""
    def __init__(self, index: int, role: str, is_human: bool, address: Optional[str] = None):
        self.index = index
        self.role = role
        self.is_human = is_human
        self.address = address
        self.alive = True
        self.name = f"Human (You)" if is_human else f"AI Agent {index}"


class GameEngine:
    """Main game engine with threshold homomorphic encryption"""

    def __init__(self):
        self.game_id: Optional[str] = None
        self.cc = None  # OpenFHE CryptoContext
        self.keypair = None  # Human player's keypair (for DKG)
        self.joint_public_key = None  # Final joint public key
        self.players: List[Player] = []
        self.num_players = 0
        self.human_player_index = 0
        self.phase = "setup"
        self.day_number = 0
        self.game_log: List[str] = []
        self.last_killed: List[int] = []
        self.last_voted_out: Optional[int] = None
        self.chat_message_id_counter = 0
        self.chat_history = GameChatHistory()
        self.last_displayed_msg_id = -1

    # ========================================================================
    # DKG (Distributed Key Generation) Methods
    # ========================================================================

    async def run_dkg_protocol(self, ai_addresses: List[str]):
        """
        Execute Distributed Key Generation protocol.
        Final result: Joint public key that requires ALL parties to decrypt
        """
        print("\n" + "="*50)
        print(" DKG: Distributed Key Generation")
        print("="*50)

        # Step 1: Create and distribute crypto context
        self.cc = create_openfhe_context(self.num_players)
        cc_b64 = serialize_crypto_context(self.cc)

        async with httpx.AsyncClient(timeout=NETWORK_CONFIG["connection_timeout"]) as client:
            tasks = []
            for i, address in enumerate(ai_addresses):
                tasks.append(self._send_dkg_setup(client, address, cc_b64, i + 1))
            await asyncio.gather(*tasks, return_exceptions=True)

        # Step 2: Build key chain
        # Human generates lead key
        self.keypair = dkg_keygen_lead(self.cc)
        current_pk_b64 = serialize_public_key(self.cc, self.keypair.publicKey)

        # Build chain visualization
        chain_parts = ["Human(sk0)"]

        async with httpx.AsyncClient(timeout=NETWORK_CONFIG["connection_timeout"]) as client:
            for i, address in enumerate(ai_addresses):
                response = await client.post(
                    f"{address}/dkg_round",
                    json={
                        "round_number": i + 2,
                        "previous_public_key": current_pk_b64
                    }
                )
                response.raise_for_status()
                data = response.json()
                current_pk_b64 = data["public_key"]
                chain_parts.append(f"Agent{i+1}(sk{i+1})")

        # Store final joint public key
        self.joint_public_key = deserialize_public_key(self.cc, current_pk_b64)

        # Print key chain
        print(f"\n Key Chain: {' -> '.join(chain_parts)} -> pk_joint")
        print(f" Result: {self.num_players}-of-{self.num_players} threshold scheme")
        print("="*50 + "\n")

    async def _send_dkg_setup(self, client: httpx.AsyncClient, address: str, cc_b64: str, player_index: int):
        """Send DKG setup to a single agent"""
        try:
            response = await client.post(
                f"{address}/dkg_setup",
                json={
                    "game_id": self.game_id,
                    "crypto_context": cc_b64,
                    "num_players": self.num_players,
                    "player_index": player_index
                }
            )
            response.raise_for_status()
        except Exception as e:
            print(f"[DKG] Error setting up agent at {address}: {e}")
            raise

    async def distributed_role_assignment(self, ai_addresses: List[str]):
        """
        Assign roles using threshold decryption.
        Security: No single party can decrypt alone!
        """
        print("="*50)
        print(" Role Assignment (Threshold Decryption)")
        print("="*50)

        # Step 1: Generate, shuffle, and encrypt roles
        role_dist = GAME_CONFIG["role_distribution"][self.num_players]
        roles = []
        for role, count in role_dist.items():
            roles.extend([role] * count)
        random.shuffle(roles)

        encoded_roles = encode_roles(roles)
        plaintext = self.cc.MakePackedPlaintext(encoded_roles)
        encrypted_roles = self.cc.Encrypt(self.joint_public_key, plaintext)
        encrypted_roles_b64 = serialize_ciphertext(self.cc, encrypted_roles)

        print(f"\n Encrypt: roles -> Enc(pk_joint) -> ciphertext")

        # Step 2: Collect partial decryptions
        partial_results = []

        # Human (Lead)
        human_partial = partial_decrypt_lead(self.cc, encrypted_roles, self.keypair.secretKey)
        partial_results.append(human_partial)

        # Agents
        async with httpx.AsyncClient(timeout=NETWORK_CONFIG["connection_timeout"]) as client:
            for i, address in enumerate(ai_addresses):
                response = await client.post(
                    f"{address}/partial_decrypt",
                    json={
                        "ciphertext": encrypted_roles_b64,
                        "is_lead": False
                    }
                )
                response.raise_for_status()
                data = response.json()
                partial_ct = deserialize_ciphertext(self.cc, data["partial_ciphertext"])
                partial_results.append(partial_ct)

        # Step 3: Fusion
        final_plaintext = fusion_decrypt(self.cc, partial_results)
        decrypted_values = list(final_plaintext.GetPackedValue()[:self.num_players])
        decrypted_roles = decode_roles(decrypted_values)

        # Print decryption flow
        partial_str = " + ".join([f"Dec(sk{i})" for i in range(self.num_players)])
        print(f" Decrypt: {partial_str}")
        print(f"        -> Fusion -> plaintext")
        print(f"\n Decrypted: {decrypted_values}")
        print(f" Roles: {decrypted_roles}")
        print("="*50)

        # Step 4: Assign roles to players
        human_role = decrypted_roles[0]
        self.players.append(Player(0, human_role, is_human=True))
        print(f"\n Your role: {human_role.upper()}\n")

        # AI agents
        joint_pk_b64 = serialize_public_key(self.cc, self.joint_public_key)
        async with httpx.AsyncClient(timeout=NETWORK_CONFIG["connection_timeout"]) as client:
            for i, address in enumerate(ai_addresses):
                role = decrypted_roles[i + 1]
                self.players.append(Player(i + 1, role, is_human=False, address=address))

                await client.post(
                    f"{address}/role_assignment",
                    json={
                        "role": role,
                        "joint_public_key": joint_pk_b64
                    }
                )

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

        # Run DKG protocol
        await self.run_dkg_protocol(ai_addresses)

        # Distribute roles via threshold decryption
        await self.distributed_role_assignment(ai_addresses)

        print(f"[Engine] Game initialized with {self.num_players} players")
        self.log_message(f"Game started with {self.num_players} players")

    async def initialize_agents(self):
        """Initialize AI agents with game state (after DKG)"""
        cc_b64 = serialize_crypto_context(self.cc)
        pk_b64 = serialize_public_key(self.cc, self.joint_public_key)

        async with httpx.AsyncClient(timeout=NETWORK_CONFIG["connection_timeout"]) as client:
            tasks = []
            for player in self.players:
                if not player.is_human:
                    tasks.append(self._init_single_agent(client, player, cc_b64, pk_b64))
            results = await asyncio.gather(*tasks, return_exceptions=True)
            for i, result in enumerate(results):
                if isinstance(result, Exception):
                    print(f"[Engine] Failed to initialize agent {i+1}: {result}")

    async def _init_single_agent(self, client: httpx.AsyncClient, player: Player, cc_b64: str, pk_b64: str):
        """Initialize a single AI agent"""
        try:
            response = await client.post(
                f"{player.address}/init",
                json={
                    "game_id": self.game_id,
                    "crypto_context": cc_b64,
                    "joint_public_key": pk_b64,
                    "role": player.role,
                    "player_index": player.index,
                    "num_players": self.num_players
                }
            )
            response.raise_for_status()
            print(f"[Engine] Initialized {player.name}")
        except Exception as e:
            print(f"[Engine] Error initializing {player.name}: {e}")
            raise

    # ========================================================================
    # Game Logic
    # ========================================================================

    def log_message(self, message: str):
        self.game_log.append(message)

    def get_survivors(self) -> List[int]:
        return [p.index for p in self.players if p.alive]

    def get_dead_players(self) -> List[int]:
        return [p.index for p in self.players if not p.alive]

    def check_win_condition(self) -> Optional[str]:
        alive_mafia = sum(1 for p in self.players if p.alive and p.role == "mafia")
        alive_citizens = sum(1 for p in self.players if p.alive and p.role != "mafia")

        if alive_mafia == 0:
            return "citizens"
        elif alive_mafia >= alive_citizens:
            return "mafia"
        return None

    async def broadcast_update(self, phase: str, message: str):
        survivors = self.get_survivors()
        dead = self.get_dead_players()

        async with httpx.AsyncClient(timeout=NETWORK_CONFIG["connection_timeout"]) as client:
            tasks = []
            for player in self.players:
                if not player.is_human:
                    tasks.append(self._update_single_agent(client, player, phase, message, survivors, dead))
            await asyncio.gather(*tasks, return_exceptions=True)

    async def _update_single_agent(self, client, player, phase, message, survivors, dead):
        try:
            await client.post(
                f"{player.address}/update",
                json={"phase": phase, "message": message, "survivors": survivors, "dead_players": dead}
            )
        except Exception as e:
            print(f"[Engine] Error updating {player.name}: {e}")

    async def broadcast_chat_message(self, sender_index: int, message: str):
        msg_id = self.chat_history.add_message(sender_index, self.phase, message, self.day_number)

        chat_data = {
            "msg_id": msg_id,
            "player_index": sender_index,
            "phase": self.phase,
            "message": message,
            "turn": self.day_number
        }

        async with httpx.AsyncClient(timeout=NETWORK_CONFIG["connection_timeout"]) as client:
            for player in self.players:
                if not player.is_human:
                    try:
                        await client.post(f"{player.address}/chat/broadcast", json=chat_data)
                    except:
                        pass

    async def start_agent_chat_phase(self, duration_seconds: int = 300):
        """Start chat phase for all agents."""
        print(f"[Engine] Starting chat phase ({duration_seconds}s)...")

        async with httpx.AsyncClient(timeout=10.0) as client:
            tasks = []
            for player in self.players:
                if not player.is_human and player.alive:
                    chat_request = {
                        "action": "start",
                        "duration_seconds": duration_seconds,
                        "survivors": self.get_survivors(),
                        "turn": self.day_number
                    }
                    tasks.append(self._send_chat_phase_request(client, player, chat_request))

            await asyncio.gather(*tasks, return_exceptions=True)

    async def stop_agent_chat_phase(self):
        """Stop chat phase for all agents."""
        print(f"[Engine] Stopping chat phase...")

        async with httpx.AsyncClient(timeout=10.0) as client:
            tasks = []
            for player in self.players:
                if not player.is_human and player.alive:
                    chat_request = {"action": "stop"}
                    tasks.append(self._send_chat_phase_request(client, player, chat_request))

            await asyncio.gather(*tasks, return_exceptions=True)

    async def _send_chat_phase_request(self, client: httpx.AsyncClient, player: Player, request_data: Dict):
        """Send chat phase request to a single agent."""
        try:
            await client.post(
                f"{player.address}/chat/phase",
                json=request_data
            )
        except Exception as e:
            print(f"[Engine] Error sending chat phase request to {player.name}: {e}")

    # ========================================================================
    # Action Collection (Threshold Decryption)
    # ========================================================================

    async def collect_encrypted_actions(self, phase: str, message: str) -> List[str]:
        """Collect encrypted actions from all players"""
        survivors = self.get_survivors()
        dead = self.get_dead_players()
        encrypted_actions = [None] * self.num_players

        # Collect from AI agents
        async with httpx.AsyncClient(timeout=NETWORK_CONFIG["action_request_timeout"]) as client:
            tasks = []
            for player in self.players:
                if not player.is_human:
                    tasks.append(self._request_agent_action(client, player, phase, message, survivors, dead))

            results = await asyncio.gather(*tasks, return_exceptions=True)

            for player, result in zip([p for p in self.players if not p.is_human], results):
                if not isinstance(result, Exception):
                    encrypted_action, chat_messages = result
                    encrypted_actions[player.index] = encrypted_action
                    for msg in chat_messages:
                        print(f"[{player.name}] {msg}")
                        await self.broadcast_chat_message(player.index, msg)
                else:
                    print(f"[Engine] {player.name} failed, using zero vector")
                    zero_vec = create_zero_vector(self.num_players, self.cc, self.joint_public_key)
                    encrypted_actions[player.index] = serialize_ciphertext(self.cc, zero_vec)

        # Get human action
        human_player = self.players[self.human_player_index]
        if human_player.alive and phase in ["night", "vote"]:
            human_action = await self.get_human_action(phase, survivors)
            encrypted_actions[self.human_player_index] = human_action
        else:
            zero_vec = create_zero_vector(self.num_players, self.cc, self.joint_public_key)
            encrypted_actions[self.human_player_index] = serialize_ciphertext(self.cc, zero_vec)

        # Fill missing with zero vectors
        for i in range(self.num_players):
            if encrypted_actions[i] is None:
                zero_vec = create_zero_vector(self.num_players, self.cc, self.joint_public_key)
                encrypted_actions[i] = serialize_ciphertext(self.cc, zero_vec)

        return encrypted_actions

    async def _request_agent_action(self, client, player, phase, message, survivors, dead) -> Tuple[str, List[str]]:
        try:
            response = await client.post(
                f"{player.address}/request_action",
                json={"phase": phase, "message": message, "survivors": survivors, "dead_players": dead}
            )
            response.raise_for_status()
            data = response.json()
            return data["encrypted_action"], data.get("chat_messages", [])
        except Exception as e:
            print(f"[Engine] Error requesting action from {player.name}: {e}")
            raise

    async def get_human_action(self, phase: str, survivors: List[int]) -> str:
        human = self.players[self.human_player_index]

        can_act = False
        if phase == "night" and human.role in ["mafia", "doctor", "police"]:
            can_act = True
        elif phase == "vote":
            can_act = True

        if not can_act:
            zero_vec = create_zero_vector(self.num_players, self.cc, self.joint_public_key)
            return serialize_ciphertext(self.cc, zero_vec)

        # Check if target was set by TUI
        target = getattr(self, 'human_night_target', None) if phase == "night" else getattr(self, 'human_vote_target', None)

        if target is None or target == -1:
            zero_vec = create_zero_vector(self.num_players, self.cc, self.joint_public_key)
            return serialize_ciphertext(self.cc, zero_vec)

        if target in survivors and target != self.human_player_index:
            encrypted_vec = create_one_hot_vector(self.num_players, target, self.cc, self.joint_public_key)
            return serialize_ciphertext(self.cc, encrypted_vec)
        else:
            zero_vec = create_zero_vector(self.num_players, self.cc, self.joint_public_key)
            return serialize_ciphertext(self.cc, zero_vec)

    # ========================================================================
    # Night Phase with Threshold Decryption
    # ========================================================================

    async def execute_night_phase(self):
        """Execute night phase with threshold homomorphic encryption"""
        self.day_number += 1
        self.phase = "night"

        print(f"\n{'#'*60}")
        print(f"NIGHT {self.day_number}")
        print(f"{'#'*60}")

        message = f"Night {self.day_number} has begun. Mafia chooses a target, Doctor can save someone, Police can investigate."
        self.log_message(message)

        await self.broadcast_update("night", message)

        # Collect encrypted actions
        print("[Engine] Collecting encrypted actions from all players...")
        encrypted_actions = await self.collect_encrypted_actions("night", message)

        # Deserialize encrypted vectors
        print("[Engine] Deserializing encrypted vectors...")
        vectors = [
            deserialize_ciphertext(self.cc, enc)
            for enc in encrypted_actions
        ]

        # Separate Mafia attacks and Doctor heals
        print("[Engine] Computing blind aggregation (no individual decryption)...")
        mafia_vectors = []
        doctor_vectors = []

        for player in self.players:
            if player.alive:
                if player.role == "mafia":
                    mafia_vectors.append(vectors[player.index])
                elif player.role == "doctor":
                    doctor_vectors.append(vectors[player.index])

        # Aggregate attacks and heals
        if mafia_vectors:
            total_attacks = aggregate_encrypted_vectors(self.cc, mafia_vectors)
        else:
            total_attacks = create_zero_vector(self.num_players, self.cc, self.joint_public_key)

        if doctor_vectors:
            total_heals = aggregate_encrypted_vectors(self.cc, doctor_vectors)
        else:
            total_heals = create_zero_vector(self.num_players, self.cc, self.joint_public_key)

        # Compute killed vector: Attack * (1 - Heal)
        print("[Engine] Computing kill results homomorphically...")
        killed_vector_enc = compute_killed_vector(self.cc, total_attacks, total_heals, self.num_players, self.joint_public_key)

        # Threshold decrypt the aggregated result
        print("[Engine] Threshold decryption of aggregated result...")
        killed_vector = await self._threshold_decrypt_vector(killed_vector_enc)

        # Update player states
        self.last_killed = []
        for i, killed in enumerate(killed_vector):
            if killed > 0 and self.players[i].alive:
                self.players[i].alive = False
                self.last_killed.append(i)

        # Handle Police investigation
        await self.handle_police_investigation(vectors)

        # Announce results
        await self.announce_night_results()

    async def _threshold_decrypt_vector(self, ciphertext) -> List[int]:
        """Perform threshold decryption with all parties"""
        ct_b64 = serialize_ciphertext(self.cc, ciphertext)
        partial_results = []

        # Human (Lead)
        human_partial = partial_decrypt_lead(self.cc, ciphertext, self.keypair.secretKey)
        partial_results.append(human_partial)

        # Agents
        async with httpx.AsyncClient(timeout=NETWORK_CONFIG["connection_timeout"]) as client:
            for player in self.players:
                if not player.is_human:
                    try:
                        response = await client.post(
                            f"{player.address}/partial_decrypt",
                            json={"ciphertext": ct_b64, "is_lead": False}
                        )
                        response.raise_for_status()
                        data = response.json()
                        partial_ct = deserialize_ciphertext(self.cc, data["partial_ciphertext"])
                        partial_results.append(partial_ct)
                    except Exception as e:
                        print(f"[Engine] Partial decrypt error from {player.name}: {e}")
                        raise

        # Fusion
        final_plaintext = fusion_decrypt(self.cc, partial_results)
        return list(final_plaintext.GetPackedValue()[:self.num_players])

    async def handle_police_investigation(self, vectors):
        """Handle police investigation privately"""
        police_players = [p for p in self.players if p.alive and p.role == "police"]

        if not police_players:
            return

        for police in police_players:
            # Get police query vector
            query_vector = vectors[police.index]

            # First decrypt to find who was investigated
            query_result = await self._threshold_decrypt_vector(query_vector)
            target_index = -1
            if max(query_result) > 0:
                target_index = query_result.index(max(query_result))

            # Check if target is mafia (server-side, after decryption)
            is_mafia = False
            if target_index >= 0:
                is_mafia = self.players[target_index].role == "mafia"

            # Send result to police
            if target_index < 0:
                continue  # No investigation performed

            if police.is_human:
                print(f"\n[POLICE INVESTIGATION]")
                print(f"Target: Player {target_index}")
                print(f"Result: {'MAFIA' if is_mafia else 'NOT MAFIA'}")
                print(f"[This information is private to you]")
            else:
                # Send to AI agent
                try:
                    async with httpx.AsyncClient(timeout=10.0) as client:
                        await client.post(
                            f"{police.address}/investigation/result",
                            json={
                                "target_index": target_index,
                                "is_mafia": is_mafia,
                                "turn": self.day_number
                            }
                        )
                except Exception as e:
                    print(f"[Engine] Error sending investigation result to {police.name}: {e}")

    async def announce_night_results(self):
        """Announce what happened during the night"""
        print(f"\n{'='*60}")
        print("NIGHT RESULTS")
        print(f"{'='*60}")

        if self.last_killed:
            for victim_index in self.last_killed:
                victim = self.players[victim_index]
                message = f"{victim.name} (Player {victim_index}) was killed during the night!"
                print(f"  {message}")
                self.log_message(message)
        else:
            message = "No one was killed during the night."
            print(f"  {message}")
            self.log_message(message)

        await self.broadcast_update("day", f"Night {self.day_number} ended. {len(self.last_killed)} players killed.")

    # ========================================================================
    # Vote Phase
    # ========================================================================

    async def execute_vote_phase(self):
        """Execute voting phase with threshold decryption"""
        self.phase = "vote"

        print(f"\n{'='*60}")
        print(f"VOTE PHASE - Day {self.day_number}")
        print(f"{'='*60}")

        survivors = self.get_survivors()
        message = f"Day {self.day_number} vote: Eliminate a suspected Mafia member."
        self.log_message(message)

        await self.broadcast_update("vote", message)

        # Collect votes
        print("[Engine] Collecting encrypted votes...")
        encrypted_votes = await self.collect_encrypted_actions("vote", message)

        # Deserialize and aggregate
        vote_vectors = [
            deserialize_ciphertext(self.cc, enc)
            for enc in encrypted_votes
        ]

        total_votes_enc = aggregate_encrypted_vectors(self.cc, vote_vectors)

        # Threshold decrypt
        vote_counts = await self._threshold_decrypt_vector(total_votes_enc)

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
            print(f"\n  {message}")
            self.log_message(message)
        else:
            message = "No one was eliminated (no votes cast)."
            print(f"\n  {message}")
            self.log_message(message)
            self.last_voted_out = None

        await self.broadcast_update("day", "Vote phase ended.")

    # ========================================================================
    # Game Loop
    # ========================================================================

    async def run_game_loop(self):
        """Main game loop"""
        print("\n[Engine] Starting game loop...")

        while True:
            # Night phase
            await self.execute_night_phase()

            # Check win condition
            winner = self.check_win_condition()
            if winner:
                await self.end_game(winner)
                break

            # Day discussion phase with chat
            await self.execute_day_phase()

            # Vote phase
            await self.execute_vote_phase()

            # Check win condition
            winner = self.check_win_condition()
            if winner:
                await self.end_game(winner)
                break

    async def execute_day_phase(self):
        """Execute day phase with chat discussion using Textual TUI"""
        self.phase = "day"

        # Start chat phase for all agents
        await self.start_agent_chat_phase(duration_seconds=300)

        # Broadcast day phase start to agents
        await self.broadcast_update("day", f"Day {self.day_number} discussion has begun.")

        # Run Textual TUI for chat
        from tui import run_chat_tui
        should_proceed = await run_chat_tui(self)

        # Stop chat phase for all agents
        await self.stop_agent_chat_phase()

        if not should_proceed:
            print("\n[Game] Chat phase interrupted by user")
            raise KeyboardInterrupt

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


# ============================================================================
# Main Entry Point
# ============================================================================

async def spawn_agents_from_lobbies(lobby_addresses: List[str], openai_api_key: str, game_id: str) -> List[str]:
    """
    Spawn AI agents from lobby servers CONCURRENTLY.
    """
    print(f"[Setup] Spawning {len(lobby_addresses)} AI agents concurrently from lobbies...")

    async def spawn_and_wait(client: httpx.AsyncClient, lobby_url: str, agent_num: int) -> str:
        await asyncio.sleep((agent_num - 1) * 0.5)

        print(f"[Setup] Requesting Agent #{agent_num} spawn from {lobby_url}...")
        response = await client.post(
            f"{lobby_url}/spawn_agent",
            json={
                "game_id": game_id,
                "openai_api_key": openai_api_key
            }
        )
        response.raise_for_status()
        data = response.json()
        agent_address = data["address"]
        print(f"[Setup] Agent #{agent_num} spawned at {agent_address}, waiting for startup...")

        for attempt in range(15):
            await asyncio.sleep(1)
            if await check_agent_health(agent_address):
                print(f"[Setup] Agent #{agent_num} ready at {agent_address}")
                return agent_address
            print(f"[Setup] Agent #{agent_num} not ready yet, retrying ({attempt+1}/15)...")

        raise Exception(f"Agent #{agent_num} at {agent_address} failed to start after 15 seconds")

    async with httpx.AsyncClient(timeout=30) as client:
        tasks = [
            spawn_and_wait(client, lobby_url, i)
            for i, lobby_url in enumerate(lobby_addresses, 1)
        ]

        results = await asyncio.gather(*tasks, return_exceptions=True)

        agent_addresses = []
        for res in results:
            if isinstance(res, Exception):
                print(f"[Setup] FATAL: Failed to spawn an agent: {res}")
                raise res
            agent_addresses.append(res)

    return agent_addresses


async def check_agent_health(address: str) -> bool:
    """Check if an agent server is healthy and responding."""
    try:
        async with httpx.AsyncClient(timeout=5) as client:
            response = await client.get(f"{address}/health")
            response.raise_for_status()
            return True
    except Exception:
        return False


async def main():
    """Main entry point - choose between TUI and CLI mode"""
    import sys

    use_cli = "--cli" in sys.argv

    if use_cli:
        await main_cli()
    else:
        from game_app import run_game_tui
        await run_game_tui()


async def main_cli():
    """Original CLI-based game (kept for backwards compatibility)"""
    import uuid

    print("=" * 60)
    print("SECURE P2P MAFIA GAME")
    print("Threshold Homomorphic Encryption + DKG Edition")
    print("=" * 60)

    game_id = str(uuid.uuid4())[:8]
    print(f"\n[Setup] Game ID: {game_id}")

    openai_api_key = NETWORK_CONFIG.get("openai_api_key", "").strip()
    if not openai_api_key:
        openai_api_key = input("\nEnter your OpenAI API key: ").strip()
        if not openai_api_key:
            print("Error: OpenAI API key required")
            return

    print("\n" + "="*60)
    print("LOBBY & AGENT CONFIGURATION")
    print("="*60)

    lobby_addresses = []

    if NETWORK_CONFIG.get("use_config_lobbies", False):
        configured_lobbies = NETWORK_CONFIG.get("lobby_addresses", [])

        if not configured_lobbies:
            print("Config lobby_addresses not set.")
            return

        num_agents = len(configured_lobbies)
        total_players = num_agents + 1

        if total_players < GAME_CONFIG['min_players'] or total_players > GAME_CONFIG['max_players']:
            print(f"Invalid player count: {total_players}")
            return

        print(f"Config: {num_agents} Lobby servers:")
        for i, addr in enumerate(configured_lobbies, 1):
            print(f"  {i}. {addr}")

        lobby_addresses = configured_lobbies
    else:
        print("Enter lobby server addresses (one per line).")
        print(f"Min {GAME_CONFIG['min_players']-1}, Max {GAME_CONFIG['max_players']-1}")

        while True:
            address = input(f"Lobby #{len(lobby_addresses)+1} (or Enter to finish): ").strip()

            if not address:
                if len(lobby_addresses) >= GAME_CONFIG['min_players'] - 1:
                    break
                else:
                    print(f"Need at least {GAME_CONFIG['min_players']-1} lobbies")
                    continue

            if not address.startswith("http://") and not address.startswith("https://"):
                address = f"http://{address}"

            lobby_addresses.append(address)
            print(f"[Setup] Lobby #{len(lobby_addresses)} added")

            if len(lobby_addresses) >= GAME_CONFIG['max_players'] - 1:
                print(f"Maximum {GAME_CONFIG['max_players']-1} reached")
                break

    try:
        agent_addresses = await spawn_agents_from_lobbies(lobby_addresses, openai_api_key, game_id)
    except Exception as e:
        print(f"[Error] Failed to spawn agents: {e}")
        return

    num_agents = len(agent_addresses)
    print(f"\n[Setup] {num_agents} AI Agents ready")

    engine = GameEngine()

    # Setup game with DKG
    await engine.setup_game(num_agents, agent_addresses, game_id)

    # Initialize agents
    print("\n[Setup] Initializing agents...")
    await engine.initialize_agents()

    print("\n[Setup] All players ready!")
    input("Press Enter to start the game...")

    try:
        await engine.run_game_loop()
    except KeyboardInterrupt:
        print("\n\n[Game] Interrupted by user")
    except Exception as e:
        print(f"\n[Error] Game error: {e}")
        import traceback
        traceback.print_exc()

    print("\nThank you for playing!")


if __name__ == "__main__":
    asyncio.run(main())
