"""
HTTP Server for Human Player - Relay Decrypt Endpoint
"""
from fastapi import FastAPI, HTTPException
import sys
import os

# Add agent directory to path
agent_path = os.path.join(os.path.dirname(__file__), '..', 'agent')
if os.path.abspath(agent_path) not in sys.path:
    sys.path.append(os.path.abspath(agent_path))

from service.crypto.serialization import serialize_ciphertext, deserialize_ciphertext
from service.crypto.threshold_decryption import partial_decrypt_lead

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
