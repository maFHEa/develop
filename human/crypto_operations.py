"""
Crypto Operations - Helper functions for encrypted game actions
Handles action collection, threshold decryption, and encrypted computations
"""
import asyncio
import sys
import os
from typing import List, Tuple
import httpx

# Add agent directory to path for security imports
agent_path = os.path.join(os.path.dirname(__file__), '..', 'agent')
if os.path.abspath(agent_path) not in sys.path:
    sys.path.append(os.path.abspath(agent_path))

from service.crypto.threshold_decryption import partial_decrypt_lead, fusion_decrypt
from service.crypto.vector_operations import create_zero_vector, create_one_hot_vector
from service.crypto.serialization import serialize_ciphertext, deserialize_ciphertext

from config import NETWORK_CONFIG


class CryptoOperations:
    """Handles encrypted operations for the game"""
    
    def __init__(self, cc, keypair, joint_public_key, num_players):
        self.cc = cc
        self.keypair = keypair
        self.joint_public_key = joint_public_key
        self.num_players = num_players
    
    async def collect_encrypted_actions(
        self, 
        players, 
        human_player_index: int,
        human_role: str,
        phase: str, 
        message: str,
        survivors: List[int],
        dead_players: List[int],
        get_human_action_callback
    ) -> Tuple[List[str], List[str], List[str]]:
        """
        Collect encrypted actions from all players.
        
        BLIND PROTOCOL: Every player sends 3 vectors regardless of role.
        Returns (attack_vectors, heal_vectors, investigate_vectors)
        Server cannot determine roles from traffic patterns.
        """
        attack_vectors = [None] * self.num_players
        heal_vectors = [None] * self.num_players
        investigate_vectors = [None] * self.num_players

        # Collect from AI agents
        async with httpx.AsyncClient(timeout=NETWORK_CONFIG["action_request_timeout"]) as client:
            tasks = []
            for player in players:
                if not player.is_human:
                    tasks.append(
                        self._request_agent_action(
                            client, player, phase, message, survivors, dead_players
                        )
                    )

            results = await asyncio.gather(*tasks, return_exceptions=True)

            for player, result in zip([p for p in players if not p.is_human], results):
                if not isinstance(result, Exception):
                    attack_vec, heal_vec, investigate_vec, chat_messages = result
                    attack_vectors[player.index] = attack_vec
                    heal_vectors[player.index] = heal_vec
                    investigate_vectors[player.index] = investigate_vec
                    # Chat messages would be handled by callback
                else:
                    print(f"[Engine] {player.name} failed, using zero vectors")
                    zero_vec = create_zero_vector(self.num_players, self.cc, self.joint_public_key)
                    zero_str = serialize_ciphertext(self.cc, zero_vec)
                    attack_vectors[player.index] = zero_str
                    heal_vectors[player.index] = zero_str
                    investigate_vectors[player.index] = zero_str

        # Get human action
        human_player = players[human_player_index]
        if human_player.alive and phase in ["night", "vote"]:
            human_attack, human_heal, human_investigate = await get_human_action_callback(
                phase, survivors, human_role
            )
            attack_vectors[human_player_index] = human_attack
            heal_vectors[human_player_index] = human_heal
            investigate_vectors[human_player_index] = human_investigate
        else:
            zero_vec = create_zero_vector(self.num_players, self.cc, self.joint_public_key)
            zero_str = serialize_ciphertext(self.cc, zero_vec)
            attack_vectors[human_player_index] = zero_str
            heal_vectors[human_player_index] = zero_str
            investigate_vectors[human_player_index] = zero_str

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

    async def _request_agent_action(
        self, client, player, phase, message, survivors, dead
    ) -> Tuple[str, str, str, List[str]]:
        """Request action from a single agent"""
        try:
            response = await client.post(
                f"{player.address}/request_action",
                json={
                    "phase": phase, 
                    "message": message, 
                    "survivors": survivors, 
                    "dead_players": dead
                }
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
            print(f"[Crypto] Error requesting action from {player.name}: {e}")
            raise

    async def threshold_decrypt_vector(self, encrypted_vector, players) -> List[int]:
        """
        Perform threshold decryption on an aggregated vector.
        Collects partial decryptions from all parties.
        """
        ct_b64 = serialize_ciphertext(self.cc, encrypted_vector)
        partial_results = []

        # Human (Lead) partial decryption
        human_partial = partial_decrypt_lead(self.cc, encrypted_vector, self.keypair.secretKey)
        partial_results.append(human_partial)

        # Agents' partial decryptions
        async with httpx.AsyncClient(timeout=NETWORK_CONFIG["connection_timeout"]) as client:
            for player in players:
                if not player.is_human:
                    try:
                        response = await client.post(
                            f"{player.address}/partial_decrypt",
                            json={
                                "ciphertext": ct_b64,
                                "is_lead": False
                            }
                        )
                        response.raise_for_status()
                        data = response.json()
                        partial_ct = deserialize_ciphertext(self.cc, data["partial_ciphertext"])
                        partial_results.append(partial_ct)
                    except Exception as e:
                        print(f"[Crypto] Error getting partial decrypt from {player.name}: {e}")
                        raise

        # Fusion
        final_plaintext = fusion_decrypt(self.cc, partial_results)
        return list(final_plaintext.GetPackedValue()[:self.num_players])

    def create_human_action_vectors(
        self, 
        target: int, 
        role: str, 
        phase: str
    ) -> Tuple[str, str, str]:
        """
        Create 3 encrypted vectors for human player action.
        Only role-appropriate vector contains real data, others are dummies.
        """
        # Determine action type
        if phase == "night":
            if role == "mafia":
                action_type = "attack"
            elif role == "doctor":
                action_type = "heal"
            elif role == "police":
                action_type = "investigate"
            else:
                action_type = None
        elif phase == "vote":
            action_type = "attack"  # Use attack vector slot for voting
        else:
            action_type = None

        # Generate real vector
        if target == -1 or action_type is None:
            real_vec = create_zero_vector(self.num_players, self.cc, self.joint_public_key)
        else:
            real_vec = create_one_hot_vector(self.num_players, target, self.cc, self.joint_public_key)

        # Create dummy vectors
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
        else:
            return dummy1_str, dummy2_str, dummy1_str  # All dummies
