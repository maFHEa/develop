"""
DKG Manager - Distributed Key Generation and Blind Role Assignment
Handles all cryptographic setup and role distribution
"""
import asyncio
import random
import sys
import os
from typing import List
import httpx

# Add agent directory to path for security imports
agent_path = os.path.join(os.path.dirname(__file__), '..', 'agent')
if os.path.abspath(agent_path) not in sys.path:
    sys.path.append(os.path.abspath(agent_path))

from security import (
    create_openfhe_context,
    serialize_crypto_context,
    deserialize_crypto_context,
    serialize_public_key,
    deserialize_public_key,
    serialize_eval_mult_key,
    deserialize_eval_mult_key,
    deserialize_eval_mult_key_object,
    serialize_ciphertext,
    deserialize_ciphertext,
    dkg_keygen_lead,
    partial_decrypt_lead,
    fusion_decrypt,
    ROLE_ENCODING
)
from openfhe import BINARY

from config import GAME_CONFIG, NETWORK_CONFIG


class DKGManager:
    """Manages Distributed Key Generation and blind role assignment"""
    
    def __init__(self):
        self.cc = None
        self.keypair = None
        self.joint_public_key = None
    
    async def run_dkg_protocol(self, num_players: int, ai_addresses: List[str], game_id: str):
        """
        Execute Distributed Key Generation protocol.
        Final result: Joint public key that requires ALL parties to decrypt
        """
        self.game_id = game_id
        
        print("\n" + "="*50)
        print(" DKG: Distributed Key Generation")
        print("="*50)

        # Step 1: Create and distribute crypto context
        self.cc = create_openfhe_context(num_players)
        cc_b64 = serialize_crypto_context(self.cc)

        async with httpx.AsyncClient(timeout=NETWORK_CONFIG["connection_timeout"]) as client:
            tasks = []
            for i, address in enumerate(ai_addresses):
                tasks.append(self._send_dkg_setup(client, address, cc_b64, num_players, i + 1, game_id))
            await asyncio.gather(*tasks, return_exceptions=True)

        # Step 2: Build key chain
        # Human generates lead key
        self.keypair = dkg_keygen_lead(self.cc)
        current_pk_b64 = serialize_public_key(self.cc, self.keypair.publicKey)

        print(f"\n [Human] Lead key generated")
        print(f"   pk₀ = KeyGen(cc)")

        # Chain through AI agents
        async with httpx.AsyncClient(timeout=NETWORK_CONFIG["connection_timeout"]) as client:
            for i, address in enumerate(ai_addresses):
                response = await client.post(
                    f"{address}/dkg_round",
                    json={"round_number": i + 2, "previous_public_key": current_pk_b64}
                )
                if not response.is_success:
                    print(f"❌ Agent {i+1} error: {response.status_code}")
                    print(f"   Response: {response.text}")
                response.raise_for_status()
                data = response.json()
                current_pk_b64 = data["public_key"]
                print(f" [Agent {i+1}] Extended key chain")
                print(f"   pk₁ ⊕ pk₂ ⊕ ... ⊕ pk_{i+1}")

        # Step 3: Final joint key
        self.joint_public_key = deserialize_public_key(self.cc, current_pk_b64)
        print(f"\n ✓ Joint public key established (n-of-n threshold)")
        print(f"   Requires ALL {num_players} parties to decrypt")
        
        # Step 4: Generate threshold evaluation multiplication keys (3-round protocol)
        # Following OpenFHE official threshold-fhe.py example
        print(f"\n [Crypto] Threshold multiplication key generation (3-round protocol)...")
        
        # Round 2: Lead (human) generates KeySwitch key
        print(f" [Round 2] Human: KeySwitchGen(sk, sk)...")
        evalMultKey_human = self.cc.KeySwitchGen(self.keypair.secretKey, self.keypair.secretKey)
        
        # Round 2: Each agent generates KeySwitch key and sends to human
        print(f" [Round 2] Agents: MultiKeySwitchGen...")
        eval_keys = [evalMultKey_human]
        
        async with httpx.AsyncClient(timeout=30.0) as client:
            for i, address in enumerate(ai_addresses):
                response = await client.post(
                    f"{address}/generate_keyswitchgen",
                    json={
                        "game_id": self.game_id,
                        "prev_key": serialize_eval_mult_key(self.cc, evalMultKey_human)
                    }
                )
                response.raise_for_status()
                data = response.json()
                agent_key = deserialize_eval_mult_key_object(self.cc, data["eval_key"])
                eval_keys.append(agent_key)
                print(f" [Agent {i+1}] KeySwitch key received")
        
        # Combine all KeySwitch keys
        print(f" [Round 2] Combining {len(eval_keys)} KeySwitch keys...")
        combined_key = eval_keys[0]
        for key in eval_keys[1:]:
            combined_key = self.cc.MultiAddEvalKeys(combined_key, key, self.joint_public_key.GetKeyTag())
        
        # Round 3: Each party generates MultiMult key
        print(f" [Round 3] Generating MultiMult keys...")
        evalMultHuman = self.cc.MultiMultEvalKey(
            self.keypair.secretKey,
            combined_key,
            self.joint_public_key.GetKeyTag()
        )
        mult_keys = [evalMultHuman]
        
        async with httpx.AsyncClient(timeout=30.0) as client:
            for i, address in enumerate(ai_addresses):
                response = await client.post(
                    f"{address}/generate_multmultkey",
                    json={
                        "game_id": self.game_id,
                        "combined_key": serialize_eval_mult_key(self.cc, combined_key),
                        "key_tag": self.joint_public_key.GetKeyTag()
                    }
                )
                response.raise_for_status()
                data = response.json()
                agent_mult_key = deserialize_eval_mult_key_object(self.cc, data["mult_key"])
                mult_keys.append(agent_mult_key)
                print(f" [Agent {i+1}] MultiMult key received")
        
        # Combine all MultiMult keys
        print(f" [Round 3] Combining {len(mult_keys)} MultiMult keys...")
        final_key = mult_keys[0]
        for key in mult_keys[1:]:
            final_key = self.cc.MultiAddEvalMultKeys(final_key, key, final_key.GetKeyTag())
        
        # Insert final key into context
        self.cc.InsertEvalMultKey([final_key])
        print(f" ✓ Threshold multiplication key installed!")
        print(f"   EvalMult now available for joint public key")
        
        print("="*50)
        
        return self.cc, self.keypair, self.joint_public_key

    async def _send_dkg_setup(self, client, address, cc_b64, num_players, player_index, game_id):
        """Send DKG setup to a single agent"""
        try:
            await client.post(
                f"{address}/dkg_setup",
                json={
                    "game_id": game_id,
                    "crypto_context": cc_b64,
                    "num_players": num_players,
                    "player_index": player_index
                }
            )
        except Exception as e:
            print(f"[DKG] Error setting up agent {player_index}: {e}")
            raise

    async def assign_roles_blindly(self, num_players: int, ai_addresses: List[str]) -> str:
        """
        Assign roles using blind threshold decryption.
        
        BLIND PROTOCOL:
        - Each player decrypts ONLY their own role
        - For player i to decrypt role[i]:
          1. All other players (j ≠ i) send partial decryptions
          2. Player i adds their own partial decryption last
          3. Player i performs fusion to get their role
        - Result: NO ONE knows anyone else's role (not even the server)
        
        Returns: human_role
        """
        print("="*50)
        print(" Role Assignment (Blind Threshold Decryption)")
        print("="*50)

        # Step 1: Generate, shuffle, and encrypt roles INDIVIDUALLY
        role_dist = GAME_CONFIG["role_distribution"][num_players]
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

        # Step 2: Human (player 0) decrypts their role
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
        
        print(f"\n Your role: {human_role.upper()}\n")

        # Step 3: Help each agent decrypt their role
        joint_pk_b64 = serialize_public_key(self.cc, self.joint_public_key)
        async with httpx.AsyncClient(timeout=NETWORK_CONFIG["connection_timeout"]) as client:
            # First, send encrypted roles to all agents
            for i, address in enumerate(ai_addresses):
                agent_index = i + 1
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
        
        return human_role
