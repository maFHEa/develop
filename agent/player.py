"""
AI Agent Player - Autonomous Mafia Game Participant
Uses OpenAI Agents SDK for stateful autonomous behavior with session-based memory
Supports DKG (Distributed Key Generation) for threshold FHE
"""
import argparse
import asyncio
import json
import os
import sys
import logging
import tempfile
import base64
import httpx
from typing import Optional, List
from fastapi import FastAPI, HTTPException
import uvicorn
from openfhe import BINARY

from agents import Agent, Runner, ToolCallItem, ToolCallOutputItem, MessageOutputItem, ItemHelpers, SQLiteSession

from model.chat import GameChatHistory, ChatMessage
from suspicion import SuspicionNoteManager, PoliceNoteManager
from agent_logic import create_mafia_agent, create_action_prompt

from model import (
    InitRequest,
    GameUpdateRequest,
    ActionResponse,
    ChatBroadcast,
    DKGSetupRequest,
    DKGSetupResponse,
    DKGRoundRequest,
    DKGRoundResponse,
    PartialDecryptRequest,
    PartialDecryptResponse,
    RoleAssignmentRequest
)

from service.crypto.context import create_openfhe_context

from service.crypto.key_generation import (
    dkg_keygen_lead,
    dkg_keygen_join
)

from service.crypto.serialization import (
    serialize_ciphertext,
    deserialize_ciphertext,
    deserialize_crypto_context,
    serialize_public_key,
    deserialize_public_key,
    serialize_ciphertext,
    deserialize_ciphertext
)

from service.crypto.threshold_decryption import (
    partial_decrypt_lead,
    partial_decrypt_main
)

from service.crypto.vector_operations import (
    create_one_hot_vector,
    create_zero_vector
)

# ============================================================================
# Global State & Setup
# ============================================================================

logger = logging.getLogger(__name__)

class AgentState:
    def __init__(self):
        self.game_id: Optional[str] = None  # Short UUID for game session
        self.agent_id: Optional[int] = None

        # OpenFHE crypto state
        self.cc = None  # CryptoContext
        self.keypair = None  # KeyPair (contains secretKey)
        self.joint_public_key = None  # Final joint public key after DKG

        self.role: Optional[str] = None
        self.player_index: Optional[int] = None
        self.num_players: int = 0
        self.agent: Optional[Agent] = None
        self.alive: bool = True
        self.current_phase: str = "setup"
        self.current_turn: int = 0
        self.chat_history: GameChatHistory = GameChatHistory()
        self.suspicion_notes: Optional[SuspicionNoteManager] = None
        self.session: Optional[SQLiteSession] = None
        self.last_read_msg_id: int = -1
        self.pending_action_target: Optional[int] = None
        self.action_submitted: bool = False
        self.pending_chat_messages: List[str] = []
        self.my_encrypted_role: Optional[str] = None  # For blind role protocol
        self.encrypted_role_vector: Optional[str] = None  # For police investigation
        self.all_encrypted_roles: List[str] = []  # All players' encrypted roles
        self.last_investigation_result: Optional[dict] = None  # Police investigation result

state = AgentState()
app = FastAPI(title="Mafia AI Agent")


# ============================================================================
# Helper Functions
# ============================================================================

async def send_dummy_investigation_packets():
    """
    경찰이 아닌 플레이어가 네트워크 obfuscation을 위해 dummy packet 전송
    2-5초 랜덤 딜레이 후 다른 플레이어들에게 investigate_parallel 요청
    """
    import random
    
    # 2-5초 랜덤 딜레이
    delay = random.uniform(2.0, 5.0)
    await asyncio.sleep(delay)
    
    logger.info(f"🕵️ Sending dummy investigation packets (role: {state.role})")
    
    # Dummy 0 벡터 생성
    dummy_ciphertext = serialize_ciphertext(
        state.cc, 
        create_zero_vector(state.num_players, state.cc, state.joint_public_key)
    )
    
    # 다른 플레이어들에게 dummy packet 전송
    tasks = []
    for i in range(state.num_players):
        if i != state.player_index:
            # 주소 추정 (Human=9000, Agent 1=port+1000, etc)
            if i == 0:
                port = 9000  # Human player
            else:
                port = 8764 + i  # Agents start from different ports
            
            player_address = f"http://localhost:{port}"
            tasks.append(_send_single_dummy_packet(player_address, dummy_ciphertext))
    
    if tasks:
        await asyncio.gather(*tasks, return_exceptions=True)
    
    logger.info(f"🕵️ Dummy packets sent to {len(tasks)} players")


async def _send_single_dummy_packet(address: str, ciphertext_b64: str):
    """Helper to send single dummy investigate packet"""
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            await client.post(
                f"{address}/investigate_parallel",
                json={"ciphertext": ciphertext_b64}
            )
    except Exception:
        pass  # Ignore errors silently


# ============================================================================
# DKG (Distributed Key Generation) Endpoints
# ============================================================================

