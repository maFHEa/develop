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
                    data["attack_vector"],
                    data["heal_vector"],
                    data["investigate_vector"],
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
        dead_players: List[int]
    ) -> List[Tuple]:
        """Collect actions from all AI agents in parallel"""
        tasks = []
        ai_players = [p for p in players if not p.is_human]
        
        for player in ai_players:
            tasks.append(
                self.request_agent_action(
                    player, phase, message, survivors, dead_players
                )
            )
        
        results = await asyncio.gather(*tasks, return_exceptions=True)
        return list(zip(ai_players, results))
    
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
