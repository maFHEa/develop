"""
HTTP Server for Human Player - Relay Decrypt Endpoint
"""
from fastapi import FastAPI, HTTPException
from typing import Optional
import sys
import os

# Add agent directory to path
agent_path = os.path.join(os.path.dirname(__file__), '..', 'agent')
if os.path.abspath(agent_path) not in sys.path:
    sys.path.append(os.path.abspath(agent_path))

from service.crypto.serialization import serialize_ciphertext, deserialize_ciphertext
from service.crypto.threshold_decryption import partial_decrypt_lead, fusion_decrypt

app = FastAPI()

# Global state - set by GameEngine
class ServerState:
    def __init__(self):
        self.cc = None
        self.keypair = None
        self.role = None
        self.dkg_coordinator = None

state = ServerState()


def initialize_server(cc, keypair, role, dkg_coordinator=None):
    """Initialize server with crypto context and keys"""
    state.cc = cc
    state.keypair = keypair
    state.role = role
    state.dkg_coordinator = dkg_coordinator


@app.post("/relay_decrypt")
async def relay_decrypt(request: dict):
    """
    Relay decryption endpoint - same as agent
    """
    try:
        if state.cc is None or state.keypair is None:
            raise ValueError("Keys not initialized")

        ciphertext_b64 = request["ciphertext"]
        partial_results_b64 = request.get("partial_results", [])
        remaining_order = request["remaining_order"]
        player_addresses = request["player_addresses"]
        
        print(f"[HTTP] 🔄 Relay decrypt - remaining_order: {remaining_order}")
        
        # Deserialize and perform partial decryption
        ciphertext = deserialize_ciphertext(state.cc, ciphertext_b64)
        partial = partial_decrypt_lead(state.cc, ciphertext, state.keypair.secretKey)
        
        # Add to list
        partial_b64 = serialize_ciphertext(state.cc, partial)
        partial_results_b64.append(partial_b64)
        
        print(f"[HTTP] 🔄 Relay decrypt: {len(partial_results_b64)} partials collected")
        
        if len(remaining_order) == 0:
            # Last player: return partials to requester
            print(f"[HTTP] 🔄 Last player, returning {len(partial_results_b64)} partials to requester")
            return {"partial_results": partial_results_b64}
        
        # Forward to next player
        import httpx
        next_index = remaining_order[0]
        next_address = player_addresses[next_index]
        new_remaining = remaining_order[1:]
        
        print(f"[HTTP] 🔄 Forwarding to {next_address}")
        
        async with httpx.AsyncClient(timeout=60.0) as client:
            response = await client.post(
                f"{next_address}/relay_decrypt",
                json={
                    "ciphertext": ciphertext_b64,
                    "partial_results": partial_results_b64,
                    "remaining_order": new_remaining,
                    "player_addresses": player_addresses
                }
            )
            response.raise_for_status()
            return response.json()
            
    except Exception as e:
        print(f"[HTTP] ❌ Relay decrypt error: {e}")
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/investigate_parallel")
async def investigate_parallel(request: dict):
    """
    병렬 조사: 암호문을 받아서 partial decrypt만 수행
    Agent와 동일한 엔드포인트
    """
    try:
        if state.cc is None or state.keypair is None:
            raise ValueError("Keys not initialized")
        
        ciphertext_b64 = request["ciphertext"]
        ciphertext = deserialize_ciphertext(state.cc, ciphertext_b64)
        
        # Partial decrypt (human uses partial_decrypt_lead)
        partial = partial_decrypt_lead(state.cc, ciphertext, state.keypair.secretKey)
        partial_b64 = serialize_ciphertext(state.cc, partial)
        
        print(f"[HTTP] 🔍 Investigate parallel: partial decrypt completed")
        
        return {"partial_result": partial_b64}
        
    except Exception as e:
        print(f"[HTTP] ❌ Investigate parallel error: {e}")
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))