@app.post("/dkg_setup", response_model=DKGSetupResponse)
async def dkg_setup(request: DKGSetupRequest):
    """
    Phase 1 of DKG: Receive crypto context from host.
    """
    try:
        state.game_id = request.game_id
        state.num_players = request.num_players
        state.player_index = request.player_index

        # Deserialize crypto context
        state.cc = deserialize_crypto_context(request.crypto_context)

        logger.info("━" * 60)
        logger.info(f"🔐 DKG SETUP | Player #{state.player_index}")
        logger.info(f"   Game ID: {state.game_id}")
        logger.info(f"   Players: {state.num_players}")
        logger.info("━" * 60)

        return DKGSetupResponse(
            success=True,
            message=f"DKG setup complete for player {state.player_index}"
        )
    except Exception as e:
        logger.error(f"❌ DKG setup error: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/dkg_round", response_model=DKGRoundResponse)
async def dkg_round(request: DKGRoundRequest):
    """
    Phase 2 of DKG: Generate or join key generation.

    Round 1: Lead party generates initial keypair
    Round 2+: Join with previous public key
    """
    try:
        if state.cc is None:
            raise ValueError("CryptoContext not initialized. Call /dkg_setup first.")

        if request.round_number == 1 and request.previous_public_key is None:
            # Lead party - generate initial keypair
            state.keypair = dkg_keygen_lead(state.cc)
            logger.info(f"🔑 DKG Round 1: Lead party key generated")
        else:
            # Joining party - use previous public key
            prev_pk = deserialize_public_key(state.cc, request.previous_public_key)
            state.keypair = dkg_keygen_join(state.cc, prev_pk)
            logger.info(f"🔑 DKG Round {request.round_number}: Joined with previous public key")

        # Serialize our public key for the next party
        pk_b64 = serialize_public_key(state.cc, state.keypair.publicKey)
        
        # Note: Multiplication key will be generated later using MultiEvalMultKeyGen

        return DKGRoundResponse(
            public_key=pk_b64,
            success=True
        )
    except Exception as e:
        logger.error(f"❌ DKG round error: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/generate_keyswitchgen")
async def generate_keyswitchgen(request: dict):
    """
    Round 2 of threshold multiplication key generation.
    Generate MultiKeySwitchGen with local secret key.
    """
    try:
        if state.cc is None or state.keypair is None:
            raise ValueError("Keys not initialized. Complete DKG first.")
        
        game_id = request.get("game_id")
        if game_id != state.game_id:
            raise ValueError(f"Game ID mismatch: expected {state.game_id}, got {game_id}")
        
        from service.crypto.serialization import deserialize_eval_mult_key_object, serialize_eval_mult_key
        # Deserialize previous key (from human)
        prev_key_b64 = request.get("prev_key")
        prev_key = deserialize_eval_mult_key_object(state.cc, prev_key_b64)
        
        # Generate local KeySwitch key
        local_key = state.cc.MultiKeySwitchGen(
            state.keypair.secretKey,
            state.keypair.secretKey,
            prev_key
        )
        
        logger.info(f"✓ Round 2: Generated MultiKeySwitchGen")
        
        # Serialize and return
        local_key_b64 = serialize_eval_mult_key(state.cc, local_key)
        
        return {
            "eval_key": local_key_b64,
            "success": True
        }
    except Exception as e:
        logger.error(f"❌ Round 2 KeySwitchGen error: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/generate_multmultkey")
async def generate_multmultkey(request: dict):
    """
    Round 3 of threshold multiplication key generation.
    Transform combined key with local secret key using MultiMultEvalKey.
    """
    try:
        if state.cc is None or state.keypair is None:
            raise ValueError("Keys not initialized. Complete DKG first.")
        
        game_id = request.get("game_id")
        if game_id != state.game_id:
            raise ValueError(f"Game ID mismatch: expected {state.game_id}, got {game_id}")
        
        from service.crypto.serialization import deserialize_eval_mult_key_object, serialize_eval_mult_key
        
        # Deserialize combined key
        combined_key_b64 = request.get("combined_key")
        combined_key = deserialize_eval_mult_key_object(state.cc, combined_key_b64)
        key_tag = request.get("key_tag")
        
        # Transform with local secret key
        mult_key = state.cc.MultiMultEvalKey(
            state.keypair.secretKey,
            combined_key,
            key_tag
        )
        
        logger.info(f"✓ Round 3: Generated MultiMultEvalKey")
        
        # Serialize and return
        mult_key_b64 = serialize_eval_mult_key(state.cc, mult_key)
        
        return {
            "mult_key": mult_key_b64,
            "success": True
        }
    except Exception as e:
        logger.error(f"❌ Round 3 MultiMultEvalKey error: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/generate_mult_key_round2")
async def generate_mult_key_round2(request: dict):
    """
    Legacy endpoint - redirects to generate_keyswitchgen.
    """
    return await generate_keyswitchgen(request)


@app.post("/generate_mult_key_round3")
async def generate_multmultkey_legacy(request: dict):
    """
    Legacy endpoint - redirects to generate_multmultkey.
    """
    return await generate_multmultkey(request)


@app.post("/generate_mult_key")
async def generate_mult_key(request: dict):
    """
    Legacy endpoint - kept for compatibility.
    Generate evaluation multiplication key in local context.
    """
    try:
        if state.cc is None or state.keypair is None:
            raise ValueError("Keys not initialized. Complete DKG first.")
        
        game_id = request.get("game_id")
        if game_id != state.game_id:
            raise ValueError(f"Game ID mismatch: expected {state.game_id}, got {game_id}")
        
        # Generate evaluation multiplication key for local context
        state.cc.EvalMultKeyGen(state.keypair.secretKey)
        logger.info(f"✓ Evaluation multiplication key generated and inserted")
        
        return {
            "success": True
        }
    except Exception as e:
        logger.error(f"❌ Mult key generation error: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/get_eval_mult_key")
