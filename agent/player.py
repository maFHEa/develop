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
from investigation import InvestigationResult

from models import (
    InitRequest,
    GameUpdateRequest,
    ActionResponse,
    ChatBroadcast,
    ChatPhaseRequest,
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

# Configure logging with INFO level
logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

# Add file handler if not already present
if not logger.handlers:
    # Create logs directory if it doesn't exist
    os.makedirs('logs', exist_ok=True)
    file_handler = logging.FileHandler('logs/agent_{port}.log')
    file_handler.setLevel(logging.INFO)
    formatter = logging.Formatter('%(asctime)s [%(levelname)s] %(name)s: %(message)s')
    file_handler.setFormatter(formatter)
    logger.addHandler(file_handler)

    # Also log to console
    console_handler = logging.StreamHandler()
    console_handler.setLevel(logging.INFO)
    console_handler.setFormatter(formatter)
    logger.addHandler(console_handler)

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
        self.chat_phase_active: bool = False  # 대화 phase 활성 여부
        self.chat_phase_task: Optional[any] = None  # 비동기 태스크 참조
        self.host_address: str = "http://localhost:5000"  # Host address

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
# API Endpoints
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
        state.host_address = request.host_address
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

        logger.info(f"✅ Initialized: Player {state.player_index} | {state.role.upper()} | Game {state.game_id}")

        return {"success": True, "message": f"Agent initialized as {state.role}"}
    except Exception as e:
        logger.error(f"❌ Init error: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/request_action", response_model=ActionResponse)
async def request_action(request: GameUpdateRequest):
    """Host requests an action from this agent."""
    try:
        import random
        import asyncio

        logger.info("-"*50)
        state.action_submitted = False
        state.pending_action_target = None
        state.pending_chat_messages = []
        state.current_phase = request.phase

        survivors_str = ", ".join(str(s) for s in request.survivors)
        logger.info(f"🎮 Turn {state.current_turn} | {request.phase.upper()} | Alive: [{survivors_str}]")

        if state.suspicion_notes:
            for i in range(state.num_players):
                if i not in request.survivors and i != state.player_index:
                    state.suspicion_notes.mark_player_dead(i)

        if not state.alive:
            logger.info("💀 Agent is dead. Sending dummy action.")
            encrypted_vector = create_zero_vector(state.num_players, state.cc, state.joint_public_key)
            return ActionResponse(
                encrypted_action=serialize_ciphertext(state.cc, encrypted_vector),
                phase=request.phase
            )

        # Optimization: If it's night and the agent has no special role, just sleep.
        is_night_action_role = state.role in ["mafia", "doctor", "police"]
        if request.phase == "night" and not is_night_action_role:
            sleep_time = random.uniform(2, 5)
            logger.info(f"😴 Non-acting role. Sleeping for {sleep_time:.2f}s...")
            await asyncio.sleep(sleep_time)

            encrypted_vector = create_zero_vector(state.num_players, state.cc, state.joint_public_key)
            logger.info("➖ Action: Abstain (slept)")

            return ActionResponse(
                encrypted_action=serialize_ciphertext(state.cc, encrypted_vector),
                phase=request.phase,
                chat_messages=[] # No chat messages while sleeping
            )

        if request.phase in ["night", "vote"]:
            if request.phase == "night":
                state.current_turn += 1

            from agent_logic import create_agent_tools
            phase_tools = create_agent_tools(state, phase=request.phase)
            state.agent.tools = phase_tools

            prompt = create_action_prompt(
                phase=request.phase,
                turn=state.current_turn,
                survivors_str=survivors_str,
                role=state.role,
                message=request.message
            )

            result = await Runner.run(
                starting_agent=state.agent,
                input=prompt,
                session=state.session,
                max_turns=10  # Increased max_turns to prevent timeout
            )

            # Refined logging for tool calls
            tool_calls = [item for item in result.new_items if isinstance(item, ToolCallItem)]
            if tool_calls:
                for item in tool_calls:
                    func_name = getattr(item.raw_item, 'name', 'unknown')
                    func_args = getattr(item.raw_item, 'arguments', '{}')
                    try:
                        args_dict = json.loads(func_args)
                        if func_name == 'send_chat_message':
                            logger.info(f"🗣️  Agent says: \"{args_dict.get('message', '')}\" ")
                        elif func_name == 'write_suspicion_note':
                            logger.info(f"📝 Agent notes on P{args_dict.get('player_index')}: \"{args_dict.get('reasoning', '')}\" (Level: {args_dict.get('suspicion_level')})")
                        elif func_name in ['read_chat_messages', 'view_suspicion_notes']:
                            logger.info(f"🤔 Agent calls {func_name}")
                    except json.JSONDecodeError:
                        logger.info(f"⚙️  Agent called {func_name} with malformed args.")

            if not state.action_submitted:
                state.pending_action_target = None
        else:
            state.pending_action_target = None

        if state.pending_action_target is not None:
            encrypted_vector = create_one_hot_vector(
                state.num_players, state.pending_action_target,
                state.cc, state.joint_public_key
            )
            logger.info(f"✅ Action: Target={state.pending_action_target}")
        else:
            encrypted_vector = create_zero_vector(state.num_players, state.cc, state.joint_public_key)
            logger.info("➖ Action: Abstain")

        return ActionResponse(
            encrypted_action=serialize_ciphertext(state.cc, encrypted_vector),
            phase=request.phase,
            chat_messages=state.pending_chat_messages
        )
    except Exception as e:
        logger.error(f"Error in /request_action: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/health")
async def health_check():
    return {"status": "healthy"}

@app.post("/chat/broadcast")
async def receive_chat_message(broadcast: ChatBroadcast):
    """Receive a chat message from another player (via host)."""
    try:
        # Don't add own messages to history (they are added via session)
        if broadcast.player_index == state.player_index:
            return {"success": True}

        state.chat_history.add_message(
            player_index=broadcast.player_index,
            phase=broadcast.phase,
            message=broadcast.message,
            turn=broadcast.turn
        )
        logger.info(f"💬 P{broadcast.player_index}: {broadcast.message[:40]}...")
        return {"success": True}
    except Exception as e:
        logger.error(f"Error in /chat/broadcast: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/investigation/result")
async def receive_investigation_result(result: InvestigationResult):
    """Receive investigation result from host (Police only)."""
    try:
        if state.role != "police":
            logger.warning("Received investigation result but agent is not police")
            return {"success": False, "message": "Not a police agent"}

        if state.suspicion_notes is None:
            return {"success": False, "message": "Suspicion notes not initialized"}

        from suspicion import PoliceNoteManager
        if not isinstance(state.suspicion_notes, PoliceNoteManager):
            return {"success": False, "message": "Not a police note manager"}

        result_msg = state.suspicion_notes.add_investigation_result(
            target_index=result.target_index,
            is_mafia=result.is_mafia,
            current_turn=result.turn
        )

        logger.info(f"🔍 P{result.target_index}: {'MAFIA' if result.is_mafia else 'NOT MAFIA'}")
        return {"success": True}
    except Exception as e:
        logger.error(f"Error in /investigation/result: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/chat/phase")
async def manage_chat_phase(request: ChatPhaseRequest):
    """Start or stop chat phase where agent continuously interacts."""
    try:
        if request.action == "start":
            if state.chat_phase_active:
                return {"success": False, "message": "Chat phase already active"}

            state.chat_phase_active = True
            logger.info(f"💬 Chat phase started ({request.duration_seconds}s)")

            import asyncio
            state.chat_phase_task = asyncio.create_task(
                _chat_phase_session(request.turn)
            )

            return {"success": True, "message": "Chat phase started"}

        elif request.action == "stop":
            state.chat_phase_active = False
            if state.chat_phase_task:
                state.chat_phase_task.cancel()
                state.chat_phase_task = None
            logger.info("💬 Chat phase stopped")
            return {"success": True, "message": "Chat phase stopped"}

        else:
            return {"success": False, "message": f"Invalid action: {request.action}"}

    except Exception as e:
        logger.error(f"Error in /chat/phase: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/chat/messages")
async def get_pending_messages():
    """Get and clear pending chat messages from agent."""
    try:
        messages = state.pending_chat_messages.copy()
        state.pending_chat_messages.clear()
        return {"messages": messages, "player_index": state.player_index}
    except Exception as e:
        logger.error(f"Error in /chat/messages: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))

async def _chat_phase_session(turn: int):
    """Background chat session - agent autonomously participates until phase ends."""
    import asyncio
    import random

    try:
        from agent_logic import create_agent_tools
        chat_tools = create_agent_tools(state, phase="chat")
        state.agent.tools = chat_tools

        survivors_str = ", ".join(str(i) for i in range(state.num_players) if i != state.player_index)
        role = state.role

        # 역할 기반 페르소나 정의
        persona_map = {
            "mafia": "당신은 교활한 마피아입니다. 무고해 보이려 노력하면서 다른 사람들을 의심하게 만드세요.",
            "police": "당신은 분석적인 경찰입니다. 논리적 추론을 통해 마피아를 찾아내세요.",
            "doctor": "당신은 보호자 의사입니다. 시민들을 구하고 위협을 파악하세요.",
            "citizen": "당신은 경계심 많은 시민입니다. 의심스러운 행동을 찾아내세요."
        }
        persona = persona_map.get(role, "당신은 신중하게 상황을 분석하는 플레이어입니다.")

        role_strategy = "마피아 전략: 의심을 다른 곳으로 돌리고, 다른 사람에 대한 의구심을 만들고, 걱정하는 척 하세요" if role == "mafia" else "시민 전략: 관찰한 것을 공유하고, 날카로운 질문을 하고, 합의를 이끌어내세요"

        prompt = f"""{turn}턴 - 대화 토론 단계 - 자연스러운 대화 모드

당신의 역할과 페르소나:
{persona}

대화 가이드라인:

1. 순서 지키기:
   - 먼저 read_chat_messages()로 모든 메시지를 읽으세요
   - 메시지 사이에 2-5초 기다리세요 (다른 사람이 말할 시간을 주기)
   - 다른 사람 말에 응답하세요, 혼자 떠들지 마세요
   - 누가 당신에게 질문하면 직접 답변하세요

2. 자연스러운 대화 규칙:
   - 다른 사람 말을 인용하세요: "Player X 말에 동의해" 또는 "Player Y, 왜 그렇게 말했어?"
   - 다른 플레이어에게 구체적인 질문을 하세요
   - 이전 대화 내용을 이어가세요
   - 같은 말 반복하지 마세요 - 매번 새로운 정보를 추가하세요
   - 메시지는 간결하게 (1-2문장)

3. 대화 흐름:
   - 항상 read_chat_messages()로 시작하세요
   - 새 메시지가 있으면 -> 응답하세요
   - 새 메시지가 없으면 -> 다음 중 선택:
     * 잠깐 기다리기 (다른 사람이 타이핑 중일 수 있음)
     * 새로운 관찰이나 의심 공유하기
     * 누군가에게 직접 질문하기

4. 문맥 인식:
   - 최근 3-5개 메시지를 살펴보세요
   - 누가 논의되고 있는지 주목하세요
   - 갑자기 주제를 바꾸지 마세요
   - 대화 흐름을 따르세요

당신의 역할 전략:
{role_strategy}

중요: 외부에서 중단할 때까지 영원히 반복됩니다.
패턴: read_chat_messages() -> 2-5초 대기 -> send_chat_message() -> 반복

다른 플레이어들: {survivors_str}
자연스러운 대화를 시작하세요! 한국어로 대화하세요.
"""

        # Add initial random delay so agents don't all start at once
        initial_delay = random.uniform(1.0, 3.0)
        await asyncio.sleep(initial_delay)

        logger.info("💬 Starting autonomous chat session...")

        # Use very large max_turns for autonomous chat (SDK doesn't support None)
        result = await Runner.run(
            starting_agent=state.agent,
            input=prompt,
            session=state.session,
            max_turns=10000  # Extremely high limit - agent continues until cancelled
        )

        logger.info(f"💬 Chat session ended naturally")

    except asyncio.CancelledError:
        logger.info("💬 Chat session cancelled by host")
    except Exception as e:
        logger.error(f"Error in chat session: {e}", exc_info=True)

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
