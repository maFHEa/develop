"""
Network Communication Module - Agent communication and health checks
"""
import asyncio
from typing import List, Dict, Tuple
import httpx

from config import NETWORK_CONFIG
from models import Player


async def spawn_agents_from_lobbies(lobby_addresses: List[str], openai_api_key: str, game_id: str) -> List[str]:
    """
    Spawn AI agents from lobby servers CONCURRENTLY.
    
    Args:
        lobby_addresses: List of lobby server URLs
        openai_api_key: OpenAI API key for agents
        game_id: Short UUID to identify this game session
        
    Returns:
        List of spawned agent addresses
    """
    print(f"[Setup] Spawning {len(lobby_addresses)} AI agents concurrently from lobbies...")

    async def spawn_and_wait(client: httpx.AsyncClient, lobby_url: str, agent_num: int) -> str:
        """Helper to spawn one agent and wait for it to be healthy."""
        # Add a delay to space out the requests
        await asyncio.sleep((agent_num - 1) * 0.5)
        
        print(f"[Setup] Requesting Agent #{agent_num} spawn from {lobby_url}...")
        response = await client.post(
            f"{lobby_url}/spawn_agent",
            json={
                "game_id": game_id,
                "openai_api_key": openai_api_key
            }
        )
        response.raise_for_status()
        data = response.json()
        agent_address = data["address"]
        print(f"[Setup] Agent #{agent_num} spawned at {agent_address}, waiting for startup...")

        # Wait for agent to be fully ready (with retries)
        for attempt in range(15):
            await asyncio.sleep(1)
            if await check_agent_health(agent_address):
                print(f"[Setup] ✓ Agent #{agent_num} ready at {agent_address}")
                return agent_address
            print(f"[Setup] Agent #{agent_num} not ready yet, retrying ({attempt+1}/15)...")
        
        raise Exception(f"Agent #{agent_num} at {agent_address} failed to start after 15 seconds")

    async with httpx.AsyncClient(timeout=30) as client:
        tasks = [
            spawn_and_wait(client, lobby_url, i)
            for i, lobby_url in enumerate(lobby_addresses, 1)
        ]
        
        results = await asyncio.gather(*tasks, return_exceptions=True)
        
        agent_addresses = []
        for res in results:
            if isinstance(res, Exception):
                print(f"[Setup] ✗ FATAL: Failed to spawn an agent: {res}")
                raise res 
            agent_addresses.append(res)
            
    return agent_addresses


async def check_agent_health(address: str) -> bool:
    """
    Check if an agent server is healthy and responding.
    
    Args:
        address: Agent server URL
        
    Returns:
        True if healthy, False otherwise
    """
    try:
        async with httpx.AsyncClient(timeout=5) as client:
            response = await client.get(f"{address}/health")
            response.raise_for_status()
            return True
    except Exception:
        return False