async def get_eval_mult_key(request: dict):
    """
    Serialize and return the locally generated evaluation multiplication key.
    This is a new endpoint required for the server to collect key pieces.
    """
    try:
        if state.cc is None or state.keypair is None:
            raise ValueError("Keys not initialized. Complete DKG first.")

        # Ensure the key is generated
        # Note: OpenFHE internally manages the key, we just need to ensure it's been generated
        if not state.cc.GetEvalMultKeyVector(state.keypair.publicKey.GetKeyTag()):
             state.cc.EvalMultKeyGen(state.keypair.secretKey)
             logger.info("🔑 Generated EvalMultKey on demand.")

        # Serialize the key using a temporary file
        with tempfile.NamedTemporaryFile(delete=False, suffix=".key") as f:
            key_path = f.name
        
        state.cc.SerializeEvalMultKey(key_path, state.keypair.publicKey, BINARY)
        
        with open(key_path, "rb") as f:
            key_data = f.read()
        
        os.remove(key_path)

        key_b64 = base64.b64encode(key_data).decode('utf-8')
        logger.info(f"✓ Serialized and returning local EvalMultKey")

        return {"success": True, "eval_mult_key": key_b64}

    except Exception as e:
        logger.error(f"❌ Get EvalMultKey error: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/receive_mult_keys")
async def receive_mult_keys(request: dict):
    """
    Receive and insert all evaluation multiplication keys from all participants.
    This enables threshold homomorphic multiplication operations.
    """
    try:
        if state.cc is None:
            raise ValueError("CryptoContext not initialized. Complete DKG setup first.")
        
        game_id = request.get("game_id")
        if game_id != state.game_id:
            raise ValueError(f"Game ID mismatch: expected {state.game_id}, got {game_id}")
        
        mult_keys = request.get("mult_keys", [])
        
        from service.crypto.serialization import deserialize_eval_mult_key
        
        # Insert all multiplication keys into context
        # Skip keys that are already inserted (our own key)
        inserted_count = 0
        skipped_count = 0
        for i, key_b64 in enumerate(mult_keys):
            try:
                deserialize_eval_mult_key(state.cc, key_b64)
                inserted_count += 1
            except RuntimeError as e:
                # Key already exists - this is expected for our own key
                if "Can not save a EvalMultKeys vector" in str(e):
                    skipped_count += 1
                    continue
                else:
                    raise
        
        logger.info(f"✓ Inserted {inserted_count} new multiplication keys, skipped {skipped_count} existing keys")
        
        return {
            "success": True,
            "keys_received": inserted_count
        }
    except Exception as e:
        logger.error(f"❌ Mult keys reception error: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/partial_decrypt", response_model=PartialDecryptResponse)
async def partial_decrypt(request: PartialDecryptRequest):
    """
    Perform partial decryption with local secret key.

    This is the key security feature: Each party contributes a partial
    decryption, but no single party can decrypt alone.
    """
    try:
        if state.cc is None or state.keypair is None:
            raise ValueError("Keys not initialized. Complete DKG first.")

        # Deserialize ciphertext
        ciphertext = deserialize_ciphertext(state.cc, request.ciphertext)

        # Perform partial decryption
        if request.is_lead:
            partial = partial_decrypt_lead(state.cc, ciphertext, state.keypair.secretKey)
            logger.info(f"🔓 Partial decryption (Lead)")
        else:
            partial = partial_decrypt_main(state.cc, ciphertext, state.keypair.secretKey)
            logger.info(f"🔓 Partial decryption (Main)")

        # Serialize partial result
        partial_b64 = serialize_ciphertext(state.cc, partial)

        return PartialDecryptResponse(
            partial_ciphertext=partial_b64,
            success=True
        )
    except Exception as e:
        logger.error(f"❌ Partial decrypt error: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/investigate_parallel")
async def investigate_parallel(request: dict):
    """병렬 조사: 암호문을 받아서 partial decrypt만 수행"""
    try:
        if state.cc is None or state.keypair is None:
            raise ValueError("Keys not initialized")
        
        ciphertext_b64 = request["ciphertext"]
        ciphertext = deserialize_ciphertext(state.cc, ciphertext_b64)
        
        # Partial decrypt
        partial = partial_decrypt_main(state.cc, ciphertext, state.keypair.secretKey)
        partial_b64 = serialize_ciphertext(state.cc, partial)
        
        return {"partial_result": partial_b64}
        
    except Exception as e:
        logger.error(f"❌ Parallel investigation error: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/investigate_parallel")
async def investigate_parallel(request: dict):
    """병렬 조사: 암호문을 받아서 partial decrypt만 수행"""
    try:
        if state.cc is None or state.keypair is None:
            raise ValueError("Keys not initialized")
        
        ciphertext_b64 = request["ciphertext"]
        ciphertext = deserialize_ciphertext(state.cc, ciphertext_b64)
        
        # Partial decrypt
        partial = partial_decrypt_main(state.cc, ciphertext, state.keypair.secretKey)
        partial_b64 = serialize_ciphertext(state.cc, partial)
        
        return {"partial_result": partial_b64}
        
    except Exception as e:
        logger.error(f"❌ Parallel investigation error: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/store_investigation_result")
