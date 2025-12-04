"""
AI Agent Player - Autonomous Mafia Game Participant
Uses OpenAI Agents SDK for stateful autonomous behavior with session-based memory
Supports DKG (Distributed Key Generation) for threshold FHE
"""
import argparse
import json
import os
import sys
import logging
from typing import Optional, List
from fastapi import FastAPI, HTTPException
import uvicorn

from agents import Agent, Runner, ToolCallItem, ToolCallOutputItem, MessageOutputItem, ItemHelpers, SQLiteSession

from chat import GameChatHistory, ChatMessage
from suspicion import SuspicionNoteManager, PoliceNoteManager
from agent_logic import create_mafia_agent, create_action_prompt

from models import (
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
from security import (
    create_openfhe_context,
    deserialize_crypto_context,
    serialize_public_key,
    deserialize_public_key,
    serialize_ciphertext,
    deserialize_ciphertext,
    dkg_keygen_lead,
    dkg_keygen_join,
    partial_decrypt_lead,
    partial_decrypt_main,
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

state = AgentState()
app = FastAPI(title="Mafia AI Agent")


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

        return DKGRoundResponse(
            public_key=pk_b64,
            success=True
        )
    except Exception as e:
        logger.error(f"❌ DKG round error: {e}", exc_info=True)
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


# ============================================================================
# Game API Endpoints
# ============================================================================

@app.post("/init")
async def initialize_agent(request: InitRequest):
    """Initialize agent with game parameters and role (after DKG)."""
    try:
        state.game_id = request.game_id
        state.cc = deserialize_crypto_context(request.crypto_context)
        state.joint_public_key = deserialize_public_key(state.cc, request.joint_public_key)
        state.role = request.role.lower()
        state.player_index = request.player_index
        state.num_players = request.num_players
        state.alive = True

        # Initialize suspicion notes manager (Police gets special version)
        if state.role == "police":
            state.suspicion_notes = PoliceNoteManager(state.num_players, state.player_index)
        else:
            state.suspicion_notes = SuspicionNoteManager(state.num_players, state.player_index)

        # SQLiteSession으로 게임별, 에이전트별 대화 히스토리 관리
        session_id = f"game_{state.game_id}_agent_{state.agent_id}_player_{state.player_index}"
        db_path = "conversations.db"
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

        # Log phase start
        survivors_str = ", ".join(str(s) for s in request.survivors)
        logger.info("")
        logger.info("━" * 60)
        logger.info(f"📍 {request.phase.upper()} PHASE | Turn {state.current_turn}")
        logger.info(f"👥 Alive: {survivors_str}")
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

        if request.phase in ["night", "vote"]:
            if request.phase == "night":
                state.current_turn += 1

            prompt = create_action_prompt(
                phase=request.phase,
                turn=state.current_turn,
                survivors_str=survivors_str,
                role=state.role,
                message=request.message
            )

            logger.debug(f"AI Prompt:\n{prompt}")

            logger.info("🤖 Calling AI agent...")
            result = await Runner.run(
                starting_agent=state.agent,
                input=prompt,
                session=state.session,
                max_turns=5
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

            if not state.action_submitted:
                logger.warning("⚠️  AI did not submit an action, defaulting to abstain.")
                state.pending_action_target = None
        else:
            logger.info("ℹ️  No action required for this phase.")
            state.pending_action_target = None

        # Encrypt final action with joint public key
        if state.pending_action_target is not None:
            encrypted_vector = create_one_hot_vector(
                state.num_players,
                state.pending_action_target,
                state.cc,
                state.joint_public_key
            )
            logger.info(f"🔒 Encrypted action → Target Player {state.pending_action_target}")
        else:
            encrypted_vector = create_zero_vector(state.num_players, state.cc, state.joint_public_key)
            logger.info("🔒 Encrypted dummy action (abstain/no-op)")

        ct_b64 = serialize_ciphertext(state.cc, encrypted_vector)

        return ActionResponse(
            encrypted_action=ct_b64,
            phase=request.phase,
            chat_messages=[]
        )
    except Exception as e:
        logger.error(f"Error in /request_action: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/health")
async def health_check():
    return {"status": "healthy"}


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
