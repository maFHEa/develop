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
    multiply_encrypted_vectors,
    encode_roles,
    decode_roles,
    ROLE_ENCODING
)

from config import GAME_CONFIG, NETWORK_CONFIG


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

    # ========================================================================
    # DKG (Distributed Key Generation) Methods
    # ========================================================================

    async def run_dkg_protocol(self, ai_addresses: List[str]):
        """
        Execute Distributed Key Generation protocol.

        1. Create crypto context and send to all agents
        2. Human (Lead) generates initial keypair
        3. Each agent joins DKG sequentially
        4. Final joint public key is established
        """
        print("\n" + "="*60)
        print("DISTRIBUTED KEY GENERATION (DKG)")
        print("="*60)

        # Step 1: Create crypto context
        print("[DKG] Creating threshold FHE context...")
        self.cc = create_openfhe_context(self.num_players)
        cc_b64 = serialize_crypto_context(self.cc)

        # Step 2: Send context to all agents
        print("[DKG] Distributing crypto context to all agents...")
        async with httpx.AsyncClient(timeout=NETWORK_CONFIG["connection_timeout"]) as client:
            tasks = []
            for i, address in enumerate(ai_addresses):
                tasks.append(self._send_dkg_setup(client, address, cc_b64, i + 1))
            await asyncio.gather(*tasks, return_exceptions=True)

        # Step 3: Human (Player 0) generates lead key
        print("[DKG] Human (Lead) generating initial keypair...")
        self.keypair = dkg_keygen_lead(self.cc)
        current_pk_b64 = serialize_public_key(self.cc, self.keypair.publicKey)
        print("[DKG] Human key generated")

        # Step 4: Each agent joins sequentially
        async with httpx.AsyncClient(timeout=NETWORK_CONFIG["connection_timeout"]) as client:
            for i, address in enumerate(ai_addresses):
                print(f"[DKG] Agent {i+1} joining...")
                response = await client.post(
                    f"{address}/dkg_round",
                    json={
                        "round_number": i + 2,  # Human is round 1
                        "previous_public_key": current_pk_b64
                    }
                )
                response.raise_for_status()
                data = response.json()
                current_pk_b64 = data["public_key"]
                print(f"[DKG] Agent {i+1} joined successfully")

        # Step 5: Store final joint public key
        self.joint_public_key = deserialize_public_key(self.cc, current_pk_b64)
        print("[DKG] Joint public key established!")
        print("="*60 + "\n")

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

        1. Shuffle roles and encrypt with joint public key
        2. Collect partial decryptions from all parties
        3. Fuse to get final plaintext roles
        4. Assign roles to players
        """
        print("\n" + "="*60)
        print("THRESHOLD ROLE ASSIGNMENT")
        print("="*60)

        # Step 1: Generate and shuffle roles
        role_dist = GAME_CONFIG["role_distribution"][self.num_players]
        roles = []
        for role, count in role_dist.items():
            roles.extend([role] * count)
        random.shuffle(roles)

        # Step 2: Encode and encrypt roles
        print("[Roles] Encoding and encrypting shuffled roles...")
        encoded_roles = encode_roles(roles)
        plaintext = self.cc.MakePackedPlaintext(encoded_roles)
        encrypted_roles = self.cc.Encrypt(self.joint_public_key, plaintext)
        encrypted_roles_b64 = serialize_ciphertext(self.cc, encrypted_roles)
        print(f"[Roles] Encrypted role vector: {encoded_roles}")

        # Step 3: Threshold decryption - Human (Lead) first
        print("[Roles] Starting threshold decryption...")
        print("[Roles] Human partial decryption (Lead)...")
        partial_results = []
        human_partial = partial_decrypt_lead(self.cc, encrypted_roles, self.keypair.secretKey)
        partial_results.append(human_partial)

        # Step 4: Collect partial decryptions from agents
        async with httpx.AsyncClient(timeout=NETWORK_CONFIG["connection_timeout"]) as client:
            for i, address in enumerate(ai_addresses):
                print(f"[Roles] Agent {i+1} partial decryption...")
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

        # Step 5: Fusion - combine all partial decryptions
        print("[Roles] Fusing partial decryptions...")
        final_plaintext = fusion_decrypt(self.cc, partial_results)
        decrypted_values = list(final_plaintext.GetPackedValue()[:self.num_players])
        decrypted_roles = decode_roles(decrypted_values)
        print(f"[Roles] Decrypted roles: {decrypted_roles}")

        # Step 6: Assign roles to players
        # Human player
        human_role = decrypted_roles[0]
        self.players.append(Player(0, human_role, is_human=True))
        print(f"\n[Engine] Your role: {human_role.upper()}")

        # AI agents
        joint_pk_b64 = serialize_public_key(self.cc, self.joint_public_key)
        async with httpx.AsyncClient(timeout=NETWORK_CONFIG["connection_timeout"]) as client:
            for i, address in enumerate(ai_addresses):
                role = decrypted_roles[i + 1]
                self.players.append(Player(i + 1, role, is_human=False, address=address))

                # Notify agent of their role
                await client.post(
                    f"{address}/role_assignment",
                    json={
                        "role": role,
                        "joint_public_key": joint_pk_b64
                    }
                )

        print("="*60 + "\n")

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
        msg_id = self.chat_message_id_counter
        self.chat_message_id_counter += 1
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
                        await client.post(f"{player.address}/broadcast_chat", json=chat_data)
                    except:
                        pass

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

        print(f"\n{'='*60}")
        print(f"YOUR TURN - {phase.upper()} PHASE")
        print(f"Your Role: {human.role.upper()}")
        print(f"Survivors: {survivors}")
        print(f"{'='*60}")

        can_act = False
        if phase == "night" and human.role in ["mafia", "doctor", "police"]:
            can_act = True
        elif phase == "vote":
            can_act = True

        if not can_act:
            print("[You] You have no action this phase")
            zero_vec = create_zero_vector(self.num_players, self.cc, self.joint_public_key)
            return serialize_ciphertext(self.cc, zero_vec)

        valid_targets = [i for i in survivors if i != self.human_player_index]
        action_name = "target" if phase == "night" else "vote for"

        while True:
            try:
                print(f"\nValid targets: {valid_targets}")
                target_input = input(f"Enter player index to {action_name} (or -1 to skip): ")
                target = int(target_input)

                if target == -1:
                    zero_vec = create_zero_vector(self.num_players, self.cc, self.joint_public_key)
                    return serialize_ciphertext(self.cc, zero_vec)

                if target in valid_targets:
                    encrypted_vec = create_one_hot_vector(self.num_players, target, self.cc, self.joint_public_key)
                    print(f"[You] Action encrypted and submitted")
                    return serialize_ciphertext(self.cc, encrypted_vec)
                else:
                    print(f"Invalid target. Choose from {valid_targets}")

            except ValueError:
                print("Please enter a valid number")
            except KeyboardInterrupt:
                print("\nGame interrupted")
                sys.exit(0)

    # ========================================================================
    # Threshold Decryption for Game Results
    # ========================================================================

    async def threshold_decrypt_vector(self, encrypted_vector) -> List[int]:
        """
        Perform threshold decryption on an aggregated vector.
        Collects partial decryptions from all parties.
        """
        ct_b64 = serialize_ciphertext(self.cc, encrypted_vector)
        partial_results = []

        # Human (Lead) partial decryption
        human_partial = partial_decrypt_lead(self.cc, encrypted_vector, self.keypair.secretKey)
        partial_results.append(human_partial)

        # Agent partial decryptions
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
                        print(f"[Engine] Partial decrypt failed for {player.name}: {e}")
                        raise

        # Fusion
        result = fusion_decrypt(self.cc, partial_results)
        return list(result.GetPackedValue()[:self.num_players])

    # ========================================================================
    # Game Phases
    # ========================================================================

    async def execute_night_phase(self):
        self.day_number += 1
        self.phase = "night"

        print(f"\n{'#'*60}")
        print(f"NIGHT {self.day_number}")
        print(f"{'#'*60}")

        message = f"Night {self.day_number} has begun."
        self.log_message(message)
        await self.broadcast_update("night", message)

        print("[Engine] Collecting encrypted actions...")
        encrypted_actions = await self.collect_encrypted_actions("night", message)

        print("[Engine] Deserializing encrypted vectors...")
        vectors = [deserialize_ciphertext(self.cc, enc) for enc in encrypted_actions]

        print("[Engine] Computing blind aggregation...")
        mafia_vectors = []
        doctor_vectors = []

        for player in self.players:
            if player.alive:
                if player.role == "mafia":
                    mafia_vectors.append(vectors[player.index])
                elif player.role == "doctor":
                    doctor_vectors.append(vectors[player.index])

        if mafia_vectors:
            total_attacks = aggregate_encrypted_vectors(self.cc, mafia_vectors)
        else:
            total_attacks = create_zero_vector(self.num_players, self.cc, self.joint_public_key)

        if doctor_vectors:
            total_heals = aggregate_encrypted_vectors(self.cc, doctor_vectors)
        else:
            total_heals = create_zero_vector(self.num_players, self.cc, self.joint_public_key)

        print("[Engine] Computing kill results homomorphically...")
        killed_vector_enc = compute_killed_vector(self.cc, total_attacks, total_heals, self.num_players, self.joint_public_key)

        print("[Engine] Threshold decrypting aggregated result...")
        killed_vector = await self.threshold_decrypt_vector(killed_vector_enc)

        self.last_killed = []
        for i, killed in enumerate(killed_vector):
            if killed > 0 and self.players[i].alive:
                self.players[i].alive = False
                self.last_killed.append(i)

        await self.handle_police_investigation(vectors)
        await self.announce_night_results()

    async def handle_police_investigation(self, vectors):
        police_players = [p for p in self.players if p.alive and p.role == "police"]

        if not police_players:
            return

        for police in police_players:
            query_vector = vectors[police.index]

            # Create role vector
            role_vector = [1 if p.role == "mafia" else 0 for p in self.players]
            role_pt = self.cc.MakePackedPlaintext(role_vector)
            role_enc = self.cc.Encrypt(self.joint_public_key, role_pt)

            result_enc = multiply_encrypted_vectors(self.cc, query_vector, role_enc)
            result = await self.threshold_decrypt_vector(result_enc)

            is_mafia = sum(result) > 0

            if police.is_human:
                print(f"\n[POLICE INVESTIGATION]")
                print(f"Result: {'MAFIA' if is_mafia else 'NOT MAFIA'}")
                print(f"[This information is private to you]")

    async def announce_night_results(self):
        print(f"\n{'='*60}")
        print("NIGHT RESULTS")
        print(f"{'='*60}")

        if self.last_killed:
            for victim_index in self.last_killed:
                victim = self.players[victim_index]
                message = f"{victim.name} was killed!"
                print(f"💀 {message}")
                self.log_message(message)
        else:
            print("✓ No one was killed")
            self.log_message("No one was killed during the night.")

        await self.broadcast_update("day", f"Night {self.day_number} ended.")

    async def execute_vote_phase(self):
        self.phase = "vote"

        print(f"\n{'='*60}")
        print(f"VOTE PHASE - Day {self.day_number}")
        print(f"{'='*60}")

        survivors = self.get_survivors()
        message = f"Day {self.day_number} vote: Eliminate a suspected Mafia member."
        self.log_message(message)

        await self.broadcast_update("vote", message)

        print("[Engine] Collecting encrypted votes...")
        encrypted_votes = await self.collect_encrypted_actions("vote", message)

        vote_vectors = [deserialize_ciphertext(self.cc, enc) for enc in encrypted_votes]
        total_votes_enc = aggregate_encrypted_vectors(self.cc, vote_vectors)

        print("[Engine] Threshold decrypting vote results...")
        vote_counts = await self.threshold_decrypt_vector(total_votes_enc)

        max_votes = max(vote_counts)
        if max_votes > 0:
            eliminated = vote_counts.index(max_votes)
            self.players[eliminated].alive = False
            self.last_voted_out = eliminated

            print(f"\n{'='*60}")
            print("VOTE RESULTS")
            print(f"{'='*60}")
            for i, count in enumerate(vote_counts):
                if count > 0:
                    print(f"Player {i} ({self.players[i].name}): {count} votes")

            message = f"{self.players[eliminated].name} was voted out!"
            print(f"\n💀 {message}")
            self.log_message(message)
        else:
            print("\n✓ No one was eliminated (no votes cast).")
            self.last_voted_out = None

        await self.broadcast_update("day", "Vote phase ended.")

    async def execute_day_phase(self):
        self.phase = "day"

        print(f"\n{'='*60}")
        print(f"DAY {self.day_number} - DISCUSSION PHASE")
        print(f"{'='*60}")
        print("Type a message to send to all players")
        print("Type 'proceed' or press Enter to move to voting")
        print(f"{'='*60}\n")

        await self.broadcast_update("day", f"Day {self.day_number} discussion has begun.")

        while True:
            try:
                user_input = input("[You] ").strip()

                if user_input.lower() in ['proceed', '']:
                    break

                if user_input:
                    print(f"[You] Broadcasting: {user_input}")
                    await self.broadcast_chat_message(self.human_player_index, user_input)
                    await asyncio.sleep(1)

            except KeyboardInterrupt:
                print("\n[Game] Interrupted")
                raise

    async def run_game_loop(self):
        print("\n[Engine] Starting game loop...")

        while True:
            await self.execute_night_phase()

            winner = self.check_win_condition()
            if winner:
                await self.end_game(winner)
                break

            await self.execute_day_phase()
            await self.execute_vote_phase()

            winner = self.check_win_condition()
            if winner:
                await self.end_game(winner)
                break

    async def end_game(self, winner: str):
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
    """Spawn AI agents from lobby servers concurrently."""
    print(f"[Setup] Spawning {len(lobby_addresses)} AI agents...")

    async def spawn_and_wait(client: httpx.AsyncClient, lobby_url: str, agent_num: int) -> str:
        await asyncio.sleep((agent_num - 1) * 0.5)

        print(f"[Setup] Requesting Agent #{agent_num} spawn from {lobby_url}...")
        response = await client.post(
            f"{lobby_url}/spawn_agent",
            json={"game_id": game_id, "openai_api_key": openai_api_key}
        )
        response.raise_for_status()
        data = response.json()
        agent_address = data["address"]
        print(f"[Setup] Agent #{agent_num} spawned at {agent_address}")

        for attempt in range(15):
            await asyncio.sleep(1)
            if await check_agent_health(agent_address):
                print(f"[Setup] ✓ Agent #{agent_num} ready")
                return agent_address
            print(f"[Setup] Agent #{agent_num} not ready yet ({attempt+1}/15)...")

        raise Exception(f"Agent #{agent_num} failed to start")

    async with httpx.AsyncClient(timeout=30) as client:
        tasks = [spawn_and_wait(client, lobby_url, i) for i, lobby_url in enumerate(lobby_addresses, 1)]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        agent_addresses = []
        for res in results:
            if isinstance(res, Exception):
                print(f"[Setup] ✗ FATAL: Failed to spawn an agent: {res}")
                raise res
            agent_addresses.append(res)

    return agent_addresses


async def check_agent_health(address: str) -> bool:
    try:
        async with httpx.AsyncClient(timeout=5) as client:
            response = await client.get(f"{address}/health")
            response.raise_for_status()
            return True
    except:
        return False


async def main():
    import uuid

    print("=" * 60)
    print("SECURE P2P MAFIA GAME")
    print("Threshold Homomorphic Encryption Edition (OpenFHE)")
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
            print("⚠️  No lobby_addresses configured")
            return

        num_agents = len(configured_lobbies)
        total_players = num_agents + 1

        if total_players < GAME_CONFIG['min_players'] or total_players > GAME_CONFIG['max_players']:
            print(f"⚠️  Config has {num_agents} lobbies (total {total_players} players)")
            print(f"Game supports {GAME_CONFIG['min_players']}-{GAME_CONFIG['max_players']} players")
            return

        print(f"Using {num_agents} lobbies from config:")
        for i, addr in enumerate(configured_lobbies, 1):
            print(f"  {i}. {addr}")

        lobby_addresses = configured_lobbies
    else:
        print("Enter lobby server addresses (one per line).")
        print(f"Min {GAME_CONFIG['min_players']-1}, Max {GAME_CONFIG['max_players']-1}")
        print("="*60 + "\n")

        while True:
            address = input(f"Lobby #{len(lobby_addresses)+1} (or Enter to finish): ").strip()

            if not address:
                if len(lobby_addresses) >= GAME_CONFIG['min_players'] - 1:
                    break
                print(f"Need at least {GAME_CONFIG['min_players']-1} lobbies")
                continue

            if not address.startswith("http"):
                address = f"http://{address}"

            lobby_addresses.append(address)
            print(f"[Setup] ✓ Lobby #{len(lobby_addresses)} added")

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
    await engine.setup_game(num_agents, agent_addresses, game_id)

    print("\n[Setup] Initializing agents with game state...")
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
