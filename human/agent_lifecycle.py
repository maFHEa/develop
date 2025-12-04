"""
Agent Lifecycle Manager - Handles agent spawning and cleanup
"""
import asyncio
from typing import List, Dict
import httpx
from urllib.parse import urlparse


class AgentLifecycleManager:
    """Manages agent lifecycle including cleanup when agents die"""
    
    def __init__(self):
        # Map agent address to lobby address
        self.agent_to_lobby: Dict[str, str] = {}
    
    def register_agent(self, agent_address: str, lobby_address: str):
        """Register an agent with its parent lobby"""
        self.agent_to_lobby[agent_address] = lobby_address
    
    async def shutdown_agent(self, agent_address: str):
        """
        Gracefully shutdown an agent when it dies.
        
        Steps:
        1. Send shutdown signal to agent
        2. Request lobby to terminate agent process
        """
        print(f"[Lifecycle] Shutting down agent at {agent_address}...")
        
        # Step 1: Graceful shutdown signal to agent
        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                await client.post(f"{agent_address}/shutdown")
                print(f"[Lifecycle] ✓ Sent shutdown signal to {agent_address}")
        except Exception as e:
            print(f"[Lifecycle] ⚠ Could not send shutdown signal: {e}")
        
        # Step 2: Request lobby to terminate process
        lobby_address = self.agent_to_lobby.get(agent_address)
        if lobby_address:
            try:
                # Extract port from agent address
                parsed = urlparse(agent_address)
                port = parsed.port
                
                async with httpx.AsyncClient(timeout=5.0) as client:
                    await client.post(
                        f"{lobby_address}/shutdown_agent",
                        json={"port": port}
                    )
                    print(f"[Lifecycle] ✓ Lobby terminated agent process on port {port}")
            except Exception as e:
                print(f"[Lifecycle] ⚠ Could not terminate via lobby: {e}")
        
        # Unregister
        if agent_address in self.agent_to_lobby:
            del self.agent_to_lobby[agent_address]
    
    async def shutdown_multiple_agents(self, agent_addresses: List[str]):
        """Shutdown multiple agents in parallel"""
        tasks = [self.shutdown_agent(addr) for addr in agent_addresses]
        await asyncio.gather(*tasks, return_exceptions=True)
    
    async def cleanup_all(self):
        """Cleanup all registered agents"""
        if self.agent_to_lobby:
            print(f"[Lifecycle] Cleaning up {len(self.agent_to_lobby)} agents...")
            await self.shutdown_multiple_agents(list(self.agent_to_lobby.keys()))
