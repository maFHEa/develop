from typing import List, Optional
import sys
import os
# Add agent directory to path for security imports
agent_path = os.path.join(os.path.dirname(__file__), '..', '..', '..', 'agent')
if os.path.abspath(agent_path) not in sys.path:
    sys.path.append(os.path.abspath(agent_path))
from service.crypto.serialization import (
    serialize_crypto_context,
    serialize_public_key,
    serialize_eval_mult_key,
    deserialize_eval_mult_key_object,
    deserialize_ciphertext,
    serialize_ciphertext,
)

from service.crypto.threshold_decryption import partial_decrypt_lead

from service.dkg.network_client import DKGNetworkClient
from service.dkg.protocol import DKGProtocol
from service.dkg.role_assigner import RoleAssigner

class DKGCoordinator:
    """전체 DKG 프로세스 조율"""
    
    def __init__(self):
        self.protocol: Optional[DKGProtocol] = None
        self.role_assigner: Optional[RoleAssigner] = None
        self.network: Optional[DKGNetworkClient] = None
        self.game_id: Optional[str] = None
    
    async def run_dkg_protocol(
        self, 
        num_players: int, 
        ai_addresses: List[str], 
        game_id: str
    ):
        """DKG 프로토콜 실행 (Facade)"""
        self.game_id = game_id
        self.protocol = DKGProtocol(num_players)
        self.network = DKGNetworkClient(ai_addresses)
        
        print("\n" + "="*50)
        print(" DKG: Distributed Key Generation")
        print("="*50)
        
        # Step 1: Setup
        cc_b64 = serialize_crypto_context(self.protocol.cc)
        await self.network.broadcast_setup(cc_b64, num_players, game_id)
        
        # Step 2: Key Chain
        initial_pk_b64 = self.protocol.initialize_lead_key()
        print("\n [Human] Lead key generated")
        
        final_pk_b64 = await self.network.chain_dkg_rounds(initial_pk_b64)
        self.protocol.finalize_joint_key(final_pk_b64)
        print("\n ✓ Joint public key established")
        
        # Step 3: Threshold Mult Keys (3-round)
        print("\n [Crypto] Threshold multiplication key generation...")
        
        # Round 2
        human_keyswitch = self.protocol.generate_keyswitch_key()
        human_key_b64 = serialize_eval_mult_key(
            self.protocol.cc, human_keyswitch
        )
        
        agent_keys_b64 = await self.network.collect_keyswitch_keys(
            game_id, human_key_b64
        )
        agent_keys = [
            deserialize_eval_mult_key_object(self.protocol.cc, k) 
            for k in agent_keys_b64
        ]
        
        combined = self.protocol.combine_keyswitch_keys(
            [human_keyswitch] + agent_keys
        )
        
        # Round 3
        human_mult = self.protocol.generate_multmult_key(combined)
        combined_b64 = serialize_eval_mult_key(self.protocol.cc, combined)
        
        agent_mult_b64 = await self.network.collect_multmult_keys(
            game_id,
            combined_b64,
            self.protocol.joint_public_key.GetKeyTag()
        )
        agent_mults = [
            deserialize_eval_mult_key_object(self.protocol.cc, k)
            for k in agent_mult_b64
        ]
        
        self.protocol.finalize_mult_keys([human_mult] + agent_mults)
        print(" ✓ Threshold multiplication key installed!")
        print("="*50)
        
        return (
            self.protocol.cc,
            self.protocol.keypair,
            self.protocol.joint_public_key
        )
    
    async def assign_roles_blindly(
        self, 
        num_players: int, 
        ai_addresses: List[str],
        player_addresses: List[str] = None
    ) -> tuple[str, str]:
        """Blind role 할당 - returns (role, encrypted_role_vector)"""
        print("="*50)
        print(" Role Assignment (Blind Threshold Decryption)")
        print("="*50)
        
        # Build player addresses if not provided
        if player_addresses is None:
            player_addresses = ["http://localhost:9000"] + ai_addresses
        
        # Role 생성
        self.role_assigner = RoleAssigner(
            self.protocol.cc,
            self.protocol.joint_public_key
        )
        encrypted_roles = self.role_assigner.generate_encrypted_roles(
            num_players
        )
        print(f"\n✓ Encrypted {len(encrypted_roles)} roles")
        
        # Human role 복호화
        print("\n[You] Decrypting your role...")
        partial_strs = await self.network.collect_partial_decryptions(
            encrypted_roles[0]
        )
        partials = [
            deserialize_ciphertext(self.protocol.cc, p) 
            for p in partial_strs
        ]
        
        human_role = self.role_assigner.decrypt_own_role(
            encrypted_roles[0],
            partials,
            self.protocol.keypair
        )
        human_encrypted_role = encrypted_roles[0]  # Store for investigation
        print(f"\n✓ Your role: {human_role.upper()}\n")
        
        # 에이전트들에게 role 분배
        joint_pk_b64 = serialize_public_key(
            self.protocol.cc, 
            self.protocol.joint_public_key
        )
        await self.network.distribute_encrypted_roles(
            encrypted_roles, joint_pk_b64, player_addresses
        )
        
        # 각 에이전트 복호화 도움
        for i in range(len(ai_addresses)):
            agent_role_enc = deserialize_ciphertext(
                self.protocol.cc, 
                encrypted_roles[i + 1]
            )
            human_partial = partial_decrypt_lead(
                self.protocol.cc,
                agent_role_enc,
                self.protocol.keypair.secretKey
            )
            human_partial_b64 = serialize_ciphertext(
                self.protocol.cc, human_partial
            )
            
            await self.network.help_agent_decrypt_role(
                i, encrypted_roles, human_partial_b64
            )
            print(f"✓ Agent {i+1} decrypted their role blindly")
        
        print("✓ All players received their roles blindly")
        print("="*50)
        
        return human_role, human_encrypted_role, encrypted_roles  # Return all encrypted roles