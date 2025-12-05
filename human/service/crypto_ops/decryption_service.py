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
    
    async def parallel_decrypt(
        self,
        ciphertext_b64: str,
        requester_index: int,
        players
    ) -> List[int]:
        """
        병렬 복호화: 요청자가 모든 플레이어에게 동시에 partial decrypt 요청
        
        Args:
            ciphertext_b64: 암호화된 데이터 (Base64)
            requester_index: 요청자(발신자) 인덱스
            players: 모든 플레이어 리스트
        
        Returns:
            복호화된 벡터
        """
        # Deserialize ciphertext
        ct = deserialize_ciphertext(self.cc, ciphertext_b64)
        
        # Requester's partial decryption
        requester_partial = partial_decrypt_lead(self.cc, ct, self.keypair.secretKey)
        all_partials = [requester_partial]
        
        # Collect partials from all other players in parallel
        tasks = []
        for i, player in enumerate(players):
            if i != requester_index:  # Skip requester (already did partial decrypt above)
                tasks.append(self.network.request_partial_investigation(player, ciphertext_b64))
        
        if tasks:
            partial_results_b64 = await asyncio.gather(*tasks, return_exceptions=True)
            for idx, partial_result in enumerate(partial_results_b64):
                if isinstance(partial_result, Exception):
                    print(f"[Decrypt] Warning: Failed to get partial from player {idx}: {partial_result}")
                    continue
                try:
                    partial = deserialize_ciphertext(self.cc, partial_result)
                    all_partials.append(partial)
                except Exception as e:
                    print(f"[Decrypt] Warning: Failed to deserialize partial from player {idx}: {e}")
        
        # Fusion decrypt
        final_result = fusion_decrypt(self.cc, all_partials)
        return final_result.GetPackedValue()

    async def relay_decrypt(
        self,
        ciphertext_b64: str,
        requester_index: int,
        players
    ) -> List[int]:
        """
        Relay decryption: 발신자가 암호문을 보내면 다른 플레이어들이 순차적으로 부분 복호화.
        마지막에 발신자에게 돌아와서 최종 복호화.
        
        Args:
            ciphertext_b64: 암호화된 데이터 (Base64)
            requester_index: 요청자(발신자) 인덱스
            players: 모든 플레이어 리스트
        
        Returns:
            복호화된 벡터
        """
        # 요청자를 제외한 모든 플레이어에게 릴레이 (죽은 플레이어도 암호학적으로 참여 필요)
        player_order = [i for i in range(len(players)) if i != requester_index]
        
        if not player_order:
            # 다른 살아있는 플레이어가 없으면 요청자 혼자 복호화
            ct = deserialize_ciphertext(self.cc, ciphertext_b64)
            partial = partial_decrypt_lead(self.cc, ct, self.keypair.secretKey)
            result = fusion_decrypt(self.cc, [partial])
            return result.GetPackedValue()
        
        # 첫 번째 플레이어에게 릴레이 시작
        first_player = players[player_order[0]]
        remaining_order = player_order[1:] + [requester_index]  # 마지막에 요청자
        
        result = await self.network.request_relay_decrypt(
            first_player,
            ciphertext_b64,
            remaining_order,
            [p.address for p in players]
        )
        
        # We're the requester, should get partials back for fusion
        if "partial_results" in result:
            print(f"[Decrypt] Received {len(result['partial_results'])} partials, performing fusion decrypt")
            all_partials = [deserialize_ciphertext(self.cc, p) for p in result["partial_results"]]
            final_result = fusion_decrypt(self.cc, all_partials)
            decrypted_vector = final_result.GetPackedValue()
            
            # If human is police, show result
            if players[requester_index].role == "police":
                import sys, os
                sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..', '..', 'agent')))
                from service.crypto.roles import NUM_ROLE_TYPES
                is_mafia = sum(decrypted_vector[:NUM_ROLE_TYPES]) == 1
                print("=" * 60)
                print("🔍 POLICE INVESTIGATION RESULT (You are the police!)")
                print(f"   Target is: {'🎭 MAFIA' if is_mafia else '✅ NOT MAFIA'}")
                print("=" * 60)
            
            return decrypted_vector
        
        # Should not reach here
        return result["decrypted_vector"]
    
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
