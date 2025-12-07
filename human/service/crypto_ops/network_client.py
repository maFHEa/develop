"""
Network Client - Agent communication for crypto operations
"""
import asyncio
from typing import List, Tuple
import httpx

from config import NETWORK_CONFIG


class AgentNetworkClient:
    """Handles network communication with AI agents for crypto operations"""
    
    def __init__(self, timeout: float = None):
        self.timeout = timeout or NETWORK_CONFIG["action_request_timeout"]
    
    async def request_agent_action(
        self, 
        player, 
        phase: str, 
        message: str, 
        survivors: List[int], 
        dead_players: List[int]
    ) -> Tuple[str, str, str, List[str]]:
        """Request encrypted action from a single agent"""
        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                response = await client.post(
                    f"{player.address}/request_action",
                    json={
                        "phase": phase,
                        "message": message,
                        "survivors": survivors,
                        "dead_players": dead_players
                    }
                )
                response.raise_for_status()
                data = response.json()
                return (
                    data["vote_vector"],
                    data["attack_vector"],
                    data["heal_vector"],
                    data.get("chat_messages", [])
                )
        except Exception as e:
            print(f"[Network] Error requesting action from {player.name}: {e}")
            raise
    
    async def collect_agent_actions(
        self,
        players,
        phase: str,
        message: str,
        survivors: List[int],
        dead_players: List[int],
        cached_results: dict = None
    ) -> List[Tuple]:
        """Collect actions from all AI agents in parallel (병렬화)"""
        ai_players = [p for p in players if not p.is_human]
        results = []
        tasks = []
        # 캐시된 결과는 즉시 추가
        for player in ai_players:
            if cached_results and player.index in cached_results:
                data = cached_results[player.index]
                result = (
                    data["vote_vector"],
                    data["attack_vector"],
                    data["heal_vector"],
                    data.get("chat_messages", [])
                )
                results.append((player, result))
            else:
                tasks.append(
                    asyncio.create_task(
                        self.request_agent_action(player, phase, message, survivors, dead_players)
                    )
                )
        # 병렬 실행
        if tasks:
            task_results = await asyncio.gather(*tasks, return_exceptions=True)
            # 순서대로 매칭
            idx = 0
            for player in ai_players:
                if not (cached_results and player.index in cached_results):
                    result = task_results[idx]
                    results.append((player, result))
                    idx += 1
        return results
    
    async def request_partial_decryption(
        self,
        player,
        ciphertext_b64: str
    ) -> str:
        """Request partial decryption from an agent"""
        try:
            async with httpx.AsyncClient(
                timeout=NETWORK_CONFIG["connection_timeout"]
            ) as client:
                response = await client.post(
                    f"{player.address}/partial_decrypt",
                    json={
                        "ciphertext": ciphertext_b64,
                        "is_lead": False
                    }
                )
                response.raise_for_status()
                return response.json()["partial_ciphertext"]
        except Exception as e:
            print(f"[Network] Error getting partial decrypt from {player.name}: {e}")
            raise
    
    async def request_partial_investigation(
        self,
        player,
        ciphertext_b64: str
    ) -> str:
        """병렬 조사를 위한 partial decrypt 요청"""
        try:
            async with httpx.AsyncClient(
                timeout=NETWORK_CONFIG["connection_timeout"]
            ) as client:
                response = await client.post(
                    f"{player.address}/investigate_parallel",
                    json={"ciphertext": ciphertext_b64}
                )
                response.raise_for_status()
                return response.json()["partial_result"]
        except Exception as e:
            print(f"[Network] Error in parallel investigation from {player.name}: {e}")
            raise

    async def request_relay_decrypt(
        self,
        player,
        ciphertext_b64: str,
        remaining_order: List[int],
        player_addresses: List[str]
    ) -> dict:
        """릴레이 복호화 요청"""
        try:
            async with httpx.AsyncClient(
                timeout=NETWORK_CONFIG["connection_timeout"] * 2
            ) as client:
                response = await client.post(
                    f"{player.address}/relay_decrypt",
                    json={
                        "ciphertext": ciphertext_b64,
                        "partial_results": [],  # Start with empty list
                        "remaining_order": remaining_order,
                        "player_addresses": player_addresses
                    }
                )
                response.raise_for_status()
                return response.json()
        except Exception as e:
            print(f"[Network] Error in relay decrypt from {player.name}: {e}")
            raise
    
    async def collect_partial_decryptions(
        self,
        players,
        ciphertext_b64: str
    ) -> List[str]:
        """Collect partial decryptions from all AI agents"""
        tasks = []
        for player in players:
            if not player.is_human:
                tasks.append(
                    self.request_partial_decryption(player, ciphertext_b64)
                )
        
        return await asyncio.gather(*tasks)
    
    async def collect_encrypted_role_vectors(
        self,
        players
    ) -> List[str]:
        """Collect encrypted role vectors from all AI agents for police investigation"""
        tasks = []
        ai_players = [p for p in players if not p.is_human and p.alive]
        
        for player in ai_players:
            tasks.append(self._request_encrypted_role_vector(player))
        
        results = await asyncio.gather(*tasks, return_exceptions=True)
        
        # Build complete list with None for failed requests
        role_vectors = [None] * len(players)
        for i, (player, result) in enumerate(zip(ai_players, results)):
            if not isinstance(result, Exception):
                role_vectors[player.index] = result
            else:
                print(f"[Network] Agent {player.name} failed to provide role vector: {result}")
        
        return role_vectors
    
    async def _request_encrypted_role_vector(self, player) -> str:
        """Request encrypted role vector from an agent"""
        try:
            async with httpx.AsyncClient(
                timeout=NETWORK_CONFIG["connection_timeout"]
            ) as client:
                response = await client.post(
                    f"{player.address}/get_encrypted_role_vector",
                    json={}
                )
                response.raise_for_status()
                return response.json()["encrypted_role_vector"]
        except Exception as e:
            print(f"[Network] Error getting role vector from {player.name}: {e}")
            raise
