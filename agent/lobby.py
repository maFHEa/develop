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
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
import uvicorn
import httpx


app = FastAPI(title="Mafia Agent Lobby")

# Track spawned agents and their log files
spawned_agents: Dict[int, Dict[str, Any]] = {}


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
    Find an available port by asking the OS to assign one.
    This is more reliable than scanning a range.
    
    Args:
        start: Ignored (kept for compatibility)
        end: Ignored (kept for compatibility)
        
    Returns:
        An available port number
    """
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(('', 0))
        s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        return s.getsockname()[1]


@app.on_event("shutdown")
def shutdown_event():
    """
    Clean up all spawned agent processes when the lobby shuts down.
    This prevents orphaned child processes.
    """
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

        # Create logs directory if it doesn't exist
        logs_dir = "logs"
        os.makedirs(logs_dir, exist_ok=True)

        # Launch player.py as subprocess with logs going to files
        # stdout and stderr both go to the same log file managed by player.py
        process = subprocess.Popen(
            [
                "./venv/bin/python", "-u",  # -u for unbuffered output
                "player.py",
                "--port", str(port),
                "--api-key", request.openai_api_key,
                "--agent-id", str(agent_id)
            ],
            cwd=".",
            # Let the logs be handled by player.py's logging system
            stdout=None,
            stderr=None
        )
        # Track the process
        spawned_agents[agent_id] = {"process": process, "port": port}
        
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
        "active_agents": sum(1 for p in spawned_agents.values() if p["process"].poll() is None)
    }


@app.delete("/agent/{agent_id}")
async def terminate_agent(agent_id: int):
    """
    Terminate a specific agent process.
    
    Args:
        agent_id: ID of the agent to terminate
    """
    agent_info = spawned_agents.get(agent_id)
    if not agent_info:
        raise HTTPException(status_code=404, detail=f"Agent {agent_id} not found")

    process = agent_info["process"]
    stderr_file = agent_info["stderr_file"]

    process.terminate()
    process.wait(timeout=5)
    stderr_file.close() # Close the log file
    
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
