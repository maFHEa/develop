from openfhe import *
import random
from typing import List
import sys
import os
# Add agent directory to path for security imports
agent_path = os.path.join(os.path.dirname(__file__), '..', '..', 'agent')
if os.path.abspath(agent_path) not in sys.path:
    sys.path.append(os.path.abspath(agent_path))
from service.crypto.serialization import (
    serialize_ciphertext,
    deserialize_ciphertext,
)
from service.crypto.threshold_decryption import fusion_decrypt, partial_decrypt_lead
from service.crypto.roles import ROLE_ENCODING, role_to_one_hot, NUM_ROLE_TYPES, one_hot_to_role
from config import GAME_CONFIG, NETWORK_CONFIG


class RoleAssigner:
    """Role 생성 및 암호화만 담당"""
    
    def __init__(self, cc, joint_public_key):
        self.cc = cc
        self.joint_public_key = joint_public_key
    
    def generate_encrypted_roles(
        self, 
        num_players: int
    ) -> List[str]:
        """Role 생성, 셔플, 암호화"""
        # Role 분배
        role_dist = GAME_CONFIG["role_distribution"][num_players]
        roles = []
        for role, count in role_dist.items():
            roles.extend([role] * count)
        random.shuffle(roles)
        
        # 개별 암호화 (One-hot vector)
        encrypted_roles = []
        for role in roles:
            # Convert role to one-hot vector
            role_vector = role_to_one_hot(role)
            plaintext = self.cc.MakePackedPlaintext(role_vector)
            ciphertext = self.cc.Encrypt(self.joint_public_key, plaintext)
            encrypted_roles.append(
                serialize_ciphertext(self.cc, ciphertext)
            )
        
        return encrypted_roles
    
    def decrypt_own_role(
        self,
        encrypted_role: str,
        partial_results: List,
        keypair
    ) -> str:
        """자신의 role 복호화 (One-hot vector)"""
        my_role_enc = deserialize_ciphertext(self.cc, encrypted_role)
        
        # 자신의 partial 추가
        human_partial = partial_decrypt_lead(
            self.cc, my_role_enc, keypair.secretKey
        )
        partial_results.append(human_partial)
        
        # Fusion
        final_plaintext = fusion_decrypt(self.cc, partial_results)
        decrypted_vector = final_plaintext.GetPackedValue()[:NUM_ROLE_TYPES]
        
        # Convert one-hot vector to role name
        return one_hot_to_role(decrypted_vector)