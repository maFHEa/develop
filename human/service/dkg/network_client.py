import asyncio
import httpx
from typing import List
import sys
import os

class DKGNetworkClient:
    """에이전트 API 통신만 담당"""
    
    def __init__(self, ai_addresses: List[str]):
        self.ai_addresses = ai_addresses
    
    async def broadcast_setup(
        self, 
        cc_b64: str, 
        num_players: int, 
        game_id: str
    ):
        """모든 에이전트에게 setup 전송"""
        async with httpx.AsyncClient(timeout=30.0) as client:
            tasks = [
                self._send_setup(
                    client, addr, cc_b64, 
                    num_players, i + 1, game_id
                )
                for i, addr in enumerate(self.ai_addresses)
            ]
            await asyncio.gather(*tasks, return_exceptions=True)
    
    async def chain_dkg_rounds(self, initial_pk_b64: str) -> str:
        """DKG 라운드 체인 실행"""
        current_pk_b64 = initial_pk_b64
        
        async with httpx.AsyncClient(timeout=30.0) as client:
            for i, address in enumerate(self.ai_addresses):
                response = await client.post(
                    f"{address}/dkg_round",
                    json={
                        "round_number": i + 2,
                        "previous_public_key": current_pk_b64
                    }
                )
                response.raise_for_status()
                current_pk_b64 = response.json()["public_key"]
                print(f" [Agent {i+1}] Extended key chain")
        
        return current_pk_b64
    
    async def collect_keyswitch_keys(
        self, 
        game_id: str, 
        human_key_b64: str
    ) -> List:
        """Round 2: KeySwitch 키 수집"""
        keys = []
        async with httpx.AsyncClient(timeout=30.0) as client:
            for i, address in enumerate(self.ai_addresses):
                response = await client.post(
                    f"{address}/generate_keyswitchgen",
                    json={
                        "game_id": game_id,
                        "prev_key": human_key_b64
                    }
                )
                response.raise_for_status()
                keys.append(response.json()["eval_key"])
                print(f" [Agent {i+1}] KeySwitch key received")
        return keys
    
    async def collect_multmult_keys(
        self,
        game_id: str,
        combined_key_b64: str,
        key_tag: str
    ) -> List:
        """Round 3: MultiMult 키 수집"""
        keys = []
        async with httpx.AsyncClient(timeout=30.0) as client:
            for i, address in enumerate(self.ai_addresses):
                response = await client.post(
                    f"{address}/generate_multmultkey",
                    json={
                        "game_id": game_id,
                        "combined_key": combined_key_b64,
                        "key_tag": key_tag
                    }
                )
                response.raise_for_status()
                keys.append(response.json()["mult_key"])
                print(f" [Agent {i+1}] MultiMult key received")
        return keys
    
    async def collect_partial_decryptions(
        self, 
        ciphertext_b64: str
    ) -> List[str]:
        """Partial 복호화 수집"""
        partials = []
        async with httpx.AsyncClient(timeout=30.0) as client:
            for address in self.ai_addresses:
                response = await client.post(
                    f"{address}/partial_decrypt",
                    json={
                        "ciphertext": ciphertext_b64,
                        "is_lead": False
                    }
                )
                response.raise_for_status()
                partials.append(response.json()["partial_ciphertext"])
        return partials
    
    async def distribute_encrypted_roles(
        self, 
        encrypted_roles: List[str],
        joint_pk_b64: str,
        player_addresses: List[str]
    ):
        """암호화된 role들을 에이전트에게 분배"""
        async with httpx.AsyncClient(timeout=30.0) as client:
            for i, address in enumerate(self.ai_addresses):
                await client.post(
                    f"{address}/blind_role_assignment",
                    json={
                        "my_index": i + 1,
                        "encrypted_roles": encrypted_roles,
                        "joint_public_key": joint_pk_b64,
                        "player_addresses": player_addresses
                    }
                )
    async def help_agent_decrypt_role(
        self,
        agent_index: int,
        encrypted_roles: List[str],
        human_partial: str
    ):
        """에이전트의 role 복호화 도움"""
        address = self.ai_addresses[agent_index]
        
        # 다른 에이전트들의 partial 수집
        partials = [human_partial]
        
        async with httpx.AsyncClient(timeout=30.0) as client:
            for j, other_addr in enumerate(self.ai_addresses):
                if j != agent_index:
                    response = await client.post(
                        f"{other_addr}/partial_decrypt",
                        json={
                            "ciphertext": encrypted_roles[agent_index + 1],
                            "is_lead": False
                        }
                    )
                    response.raise_for_status()
                    partials.append(response.json()["partial_ciphertext"])
            
            # Partial들을 에이전트에게 전송
            await client.post(
                f"{address}/complete_role_decryption",
                json={"partial_ciphertexts": partials}
            )
    
    async def _send_setup(
        self, 
        client, 
        address, 
        cc_b64, 
        num_players, 
        player_index, 
        game_id
    ):
        """Setup 전송"""
        await client.post(
            f"{address}/dkg_setup",
            json={
                "game_id": game_id,
                "crypto_context": cc_b64,
                "num_players": num_players,
                "player_index": player_index
            }
        )