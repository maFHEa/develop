"""
Agent Lobby - Spawner Server
Creates ONE AI agent per game session.
Multiple lobbies can run simultaneously for multiple games.
"""
import asyncio
import subprocess
import socket
import os
from typing import Dict, Any
from contextlib import asynccontextmanager
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
import uvicorn
import httpx


# Track spawned agents
spawned_agents: Dict[int, Dict[str, Any]] = {}


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Lifespan context manager for startup and shutdown events"""
    # Startup
    yield
    # Shutdown
    print("[Lobby] Shutting down. Terminating all spawned agents...")
    for agent_id, agent_info in list(spawned_agents.items()):
        process = agent_info["process"]
        
        print(f"[Lobby] Terminating Agent #{agent_id} (PID: {process.pid})...")
        process.terminate()
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            print(f"[Lobby] Agent #{agent_id} did not terminate, killing.")
            process.kill()
    print("[Lobby] All agents terminated.")


app = FastAPI(title="Mafia Agent Lobby", lifespan=lifespan)


class SpawnRequest(BaseModel):
    """Request to spawn a new AI agent for a game session"""
    game_id: str  # Short UUID to identify game session
    openai_api_key: str


class SpawnResponse(BaseModel):
    """Response with new agent connection info"""
    agent_id: int
    address: str
    port: int


def find_free_port(start: int = 8001, end: int = 9000) -> int:
    """
    Find an available port by asking the OS to assign one.
    This is more reliable than scanning a range.
    """
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(('', 0))
        s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        return s.getsockname()[1]


@app.post("/spawn_agent", response_model=SpawnResponse)
async def spawn_agent(request: SpawnRequest):
    """
    Spawn ONE AI agent for a specific game session.
    """
    try:
        port = find_free_port()
        agent_id = len(spawned_agents) + 1

        logs_dir = "logs"
        os.makedirs(logs_dir, exist_ok=True)

        process = subprocess.Popen(
            [
                "./venv/bin/python", "-u",
                "player.py",
                "--port", str(port),
                "--api-key", request.openai_api_key,
                "--game-id", request.game_id,
                "--agent-id", str(agent_id)
            ],
            cwd=".",
            stdout=None,
            stderr=None
        )
        spawned_agents[agent_id] = {"process": process, "port": port}
        
        address = f"http://localhost:{port}"
        print(f"[Lobby] Spawned Agent #{agent_id} at {address}, waiting for startup...")
        
        async with httpx.AsyncClient(timeout=15) as client:
            for attempt in range(15):
                await asyncio.sleep(1)
                try:
                    response = await client.get(f"{address}/health")
                    if response.status_code == 200:
                        print(f"[Lobby] Agent #{agent_id} is ready!")
                        break
                except httpx.RequestError:
                    if attempt == 14:
                        print(f"[Lobby] ❌ Agent #{agent_id} did not respond to health check after 15s")
                        raise
        
        return SpawnResponse(agent_id=agent_id, address=address, port=port)
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to spawn agent: {str(e)}")


@app.get("/health")
async def health_check():
    """Health check endpoint"""
    return {
        "status": "healthy",
        "spawned_agents": len(spawned_agents),
        "active_agents": sum(1 for p in spawned_agents.values() if p["process"].poll() is None)
    }


@app.delete("/agent/{agent_id}")
async def terminate_agent(agent_id: int):
    """
    Terminate a specific agent process.
    """
    agent_info = spawned_agents.get(agent_id)
    if not agent_info:
        raise HTTPException(status_code=404, detail=f"Agent {agent_id} not found")

    process = agent_info["process"]
    process.terminate()
    try:
        process.wait(timeout=5)
    except subprocess.TimeoutExpired:
        process.kill()
    
    del spawned_agents[agent_id]
    
    return {"message": f"Agent {agent_id} terminated"}


if __name__ == "__main__":
    import argparse
    
    parser = argparse.ArgumentParser(description="Mafia Agent Lobby Server")
    parser.add_argument("--port", type=int, default=8000, help="Port to run lobby on")
    parser.add_argument("--host", type=str, default="0.0.0.0", help="Host to bind to")
    
    args = parser.parse_args()
    
    print(f"[Lobby] Starting Agent Lobby Server on port {args.port}...")
    uvicorn.run(app, host=args.host, port=args.port)