class AgentCommunicator:
    """Handles all agent network communication"""
    
    @staticmethod
    async def initialize_agents(players: List[Player], public_context: str, game_id: str, num_players: int):
        """Send initialization data to all AI agents"""
        async with httpx.AsyncClient(timeout=NETWORK_CONFIG["connection_timeout"]) as client:
            tasks = []
            for player in players:
                if not player.is_human:
                    tasks.append(AgentCommunicator._init_single_agent(
                        client, player, public_context, game_id, num_players
                    ))
            
            results = await asyncio.gather(*tasks, return_exceptions=True)
            
            for i, result in enumerate(results):
                if isinstance(result, Exception):
                    print(f"[Engine] Failed to initialize agent {i+1}: {result}")
    
    @staticmethod
    async def _init_single_agent(
        client: httpx.AsyncClient, 
        player: Player, 
        public_context: str,
        game_id: str,
        num_players: int
    ):
        """Initialize a single AI agent"""
        try:
            response = await client.post(
                f"{player.address}/init",
                json={
                    "game_id": game_id,
                    "public_context": public_context,
                    "role": player.role,
                    "player_index": player.index,
                    "num_players": num_players
                }
            )
            response.raise_for_status()
            print(f"[Engine] Initialized {player.name}")
        except Exception as e:
            print(f"[Engine] Error initializing {player.name}: {e}")
            raise
    
    @staticmethod
    async def broadcast_update(
        players: List[Player], 
        phase: str, 
        message: str, 
        survivors: List[int], 
        dead: List[int],
        recently_killed: List[int] = None,
        recently_voted_out: int = -1
    ):
        """Send game state update to all AI agents with detailed information"""
        async with httpx.AsyncClient(timeout=NETWORK_CONFIG["connection_timeout"]) as client:
            tasks = []
            for player in players:
                if not player.is_human:
                    tasks.append(AgentCommunicator._update_single_agent(
                        client, player, phase, message, survivors, dead,
                        recently_killed or [], recently_voted_out
                    ))
            
            await asyncio.gather(*tasks, return_exceptions=True)
    
    @staticmethod
    async def _update_single_agent(
        client: httpx.AsyncClient,
        player: Player,
        phase: str,
        message: str,
        survivors: List[int],
        dead: List[int],
        recently_killed: List[int] = None,
        recently_voted_out: int = -1
    ):
        """Update a single AI agent with detailed game state"""
        try:
            await client.post(
                f"{player.address}/update",
                json={
                    "phase": phase,
                    "message": message,
                    "survivors": survivors,
                    "dead_players": dead,
                    "recently_killed": recently_killed or [],
                    "recently_voted_out": recently_voted_out
                }
            )
        except Exception as e:
            print(f"[Engine] Error updating {player.name}: {e}")
    
    @staticmethod
    async def broadcast_chat_message(players: List[Player], chat_data: Dict):
        """Broadcast a chat message to all AI agents"""
        async with httpx.AsyncClient(timeout=NETWORK_CONFIG["connection_timeout"]) as client:
            tasks = []
            for player in players:
                if not player.is_human:
                    tasks.append(AgentCommunicator._send_chat_to_agent(client, player, chat_data))
            
            await asyncio.gather(*tasks, return_exceptions=True)
    
    @staticmethod
    async def _send_chat_to_agent(client: httpx.AsyncClient, player: Player, chat_data: Dict):
        """Send a chat message to a single AI agent"""
        try:
            await client.post(
                f"{player.address}/chat/broadcast",
                json=chat_data
            )
        except Exception as e:
            print(f"[Engine] Error sending chat to {player.name}: {e}")
    
    @staticmethod
    async def start_agent_chat_phase(players: List[Player], duration_seconds: int, survivors: List[int], day_number: int):
        """Start chat phase for all agents"""
        print(f"[Engine] Starting chat phase (Day {day_number}, {duration_seconds}s)...")
        
        async with httpx.AsyncClient(timeout=10.0) as client:
            tasks = []
            for player in players:
                if not player.is_human and player.alive:
                    chat_request = {
                        "action": "start",
                        "duration_seconds": duration_seconds,
                        "survivors": survivors,
                        "turn": day_number
                    }
                    tasks.append(AgentCommunicator._send_chat_phase_request(client, player, chat_request))
            
            results = await asyncio.gather(*tasks, return_exceptions=True)
            
            success_count = sum(1 for r in results if not isinstance(r, Exception))
            print(f"[Engine] Chat phase started for {success_count}/{len(tasks)} agents")
    
    @staticmethod
    async def stop_agent_chat_phase(players: List[Player], day_number: int):
        """Stop chat phase for all agents"""
        print(f"[Engine] Stopping chat phase (Day {day_number})...")
        
        async with httpx.AsyncClient(timeout=10.0) as client:
            tasks = []
            for player in players:
                if not player.is_human:
                    chat_request = {"action": "stop"}
                    tasks.append(AgentCommunicator._send_chat_phase_request(client, player, chat_request))
            
            results = await asyncio.gather(*tasks, return_exceptions=True)
            
            success_count = sum(1 for r in results if not isinstance(r, Exception))
            print(f"[Engine] Chat phase stopped for {success_count}/{len(tasks)} agents")
    
    @staticmethod
    async def _send_chat_phase_request(client: httpx.AsyncClient, player: Player, request_data: Dict):
        """Send chat phase request to a single agent"""
        try:
            await client.post(
                f"{player.address}/chat/phase",
                json=request_data
            )
        except Exception as e:
            print(f"[Engine] Error sending chat phase request to {player.name}: {e}")
    
    @staticmethod
    async def request_agent_action(
        client: httpx.AsyncClient,
        player: Player,
        phase: str,
        message: str,
        survivors: List[int],
        dead: List[int]
    ) -> Tuple[str, List[str]]:
        """Request action from a single AI agent
        
        Returns:
            Tuple of (encrypted_action, chat_messages)
        """
        try:
            response = await client.post(
                f"{player.address}/request_action",
                json={
                    "phase": phase,
                    "message": message,
                    "survivors": survivors,
                    "dead_players": dead
                }
            )
            response.raise_for_status()
            data = response.json()
            return data["encrypted_action"], data.get("chat_messages", [])
        except Exception as e:
            print(f"[Engine] Error requesting action from {player.name}: {e}")
            raise