async def store_investigation_result(request: dict):
    """서버로부터 조사 결과를 받아서 저장"""
    if state.role != "police":
        raise HTTPException(status_code=403, detail="Only police can receive investigation results")
    
    state.last_investigation_result = {
        "target": request["target"],
        "is_mafia": request["is_mafia"]
    }
    
    # Log the result
    target = request["target"]
    is_mafia = request["is_mafia"]
    logger.info("=" * 60)
    logger.info("🔍 POLICE INVESTIGATION RESULT")
    logger.info(f"   Player {target} is: {'🎭 MAFIA' if is_mafia else '✅ NOT MAFIA'}")
    logger.info("=" * 60)
    
    return {"success": True}


@app.get("/investigation_result")
async def get_investigation_result():
    """경찰이 자신의 조사 결과를 조회 (tool에서 사용)"""
    if state.role != "police":
        raise HTTPException(status_code=403, detail="Only police can check investigation results")
    
    if state.last_investigation_result is None:
        return {"has_result": False}
    
    return {
        "has_result": True,
        "result": state.last_investigation_result
    }


@app.post("/relay_decrypt")
async def relay_decrypt(request: dict):
    """
    Relay decryption: accumulate partial decryptions and pass to next player.
    Last player performs fusion decrypt with all partials.
    """
    try:
        if state.cc is None or state.keypair is None:
            raise ValueError("Keys not initialized. Complete DKG first.")

        ciphertext_b64 = request["ciphertext"]
        partial_results_b64 = request.get("partial_results", [])  # Accumulated partials
        remaining_order = request["remaining_order"]
        player_addresses = request["player_addresses"]
        
        logger.info(f"🔄 Relay decrypt - remaining_order: {remaining_order}, player_addresses: {player_addresses}")
        
        # Deserialize original ciphertext and perform partial decryption
        ciphertext = deserialize_ciphertext(state.cc, ciphertext_b64)
        partial = partial_decrypt_main(state.cc, ciphertext, state.keypair.secretKey)
        
        # Add my partial to the list
        partial_b64 = serialize_ciphertext(state.cc, partial)
        partial_results_b64.append(partial_b64)
        
        logger.info(f"🔄 Relay decrypt: {len(partial_results_b64)} partials collected")
        
        if len(remaining_order) == 0:
            # Last player: return all partials to requester
            logger.info(f"🔄 Last player, returning {len(partial_results_b64)} partials to requester")
            return {"partial_results": partial_results_b64}
        
        # Pass to next player with accumulated partials
        next_index = remaining_order[0]
        next_address = player_addresses[next_index]
        new_remaining = remaining_order[1:]
        
        logger.info(f"🔄 Forwarding to next player at {next_address}, remaining: {new_remaining}")
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
            result = response.json()
            
            # If we're the requester and got partials back, do fusion decrypt
            if "partial_results" in result:
                from service.crypto.threshold_decryption import fusion_decrypt
                from service.crypto.roles import NUM_ROLE_TYPES
                
                logger.info(f"🔄 Received {len(result['partial_results'])} partials, performing fusion decrypt")
                all_partials = [deserialize_ciphertext(state.cc, p) for p in result["partial_results"]]
                final_result = fusion_decrypt(state.cc, all_partials)
                decrypted_vector = final_result.GetPackedValue()
                logger.info(f"✅ Fusion decrypt complete: {decrypted_vector[:10]}...")
                
                # If this agent is police, show investigation result
                if state.role == "police":
                    is_mafia = sum(decrypted_vector[:NUM_ROLE_TYPES]) == 1
                    logger.info("=" * 60)
                    logger.info("🔍 POLICE INVESTIGATION RESULT")
                    logger.info(f"   Target is: {'🎭 MAFIA' if is_mafia else '✅ NOT MAFIA'}")
                    logger.info("=" * 60)
                
                return {"decrypted_vector": decrypted_vector}
            
            return result
            
    except Exception as e:
        logger.error(f"❌ Relay decrypt error: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/role_assignment")
async def role_assignment(request: RoleAssignmentRequest):
    """
    Receive role assignment after threshold decryption.
    """
    try:
        state.role = request.role.lower()
        state.joint_public_key = deserialize_public_key(state.cc, request.joint_public_key)

        logger.info("━" * 60)
        logger.info(f"🎭 ROLE ASSIGNED | Player #{state.player_index}")
        logger.info(f"   Role: {state.role.upper()}")
        logger.info("━" * 60)

        return {"success": True, "message": f"Role {state.role} assigned"}
    except Exception as e:
        logger.error(f"❌ Role assignment error: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/blind_role_assignment")
