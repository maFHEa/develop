"""
Agent Lobby - Spawner Server
Creates ONE AI agent per game session.
Multiple lobbies can run simultaneously for multiple games.
"""
import asyncio
import subprocess
import socket
from typing import Dict
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
import uvicorn
import httpx


app = FastAPI(title="Mafia Agent Lobby")

# Track spawned agents
spawned_agents: Dict[int, subprocess.Popen] = {}


class SpawnRequest(BaseModel):
    """Request to spawn a new AI agent for a game session"""
    openai_api_key: str
    game_session_id: str = "default"  # Optional game identifier


class SpawnResponse(BaseModel):
    """Response with new agent connection info"""
    agent_id: int
    address: str
    port: int


def find_free_port(start: int = 8001, end: int = 9000) -> int:
    """
    Find an available port in the specified range.
    
    Args:
        start: Starting port number
        end: Ending port number
        
    Returns:
        Available port number
        
    Raises:
        RuntimeError: If no free port found
    """
    for port in range(start, end):
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                s.bind(('', port))
                return port
        except OSError:
            continue
    raise RuntimeError(f"No free port found in range {start}-{end}")


@app.post("/spawn_agent", response_model=SpawnResponse)
async def spawn_agent(request: SpawnRequest):
    """
    Spawn ONE AI agent for a specific game session.
    Each game session should have its own dedicated agent.
    
    This launches agent/player.py as a separate process on a free port.
    
    Args:
        request: Contains OpenAI API key and optional game session ID
        
    Returns:
        Connection information for the new agent
    """
    import asyncio
    
    try:
        # Find available port
        port = find_free_port()
        
        # Generate agent ID
        agent_id = len(spawned_agents) + 1
        
        # Launch player.py as subprocess
        # Use the venv's python executable to ensure dependencies are loaded
        process = subprocess.Popen(
            [
                "./venv/bin/python", "player.py",
                "--port", str(port),
                "--api-key", request.openai_api_key,
                "--agent-id", str(agent_id)
            ],
            cwd=".",
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE
        )
        # Track the process
        spawned_agents[agent_id] = process
        
        address = f"http://localhost:{port}"
        
        print(f"[Lobby] Spawned Agent #{agent_id} at {address}, waiting for startup...")
        
        # Wait for agent to be ready
        async with httpx.AsyncClient(timeout=5) as client:
            for attempt in range(15):
                await asyncio.sleep(1)
                try:
                    response = await client.get(f"{address}/health")
                    if response.status_code == 200:
                        print(f"[Lobby] Agent #{agent_id} is ready!")
                        break
                except:
                    pass
                
                if attempt == 14:
                    print(f"[Lobby] Warning: Agent #{agent_id} did not respond to health check")
        
        return SpawnResponse(
            agent_id=agent_id,
            address=address,
            port=port
        )
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to spawn agent: {str(e)}")


@app.get("/health")
async def health_check():
    """Health check endpoint"""
    return {
        "status": "healthy",
        "spawned_agents": len(spawned_agents),
        "active_agents": sum(1 for p in spawned_agents.values() if p.poll() is None)
    }


@app.delete("/agent/{agent_id}")
async def terminate_agent(agent_id: int):
    """
    Terminate a specific agent process.
    
    Args:
        agent_id: ID of the agent to terminate
    """
    if agent_id not in spawned_agents:
        raise HTTPException(status_code=404, detail=f"Agent {agent_id} not found")
    
    process = spawned_agents[agent_id]
    process.terminate()
    process.wait(timeout=5)
    
    del spawned_agents[agent_id]
    
    return {"message": f"Agent {agent_id} terminated"}


if __name__ == "__main__":
    import argparse
    
    parser = argparse.ArgumentParser(description="Mafia Agent Lobby Server")
    parser.add_argument("--port", type=int, default=8000, help="Port to run lobby on (default: 8000)")
    parser.add_argument("--host", type=str, default="0.0.0.0", help="Host to bind to (default: 0.0.0.0)")
    
    args = parser.parse_args()
    
    print(f"[Lobby] Starting Agent Lobby Server on port {args.port}...")
    print("[Lobby] Ready to spawn AI agents on demand")
    uvicorn.run(app, host=args.host, port=args.port)
