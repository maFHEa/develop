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
from service.crypto.context import create_openfhe_context
from service.crypto.serialization import (
    serialize_crypto_context,
    deserialize_crypto_context,
    serialize_public_key,
    deserialize_public_key,
    serialize_ciphertext,
    deserialize_ciphertext,
)
from service.crypto.key_generation import dkg_keygen_lead, dkg_keygen_join
from service.crypto.threshold_decryption import (
    partial_decrypt_lead,
    partial_decrypt_main,
    fusion_decrypt,
)
from service.crypto.vector_operations import (
    create_one_hot_vector,
    create_zero_vector,
    aggregate_encrypted_vectors,
    compute_killed_vector,
    multiply_encrypted_vectors,
)
from service.crypto.roles import encode_roles, decode_roles, ROLE_ENCODING

from config import GAME_CONFIG, NETWORK_CONFIG
from models import Player


# ============================================================================
# Game State
# ============================================================================



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
        self.human_role: Optional[str] = None  # Only human's role is known to server
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
        chain_parts = ["Human(sk₀)"]

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
        print(f"\n Key Chain: {' → '.join(chain_parts)} → pk_joint")
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
        
        BLIND PROTOCOL:
        - Each player decrypts ONLY their own role
        - For player i to decrypt role[i]:
          1. All other players (j ≠ i) send partial decryptions
          2. Player i adds their own partial decryption last
          3. Player i performs fusion to get their role
        - Result: NO ONE knows anyone else's role (not even the server)
        """
        print("="*50)
        print(" Role Assignment (Blind Threshold Decryption)")
        print("="*50)

        # Step 1: Generate, shuffle, and encrypt roles INDIVIDUALLY
        role_dist = GAME_CONFIG["role_distribution"][self.num_players]
        roles = []
        for role, count in role_dist.items():
            roles.extend([role] * count)
        random.shuffle(roles)

        # Encrypt each role separately
        encrypted_roles_list = []
        for role in roles:
            encoded = ROLE_ENCODING[role]
            plaintext = self.cc.MakePackedPlaintext([encoded])
            ciphertext = self.cc.Encrypt(self.joint_public_key, plaintext)
            encrypted_roles_list.append(serialize_ciphertext(self.cc, ciphertext))

        print(f"\n Encrypted {len(roles)} individual role assignments")
        print(f" Each player will decrypt only their own role")

        # Step 2: Each player decrypts their own role
        # Human (player 0) decrypts encrypted_roles_list[0]
        print(f"\n[You] Decrypting your role...")
        my_role_enc = deserialize_ciphertext(self.cc, encrypted_roles_list[0])
        
        # Collect partial decryptions from ALL agents (excluding self)
        partial_results = []
        async with httpx.AsyncClient(timeout=NETWORK_CONFIG["connection_timeout"]) as client:
            for i, address in enumerate(ai_addresses):
                response = await client.post(
                    f"{address}/partial_decrypt",
                    json={
                        "ciphertext": encrypted_roles_list[0],
                        "is_lead": False
                    }
                )
                response.raise_for_status()
                data = response.json()
                partial_ct = deserialize_ciphertext(self.cc, data["partial_ciphertext"])
                partial_results.append(partial_ct)
        
        # Add human's partial decryption LAST
        human_partial = partial_decrypt_lead(self.cc, my_role_enc, self.keypair.secretKey)
        partial_results.append(human_partial)
        
        # Fusion to get human's role
        final_plaintext = fusion_decrypt(self.cc, partial_results)
        decrypted_value = final_plaintext.GetPackedValue()[0]
        human_role = next(role for role, code in ROLE_ENCODING.items() if code == decrypted_value)
        
        self.human_role = human_role
        self.players.append(Player(0, is_human=True))
        print(f"\n Your role: {human_role.upper()}\n")

        # Step 3: Send encrypted roles to agents for them to decrypt
        joint_pk_b64 = serialize_public_key(self.cc, self.joint_public_key)
        async with httpx.AsyncClient(timeout=NETWORK_CONFIG["connection_timeout"]) as client:
            for i, address in enumerate(ai_addresses):
                agent_index = i + 1
                self.players.append(Player(agent_index, is_human=False, address=address))
                
                # Send agent's encrypted role
                await client.post(
                    f"{address}/blind_role_assignment",
                    json={
                        "my_index": agent_index,
                        "encrypted_roles": encrypted_roles_list,
                        "joint_public_key": joint_pk_b64
                    }
                )
            
            # Now help each agent decrypt their role
            for i, address in enumerate(ai_addresses):
                agent_index = i + 1
                agent_role_enc = deserialize_ciphertext(self.cc, encrypted_roles_list[agent_index])
                
                # Collect partial decryptions from EVERYONE except this agent
                partial_results = []
                
                # Human's partial
                human_partial = partial_decrypt_lead(self.cc, agent_role_enc, self.keypair.secretKey)
                partial_results.append(serialize_ciphertext(self.cc, human_partial))
                
                # Other agents' partials
                for j, other_address in enumerate(ai_addresses):
                    if j != i:  # Skip the target agent
                        response = await client.post(
                            f"{other_address}/partial_decrypt",
                            json={
                                "ciphertext": encrypted_roles_list[agent_index],
                                "is_lead": False
                            }
                        )
                        response.raise_for_status()
                        partial_results.append(response.json()["partial_ciphertext"])
                
                # Send partials to agent for final fusion
                await client.post(
                    f"{address}/complete_role_decryption",
                    json={"partial_ciphertexts": partial_results}
                )
                
                print(f"✓ Agent {agent_index} decrypted their role blindly")
        
        print(f"✓ All players received their roles blindly")
        print("="*50)

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

    async def check_win_condition(self) -> Optional[str]:
        """
        Check win condition using encrypted role information.
        
        PROBLEM: Server doesn't know anyone's role!
        SOLUTION: Each alive player encrypts their role (1=mafia, 0=other)
                  Server aggregates and threshold decrypts the sum.
        
        TODO: Implement proper encrypted role aggregation
        For now, we cannot check win condition without revealing roles.
        Game will continue indefinitely until manual stop.
        """
        # Temporary: Just count alive players
        alive_count = sum(1 for p in self.players if p.alive)
        
        if alive_count <= 1:
            return "draw"  # Only 1 or 0 players left
        
        # Cannot determine winner without role information
        # This needs to be implemented with encrypted role vectors
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

    async def collect_encrypted_actions(self, phase: str, message: str) -> Tuple[List[str], List[str], List[str]]:
        """
        Collect encrypted actions from all players.
        
        BLIND PROTOCOL: Every player sends 3 vectors regardless of role.
        Returns (attack_vectors, heal_vectors, investigate_vectors)
        Server cannot determine roles from traffic patterns.
        """
        survivors = self.get_survivors()
        dead = self.get_dead_players()
        
        attack_vectors = [None] * self.num_players
        heal_vectors = [None] * self.num_players
        investigate_vectors = [None] * self.num_players

        # Collect from AI agents
        async with httpx.AsyncClient(timeout=NETWORK_CONFIG["action_request_timeout"]) as client:
            tasks = []
            for player in self.players:
                if not player.is_human:
                    tasks.append(self._request_agent_action(client, player, phase, message, survivors, dead))

            results = await asyncio.gather(*tasks, return_exceptions=True)

            for player, result in zip([p for p in self.players if not p.is_human], results):
                if not isinstance(result, Exception):
                    attack_vec, heal_vec, investigate_vec, chat_messages = result
                    attack_vectors[player.index] = attack_vec
                    heal_vectors[player.index] = heal_vec
                    investigate_vectors[player.index] = investigate_vec
                    for msg in chat_messages:
                        print(f"[{player.name}] {msg}")
                        await self.broadcast_chat_message(player.index, msg)
                else:
                    print(f"[Engine] {player.name} failed, using zero vectors")
                    zero_vec = create_zero_vector(self.num_players, self.cc, self.joint_public_key)
                    zero_str = serialize_ciphertext(self.cc, zero_vec)
                    attack_vectors[player.index] = zero_str
                    heal_vectors[player.index] = zero_str
                    investigate_vectors[player.index] = zero_str

        # Get human action
        human_player = self.players[self.human_player_index]
        if human_player.alive and phase in ["night", "vote"]:
            human_attack, human_heal, human_investigate = await self.get_human_action(phase, survivors)
            attack_vectors[self.human_player_index] = human_attack
            heal_vectors[self.human_player_index] = human_heal
            investigate_vectors[self.human_player_index] = human_investigate
        else:
            zero_vec = create_zero_vector(self.num_players, self.cc, self.joint_public_key)
            zero_str = serialize_ciphertext(self.cc, zero_vec)
            attack_vectors[self.human_player_index] = zero_str
            heal_vectors[self.human_player_index] = zero_str
            investigate_vectors[self.human_player_index] = zero_str

        # Fill missing with zero vectors
        zero_vec = create_zero_vector(self.num_players, self.cc, self.joint_public_key)
        zero_str = serialize_ciphertext(self.cc, zero_vec)
        
        for i in range(self.num_players):
            if attack_vectors[i] is None:
                attack_vectors[i] = zero_str
            if heal_vectors[i] is None:
                heal_vectors[i] = zero_str
            if investigate_vectors[i] is None:
                investigate_vectors[i] = zero_str

        return attack_vectors, heal_vectors, investigate_vectors

    async def _request_agent_action(self, client, player, phase, message, survivors, dead) -> Tuple[str, str, str, List[str]]:
        try:
            response = await client.post(
                f"{player.address}/request_action",
                json={"phase": phase, "message": message, "survivors": survivors, "dead_players": dead}
            )
            response.raise_for_status()
            data = response.json()
            return (
                data["attack_vector"],
                data["heal_vector"], 
                data["investigate_vector"],
                data.get("chat_messages", [])
            )
        except Exception as e:
            print(f"[Engine] Error requesting action from {player.name}: {e}")
            raise

    async def get_human_action(self, phase: str, survivors: List[int]) -> Tuple[str, str, str]:
        """
        Get human player action.
        
        BLIND PROTOCOL: Returns 3 vectors (attack, heal, investigate).
        Only the role-appropriate vector contains real action, others are dummies.
        """
        human = self.players[self.human_player_index]

        print(f"\n{'='*60}")
        print(f"YOUR TURN - {phase.upper()} PHASE")
        print(f"Your Role: {self.human_role.upper()}")
        print(f"Survivors: {survivors}")
        print(f"{'='*60}")

        # Determine if human can act
        can_act = False
        action_type = None
        
        if phase == "night":
            if self.human_role == "mafia":
                can_act = True
                action_type = "attack"
            elif self.human_role == "doctor":
                can_act = True
                action_type = "heal"
            elif self.human_role == "police":
                can_act = True
                action_type = "investigate"
        elif phase == "vote":
            can_act = True
            action_type = "vote"

        if not can_act:
            print("[You] You have no action this phase")
            zero_vec = create_zero_vector(self.num_players, self.cc, self.joint_public_key)
            zero_str = serialize_ciphertext(self.cc, zero_vec)
            return zero_str, zero_str, zero_str

        valid_targets = [i for i in survivors if i != self.human_player_index]
        action_name = action_type if phase == "night" else "vote for"

        while True:
            try:
                print(f"\nValid targets: {valid_targets}")
                target_input = input(f"Enter player index to {action_name} (or -1 to skip): ")
                target = int(target_input)

                # Generate 3 vectors: real + 2 dummies
                if target == -1:
                    real_vec = create_zero_vector(self.num_players, self.cc, self.joint_public_key)
                elif target in valid_targets:
                    real_vec = create_one_hot_vector(self.num_players, target, self.cc, self.joint_public_key)
                    print(f"[You] Action encrypted and submitted")
                else:
                    print(f"Invalid target. Choose from {valid_targets}")
                    continue

                # Create dummy vectors
                from service.crypto.vector_operations import create_zero_vector
                dummy1 = create_zero_vector(self.num_players, self.cc, self.joint_public_key)
                dummy2 = create_zero_vector(self.num_players, self.cc, self.joint_public_key)
                
                real_str = serialize_ciphertext(self.cc, real_vec)
                dummy1_str = serialize_ciphertext(self.cc, dummy1)
                dummy2_str = serialize_ciphertext(self.cc, dummy2)

                # Assign based on role
                if action_type == "attack":
                    return real_str, dummy1_str, dummy2_str
                elif action_type == "heal":
                    return dummy1_str, real_str, dummy2_str
                elif action_type == "investigate":
                    return dummy1_str, dummy2_str, real_str
                else:  # vote phase - use attack vector slot
                    return real_str, dummy1_str, dummy2_str

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

        print("[Engine] Collecting encrypted actions (3 vectors per player)...")
        attack_vectors, heal_vectors, investigate_vectors = await self.collect_encrypted_actions("night", message)

        print("[Engine] Deserializing attack vectors...")
        attacks_enc = [deserialize_ciphertext(self.cc, enc) for enc in attack_vectors]
        
        print("[Engine] Deserializing heal vectors...")
        heals_enc = [deserialize_ciphertext(self.cc, enc) for enc in heal_vectors]
        
        print("[Engine] Deserializing investigate vectors...")
        investigations_enc = [deserialize_ciphertext(self.cc, enc) for enc in investigate_vectors]

        print("[Engine] Aggregating all attack vectors (blind protocol)...")
        total_attacks = aggregate_encrypted_vectors(self.cc, attacks_enc)
        
        print("[Engine] Aggregating all heal vectors (blind protocol)...")
        total_heals = aggregate_encrypted_vectors(self.cc, heals_enc)

        print("[Engine] Computing kill results homomorphically...")
        killed_vector_enc = compute_killed_vector(self.cc, total_attacks, total_heals, self.num_players, self.joint_public_key)

        print("[Engine] Threshold decrypting aggregated result...")
        killed_vector = await self.threshold_decrypt_vector(killed_vector_enc)

        self.last_killed = []
        for i, killed in enumerate(killed_vector):
            if killed > 0 and self.players[i].alive:
                self.players[i].alive = False
                self.last_killed.append(i)

        await self.handle_police_investigation(investigations_enc)
        await self.announce_night_results()

    async def handle_police_investigation(self, investigations_enc):
        """
        Police investigation using encrypted role vectors.
        
        Server aggregates all investigate_vectors to find which player was investigated.
        Then computes dot product with each player's encrypted_role_vector.
        Result > 0 means investigated player is mafia.
        
        BLIND: Server doesn't know who is police, but can compute results.
        """
        # Aggregate all investigations (only police sent real vector, others sent dummies)
        total_investigation = aggregate_encrypted_vectors(self.cc, investigations_enc)
        
        # For each player, compute investigation result
        investigation_results = []
        for player in self.players:
            if player.encrypted_role_vector is not None:
                role_enc = deserialize_ciphertext(self.cc, player.encrypted_role_vector)
                result_enc = multiply_encrypted_vectors(self.cc, total_investigation, role_enc)
                investigation_results.append(result_enc)
            else:
                # No role assigned yet (should not happen)
                investigation_results.append(None)
        
        # Decrypt all results
        decrypted_results = []
        for result_enc in investigation_results:
            if result_enc is not None:
                result = await self.threshold_decrypt_vector(result_enc)
                decrypted_results.append(sum(result))
            else:
                decrypted_results.append(0)
        
        # Check if any player is mafia (server doesn't know WHO was investigated)
        is_mafia = any(val > 0 for val in decrypted_results)
        
        # Broadcast result to human player (if they are police)
        human_player = self.players[self.human_player_index]
        if human_player.alive and self.human_role == "police":
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

        print("[Engine] Collecting encrypted votes (3 vectors per player)...")
        attack_vectors, heal_vectors, investigate_vectors = await self.collect_encrypted_actions("vote", message)

        # For voting, we use attack_vector slot
        vote_vectors = [deserialize_ciphertext(self.cc, enc) for enc in attack_vectors]
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