async def blind_role_assignment(request: dict):
    """
    BLIND role assignment: Agent decrypts only their own role.
    
    Protocol:
    1. Receive encrypted_roles[my_index] - my encrypted role
    2. Request partial decryptions from ALL other players
    3. Add my own partial decryption last
    4. Fusion decrypt to get my role
    
    Result: I only know MY role, no one else's
    """
    try:
        my_index = request["my_index"]
        encrypted_roles = request["encrypted_roles"]
        state.joint_public_key = deserialize_public_key(state.cc, request["joint_public_key"])
        
        # Store all encrypted roles for future use (e.g., police investigation)
        state.all_encrypted_roles = encrypted_roles
        
        logger.info(f"🔐 Starting blind role decryption for player {my_index}")
        
        # My encrypted role
        my_role_enc = deserialize_ciphertext(state.cc, encrypted_roles[my_index])
        
        # Collect partial decryptions from ALL other players
        # (In a real implementation, this would involve network requests)
        # For now, we simulate that the server coordinates this
        # The key point: THIS agent only gets the final decrypted role
        
        # For now, we'll use a simplified approach where the server
        # already collected partials and we just do our own
        # TODO: Implement full distributed protocol
        
        # Temporary: Store encrypted role and wait for server to send final role
        state.my_encrypted_role = encrypted_roles[my_index]
        
        logger.info(f"✓ Blind role assignment initiated for player {my_index}")
        return {"success": True, "message": "Waiting for threshold decryption"}
        
    except Exception as e:
        logger.error(f"❌ Blind role assignment error: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/complete_role_decryption")
