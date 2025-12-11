from typing import List
import sys
import os

# Add agent directory to path for security imports
agent_path = os.path.join(os.path.dirname(__file__), '..', '..', 'agent')
if os.path.abspath(agent_path) not in sys.path:
    sys.path.append(os.path.abspath(agent_path))

from service.crypto.context import create_openfhe_context
from service.crypto.serialization import (
    serialize_public_key,
    deserialize_public_key,

)
from service.crypto.key_generation import dkg_keygen_lead

class DKGProtocol:
    """순수 DKG 암호화 로직만 담당"""
    
    def __init__(self, num_players: int):
        self.cc = create_openfhe_context(num_players)
        self.keypair = None
        self.joint_public_key = None
    
    def initialize_lead_key(self):
        """Human이 리드 키 생성"""
        self.keypair = dkg_keygen_lead(self.cc)
        return serialize_public_key(self.cc, self.keypair.publicKey)
    
    def finalize_joint_key(self, final_pk_b64: str):
        """최종 조인트 키 설정"""
        self.joint_public_key = deserialize_public_key(self.cc, final_pk_b64)
    
    def generate_keyswitch_key(self):
        """KeySwitch 키 생성 (Round 2)"""
        return self.cc.KeySwitchGen(
            self.keypair.secretKey, 
            self.keypair.secretKey
        )
    
    def combine_keyswitch_keys(self, keys: List):
        """KeySwitch 키들 결합"""
        combined = keys[0]
        for key in keys[1:]:
            combined = self.cc.MultiAddEvalKeys(
                combined, key, 
                self.joint_public_key.GetKeyTag()
            )
        return combined
    
    def generate_multmult_key(self, combined_key):
        """MultiMult 키 생성 (Round 3)"""
        return self.cc.MultiMultEvalKey(
            self.keypair.secretKey,
            combined_key,
            self.joint_public_key.GetKeyTag()
        )
    
    def finalize_mult_keys(self, mult_keys: List):
        """MultiMult 키들 결합하고 context에 삽입"""
        final_key = mult_keys[0]
        for key in mult_keys[1:]:
            final_key = self.cc.MultiAddEvalMultKeys(
                final_key, key, final_key.GetKeyTag()
            )
        self.cc.InsertEvalMultKey([final_key])