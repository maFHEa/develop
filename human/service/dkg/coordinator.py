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
        
        # Send final mult key to all agents
        final_mult_key = self.protocol.cc.GetEvalMultKeyVector(
            self.protocol.joint_public_key.GetKeyTag()
        )[0]
        final_mult_key_b64 = serialize_eval_mult_key(self.protocol.cc, final_mult_key)
        
        await self.network.distribute_final_mult_key(final_mult_key_b64)
        print(" ✓ Final multiplication key distributed to all agents!")
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
        print(" Role Assignment (Distributed Shuffle + Blind Decryption)")
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
        
        # Distributed Shuffle: Agent들이 순차적으로 섞고 re-randomize함
        print("\n[Distributed Shuffle] Agents will shuffle and re-randomize encrypted roles...")
        
        # Serialize joint public key to send to agents
        from service.crypto.serialization import serialize_public_key
        joint_pk_b64 = serialize_public_key(self.protocol.cc, self.protocol.joint_public_key)
        
        # Host sequentially calls each agent to shuffle+rerandomize
        encrypted_roles = await self.network.initiate_distributed_shuffle(
            encrypted_roles,
            joint_pk_b64
        )
        
        print("✓ All agents completed shuffle+rerandomization (Host cannot know original order)")
            # Fallback to original if shuffle fails
        
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
        # 역할은 비밀 - 콘솔에 출력하지 않음
        
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

        # Store encrypted roles for later decryption at game end
        self.all_encrypted_roles = encrypted_roles

        return human_role, human_encrypted_role, encrypted_roles  # Return all encrypted roles

    async def decrypt_all_roles_for_game_end(self) -> List[str]:
        """
        게임 종료 시 모든 플레이어의 역할을 DKG threshold decryption으로 복호화.
        각 역할에 대해 모든 플레이어로부터 partial decryption을 수집하고 fusion.
        """
        from service.crypto.roles import one_hot_to_role, NUM_ROLE_TYPES
        from service.crypto.threshold_decryption import fusion_decrypt

        print("\n" + "="*50)
        print(" Game End: Revealing All Roles via DKG")
        print("="*50)

        if not hasattr(self, 'all_encrypted_roles') or not self.all_encrypted_roles:
            print("⚠️ No encrypted roles stored")
            return []

        all_roles = []

        for player_idx, encrypted_role_b64 in enumerate(self.all_encrypted_roles):
            print(f"\n[Decrypting] Player {player_idx}'s role...")

            # 모든 에이전트로부터 partial decryption 수집
            partial_strs = await self.network.collect_partial_decryptions(encrypted_role_b64)
            partials = [
                deserialize_ciphertext(self.protocol.cc, p)
                for p in partial_strs
            ]

            # Human의 partial 추가
            encrypted_role = deserialize_ciphertext(self.protocol.cc, encrypted_role_b64)
            human_partial = partial_decrypt_lead(
                self.protocol.cc,
                encrypted_role,
                self.protocol.keypair.secretKey
            )
            partials.append(human_partial)

            # Fusion decrypt
            final_plaintext = fusion_decrypt(self.protocol.cc, partials)
            decrypted_vector = final_plaintext.GetPackedValue()[:NUM_ROLE_TYPES]

            # Convert one-hot to role name
            role = one_hot_to_role(decrypted_vector)
            all_roles.append(role)
            print(f"  ✓ Player {player_idx}: {role.upper()}")

        print("\n" + "="*50)
        print(" All roles revealed!")
        print("="*50)

        return all_roles