async def complete_role_decryption(request: dict):
    """
    Complete role decryption with collected partial decryptions.
    Server sends all partial decryptions except mine.
    """
    try:
        partial_ciphertexts_b64 = request["partial_ciphertexts"]
        
        # Deserialize partials
        partial_results = [
            deserialize_ciphertext(state.cc, pt_b64) 
            for pt_b64 in partial_ciphertexts_b64
        ]
        
        # Add my partial decryption LAST
        my_role_enc = deserialize_ciphertext(state.cc, state.my_encrypted_role)
        my_partial = partial_decrypt_main(state.cc, my_role_enc, state.keypair.secretKey)
        partial_results.append(my_partial)
        
        # Fusion decrypt
        from service.crypto.threshold_decryption import fusion_decrypt
        from service.crypto.roles import ROLE_ENCODING, one_hot_to_role, NUM_ROLE_TYPES
        final_plaintext = fusion_decrypt(state.cc, partial_results)
        decrypted_vector = final_plaintext.GetPackedValue()[:NUM_ROLE_TYPES]
        my_role = one_hot_to_role(decrypted_vector)
        
        state.role = my_role.lower()
        
        # Store encrypted role for police investigation
        state.encrypted_role_vector = state.my_encrypted_role
        
        # Initialize suspicion notes manager
        from suspicion import SuspicionNoteManager, PoliceNoteManager
        if state.role == "police":
            state.suspicion_notes = PoliceNoteManager(state.num_players, state.player_index)
        else:
            state.suspicion_notes = SuspicionNoteManager(state.num_players, state.player_index)
        
        # Initialize AI agent now that we have the role
        session_id = f"game_{state.game_id}_agent_{state.agent_id}_player_{state.player_index}"
        db_path = "db/conversations.db"
        state.session = SQLiteSession(session_id, db_path)
        await state.session.clear_session()
        state.last_read_msg_id = -1
        state.agent = create_mafia_agent(state, state.role, state.player_index, state.num_players)
        
        logger.info("━" * 60)
        logger.info(f"🎭 ROLE DECRYPTED BLINDLY | Player #{state.player_index}")
        logger.info(f"   Role: {state.role.upper()}")
        logger.info(f"   ✓ No one else knows my role!")
        logger.info(f"   🔐 Encrypted role vector stored for investigation")
        logger.info(f"   🤖 AI Agent initialized")
        logger.info("━" * 60)
        
        return {"success": True, "role": state.role}
        
    except Exception as e:
        logger.error(f"❌ Role decryption completion error: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


# ============================================================================
# Game API Endpoints
# ============================================================================

@app.post("/init")
async def initialize_agent(request: InitRequest):
    """Initialize agent with game parameters (before role assignment)."""
    try:
        state.game_id = request.game_id
        state.cc = deserialize_crypto_context(request.crypto_context)
        state.joint_public_key = deserialize_public_key(state.cc, request.joint_public_key)
        state.player_index = request.player_index
        state.num_players = request.num_players
        state.alive = True
        # Role will be assigned later via blind threshold decryption

        logger.info("━" * 60)
        logger.info(f"🎮 AGENT INITIALIZED | Player #{state.player_index}")
        logger.info(f"   Game ID: {state.game_id}")
        logger.info(f"   Players: {state.num_players}")
        logger.info(f"   Waiting for blind role assignment...")
        logger.info("━" * 60)

        # SQLiteSession으로 게임별, 에이전트별 대화 히스토리 관리
        session_id = f"game_{state.game_id}_agent_{state.agent_id}_player_{state.player_index}"
        db_path = "db/conversations.db"
        state.session = SQLiteSession(session_id, db_path)
        await state.session.clear_session()
        state.last_read_msg_id = -1
        state.agent = create_mafia_agent(state, state.role, state.player_index, state.num_players)

        logger.info("━" * 60)
        logger.info(f"🎮 INITIALIZED | Player #{state.player_index} | Role: {state.role.upper()}")
        logger.info("━" * 60)

        return {"success": True, "message": f"Agent initialized as {state.role}"}
    except Exception as e:
        logger.error(f"❌ Init error: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/request_action", response_model=ActionResponse)
async def request_action(request: GameUpdateRequest):
    """Host requests an action from this agent."""
    try:
        logger.info("-"*50)
        state.action_submitted = False
        state.pending_action_target = None
        state.pending_chat_messages = []
        state.current_phase = request.phase

        # Log phase start with RANDOMIZED survivor order to prevent bias
        import random
        shuffled_survivors = list(request.survivors)
        random.shuffle(shuffled_survivors)
        survivors_str = ", ".join(str(s) for s in shuffled_survivors)
        dead_str = ", ".join(str(d) for d in request.dead_players)
        logger.info("")
        logger.info("━" * 60)
        logger.info(f"📍 {request.phase.upper()} PHASE | Turn {state.current_turn}")
        logger.info(f"👥 Alive (randomized order): {survivors_str}")
        logger.info(f"💀 Dead: {dead_str}")
        logger.info(f"💬 Message: {request.message}")
        logger.info("━" * 60)

        # Update dead players in suspicion notes
        if state.suspicion_notes:
            for i in range(state.num_players):
                if i not in request.survivors and i != state.player_index:
                    state.suspicion_notes.mark_player_dead(i)

        if not state.alive:
            logger.info("💀 Agent is dead. Sending dummy action.")
            encrypted_vector = create_zero_vector(state.num_players, state.cc, state.joint_public_key)
            ct_b64 = serialize_ciphertext(state.cc, encrypted_vector)
            return ActionResponse(encrypted_action=ct_b64, phase=request.phase)

        # CITIZEN OPTIMIZATION: Skip AI call during night phase
        if request.phase == "night" and state.role == "citizen":
            import random
            
            # Random delay (2-5 seconds) to avoid timing analysis
            delay = random.uniform(2.0, 5.0)
            logger.info(f"😴 Citizen has no night action - waiting {delay:.1f}s for timing...")
            await asyncio.sleep(delay)
            logger.info("✓ Citizen dummy vectors ready")
            
            # Skip to vector generation (handled at the end)
            state.pending_action_target = None
            state.action_submitted = True
            
        elif request.phase in ["night", "vote"]:
            if request.phase == "night":
                state.current_turn += 1

            # Update agent tools for current phase
            from agent_logic import create_agent_tools
            state.agent.tools = create_agent_tools(state, phase=request.phase)

            prompt = create_action_prompt(
                phase=request.phase,
                turn=state.current_turn,
                survivors_str=survivors_str,
                dead_str=dead_str,
                role=state.role,
                message=request.message
            )

            logger.debug(f"AI Prompt:\n{prompt}")

            logger.info("🤖 Calling AI agent...")
            result = await Runner.run(
                starting_agent=state.agent,
                input=prompt,
                session=state.session,
                max_turns=20
            )

            # Log AI interaction
            logger.info("")
            logger.info("┌─ AI Decision ─────────────────────────────────────────────┐")

            for item in result.new_items:
                if isinstance(item, ToolCallItem):
                    func_name = getattr(item.raw_item, 'name', 'unknown')
                    func_args = getattr(item.raw_item, 'arguments', '{}')
                    try:
                        args_dict = json.loads(func_args)
                        logger.info(f"│ 🔧 Function: {func_name}")
                        logger.info(f"│    Args: {args_dict}")
                    except:
                        logger.info(f"│ 🔧 Function: {func_name}({func_args})")

                elif isinstance(item, ToolCallOutputItem):
                    logger.info(f"│ ✅ Result: {item.output}")

                elif isinstance(item, MessageOutputItem):
                    message_text = ItemHelpers.text_message_output(item)
                    if message_text.strip():
                        logger.info(f"│ 💭 Thought: {message_text[:100]}...")

            logger.info("└───────────────────────────────────────────────────────────┘")
            logger.debug(f"Full AI output: {result.final_output}")

            # If AI didn't submit action, give one more chance with urgent reminder
            if not state.action_submitted:
                logger.warning("⚠️  AI did not submit an action, sending urgent reminder...")
                
                action_tool = "submit_night_action" if request.phase == "night" else "submit_vote"
                reminder_prompt = f"""🚨 URGENT: You MUST submit your action NOW!

You have analyzed the situation but haven't acted yet.
ALIVE players: [{survivors_str}]

⚡ IMMEDIATELY call {action_tool}(target_index) right now!
- Choose ANY alive player index from the list above
- If unsure, pick a random number from alive players
- This is REQUIRED to continue the game!

Do it NOW - no more analysis needed!"""
                
                try:
                    retry_result = await Runner.run(
                        starting_agent=state.agent,
                        input=reminder_prompt,
                        session=state.session,
                        max_turns=3
                    )
                    
                    if not state.action_submitted:
                        logger.error("❌ AI still did not submit action after reminder, forcing abstain")
                        state.pending_action_target = None
                    else:
                        logger.info("✅ AI submitted action after reminder")
                except Exception as e:
                    logger.error(f"Retry failed: {e}")
                    state.pending_action_target = None
                    
        elif request.phase in ["chat", "day"]:
            # Chat/Day phase - continuous interaction until time runs out
            from agent_logic import create_agent_tools, create_chat_prompt
            import time as time_module
            
            state.agent.tools = create_agent_tools(state, phase="chat")
            
            remaining_time = request.remaining_time if request.remaining_time else 120
            start_time = time_module.time()
            chat_round = 0
            
            # Keep chatting until time runs out
            while True:
                chat_round += 1
                elapsed = time_module.time() - start_time
                time_left = max(0, remaining_time - elapsed)
                
                # Stop if less than 5 seconds left
                if time_left < 5:
                    logger.info(f"⏱️  Chat time ended - {elapsed:.1f}s elapsed")
                    break
                
                prompt = create_chat_prompt(
                    turn=state.current_turn,
                    survivors_str=survivors_str,
                    dead_str=dead_str,
                    role=state.role,
                    message=request.message,
                    remaining_time=int(time_left)
                )
                
                logger.info(f"💬 Chat round {chat_round} - {time_left:.0f}s remaining")
                
                try:
                    # Shorter max_turns per round so we can loop
                    result = await Runner.run(
                        starting_agent=state.agent,
                        input=prompt,
                        session=state.session,
                        max_turns=10  # Shorter rounds, but multiple iterations
                    )
                    
                    msgs_sent = len(state.pending_chat_messages)
                    logger.info(f"💬 Round {chat_round} complete - {msgs_sent} total messages sent")
                    
                    # Small delay between rounds to avoid spam
                    await asyncio.sleep(2)
                    
                except Exception as e:
                    logger.error(f"Chat round {chat_round} error: {e}")
                    await asyncio.sleep(2)
            
            logger.info(f"💬 Chat phase ended - {chat_round} rounds, {len(state.pending_chat_messages)} messages sent")
            
        else:
            logger.info("ℹ️  No action required for this phase.")
            state.pending_action_target = None

        # BLIND PROTOCOL: Create ALL three action vectors
        # Only the one matching our role contains real data, others are random dummies
        logger.info("🎭 BLIND PROTOCOL: Generating 3 encrypted vectors (attack/heal/investigate)")
        
        attack_vec = None
        heal_vec = None
        investigate_vec = None
        
        if state.pending_action_target is not None and request.phase == "night":
            real_vector = create_one_hot_vector(
                state.num_players,
                state.pending_action_target,
                state.cc,
                state.joint_public_key
            )
            
            # Assign real vector to matching role, dummies to others
            if state.role == "mafia":
                attack_vec = real_vector
                heal_vec = create_zero_vector(state.num_players, state.cc, state.joint_public_key)
                investigate_vec = create_zero_vector(state.num_players, state.cc, state.joint_public_key)
                logger.info(f"🔪 Attack: REAL → Player {state.pending_action_target} | Heal: DUMMY | Investigate: DUMMY")
            elif state.role == "doctor":
                attack_vec = create_zero_vector(state.num_players, state.cc, state.joint_public_key)
                heal_vec = real_vector
                investigate_vec = create_zero_vector(state.num_players, state.cc, state.joint_public_key)
                logger.info(f"💊 Attack: DUMMY | Heal: REAL → Player {state.pending_action_target} | Investigate: DUMMY")
            elif state.role == "police":
                attack_vec = create_zero_vector(state.num_players, state.cc, state.joint_public_key)
                heal_vec = create_zero_vector(state.num_players, state.cc, state.joint_public_key)
                
                # Police: Compute investigation result
                # Get target's encrypted role vector
                target_role_enc_b64 = state.all_encrypted_roles[state.pending_action_target]
                target_role_enc = deserialize_ciphertext(state.cc, target_role_enc_b64)
                
                # Mafia check vector: [citizen=0, mafia=1, doctor=0, police=0]
                from service.crypto.roles import NUM_ROLE_TYPES
                from service.crypto.vector_operations import homomorphic_dot_product
                mafia_check_vector = [0, 1, 0, 0]
                
                # Compute dot product: role_vector · mafia_check
                # Result will be 1 if mafia, 0 otherwise
                investigate_vec = homomorphic_dot_product(
                    state.cc,
                    target_role_enc,
                    mafia_check_vector
                )
                
                logger.info(f"🔍 Attack: DUMMY | Heal: DUMMY | Investigate: COMPUTED (Player {state.pending_action_target} role check)")
            else:  # citizen
                attack_vec = create_zero_vector(state.num_players, state.cc, state.joint_public_key)
                heal_vec = create_zero_vector(state.num_players, state.cc, state.joint_public_key)
                investigate_vec = create_zero_vector(state.num_players, state.cc, state.joint_public_key)
                logger.info("👤 Citizen: All DUMMY vectors")
        else:
            # No action or not night phase - all dummies
            attack_vec = create_zero_vector(state.num_players, state.cc, state.joint_public_key)
            heal_vec = create_zero_vector(state.num_players, state.cc, state.joint_public_key)
            investigate_vec = create_zero_vector(state.num_players, state.cc, state.joint_public_key)
            logger.info("⏸️  No action: All DUMMY vectors")

        attack_b64 = serialize_ciphertext(state.cc, attack_vec)
        heal_b64 = serialize_ciphertext(state.cc, heal_vec)
        investigate_b64 = serialize_ciphertext(state.cc, investigate_vec)
        
        # Network obfuscation: 경찰이 아닌 경우도 dummy investigation packets 전송
        if request.phase == "night" and state.role != "police":
            asyncio.create_task(send_dummy_investigation_packets())

        return ActionResponse(
            attack_vector=attack_b64,
            heal_vector=heal_b64,
            investigate_vector=investigate_b64,
            phase=request.phase,
            chat_messages=[]
        )
    except Exception as e:
        logger.error(f"Error in /request_action: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/investigation_result")
async def get_investigation_result():
    """경찰이 자신의 조사 결과를 조회 (tool에서 사용)"""
    if state.role != "police":
        raise HTTPException(status_code=403, detail="Only police can check investigation results")
    
    if state.last_investigation_result is None:
        return {"has_result": False}
    
    return {
        "has_result": True,
        "result": state.last_investigation_result
    }


@app.get("/health")
async def health_check():
    return {"status": "healthy"}


@app.get("/chat/messages")
async def get_chat_messages():
    """Get pending chat messages from this agent"""
    messages = state.pending_chat_messages.copy()
    state.pending_chat_messages.clear()
    return {"messages": messages}


@app.post("/chat")
async def receive_chat_message(request: dict):
    """Receive chat message from host"""
    # Store received messages for agent's context
    sender_index = request.get("sender_index")
    message = request.get("message")
    msg_id = request.get("message_id")
    
    # Add to chat history so agent can read it
    state.chat_history.add_message(
        player_index=sender_index,
        phase="chat",  # Chat messages happen during day/chat phase
        message=message,
        turn=state.current_turn
    )
    
    # Agent can use this to update their understanding of the game
    logger.info(f"[Agent] Received chat from player {sender_index}: {message}")
    logger.info(f"[Agent] Chat history now has {len(state.chat_history.messages)} messages")
    
    return {"status": "ok"}


@app.post("/get_encrypted_role_vector")
async def get_encrypted_role_vector(request: dict):
    """Return encrypted role vector for police investigation"""
    try:
        if state.encrypted_role_vector is None:
            raise ValueError("Encrypted role vector not available")
        
        logger.info(f"🔍 Providing encrypted role vector for investigation")
        
        return {
            "encrypted_role_vector": state.encrypted_role_vector,
            "success": True
        }
    except Exception as e:
        logger.error(f"❌ Get encrypted role vector error: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


# ============================================================================
# Main Entry Point
# ============================================================================

def setup_logging(port: int):
    """Sets up file-based logging for the agent."""
    logs_dir = "logs"
    if not os.path.exists(logs_dir):
        os.makedirs(logs_dir)

    agent_log_path = os.path.join(logs_dir, f"agent_{port}.log")
    debug_log_path = os.path.join(logs_dir, f"debug_{port}.log")

    agent_handler = logging.FileHandler(agent_log_path, mode='a')
    agent_handler.setLevel(logging.INFO)
    agent_handler.setFormatter(logging.Formatter(
        '%(asctime)s | %(message)s',
        datefmt='%H:%M:%S'
    ))

    debug_handler = logging.FileHandler(debug_log_path, mode='a')
    debug_handler.setLevel(logging.DEBUG)
    debug_handler.setFormatter(logging.Formatter(
        '%(asctime)s [%(levelname)s] %(name)s: %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S'
    ))

    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(logging.INFO)
    console_handler.setFormatter(logging.Formatter(
        '%(asctime)s | %(message)s',
        datefmt='%H:%M:%S'
    ))

    root_logger = logging.getLogger()
    root_logger.handlers.clear()
    root_logger.setLevel(logging.DEBUG)
    root_logger.addHandler(agent_handler)
    root_logger.addHandler(debug_handler)
    root_logger.addHandler(console_handler)

    for logger_name in ['uvicorn', 'uvicorn.access', 'uvicorn.error']:
        uvicorn_logger = logging.getLogger(logger_name)
        uvicorn_logger.handlers.clear()
        uvicorn_logger.propagate = False
        uvicorn_logger.addHandler(debug_handler)
        uvicorn_logger.setLevel(logging.INFO)

    for logger_name in ['openai', 'openai.agents', 'httpx', 'httpcore']:
        sdk_logger = logging.getLogger(logger_name)
        sdk_logger.handlers.clear()
        sdk_logger.propagate = False
        sdk_logger.addHandler(debug_handler)
        sdk_logger.setLevel(logging.DEBUG)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Mafia AI Agent Player")
    parser.add_argument("--port", type=int, required=True, help="Port to run on")
    parser.add_argument("--api-key", type=str, required=True, help="OpenAI API key")
    parser.add_argument("--game-id", type=str, required=True, help="Game session ID (short UUID)")
    parser.add_argument("--agent-id", type=int, required=True, help="Agent ID")

    args = parser.parse_args()

    setup_logging(args.port)

    os.environ["OPENAI_API_KEY"] = args.api_key
    state.game_id = args.game_id
    state.agent_id = args.agent_id

    logger.info("=" * 60)
    logger.info(f"🚀 Mafia AI Agent #{args.agent_id} | Port {args.port}")
    logger.info("=" * 60)

    uvicorn.run(
        app,
        host="0.0.0.0",
        port=args.port,
        log_config=None,
        access_log=True
    )
