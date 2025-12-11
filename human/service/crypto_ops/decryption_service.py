"""
Decryption Service - Threshold decryption operations
"""
import sys
import os
import asyncio
from typing import List

# Add agent directory to path
agent_path = os.path.join(os.path.dirname(__file__), '..', '..', '..', 'agent')
if os.path.abspath(agent_path) not in sys.path:
    sys.path.append(os.path.abspath(agent_path))

from service.crypto.threshold_decryption import partial_decrypt_lead, fusion_decrypt
from service.crypto.serialization import serialize_ciphertext, deserialize_ciphertext

from .network_client import AgentNetworkClient


class ThresholdDecryptionService:
    """Handles threshold decryption with multiple parties"""
    
    def __init__(self, cc, keypair, num_players: int):
        self.cc = cc
        self.keypair = keypair
        self.num_players = num_players
        self.network = AgentNetworkClient()
    
    async def decrypt_vector(
        self,
        encrypted_vector,
        players
    ) -> List[int]:
        """
        Perform threshold decryption on an aggregated vector.
        
        Collects partial decryptions from all parties and combines them.
        """
        # Serialize for network transmission
        ct_b64 = serialize_ciphertext(self.cc, encrypted_vector)
        
        # Human (Lead) partial decryption
        human_partial = partial_decrypt_lead(
            self.cc, encrypted_vector, self.keypair.secretKey
        )
        partial_results = [human_partial]
        
        # Collect agents' partial decryptions
        agent_partials_b64 = await self.network.collect_partial_decryptions(
            players, ct_b64
        )
        
        # Deserialize agent partials
        for partial_b64 in agent_partials_b64:
            partial_ct = deserialize_ciphertext(self.cc, partial_b64)
            partial_results.append(partial_ct)
        
        # Fusion
        final_plaintext = fusion_decrypt(self.cc, partial_results)
        return list(final_plaintext.GetPackedValue()[:self.num_players])
