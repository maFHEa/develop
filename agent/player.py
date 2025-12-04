"""
AI Agent Player - Autonomous Mafia Game Participant
Uses OpenAI Agents SDK for stateful autonomous behavior with session-based memory
"""
import argparse
import json
import os
import sys
import logging
from typing import Optional, List
from fastapi import FastAPI, HTTPException
import uvicorn
import tenseal as ts

from agents import Agent, Runner, ToolCallItem, ToolCallOutputItem, MessageOutputItem, ItemHelpers, SQLiteSession

from chat import GameChatHistory, ChatMessage
from suspicion import SuspicionNoteManager, PoliceNoteManager
from agent_logic import create_mafia_agent, create_action_prompt

from models import (
    InitRequest,
    GameUpdateRequest,
    ActionResponse,
    ChatBroadcast
)
from security import (
    deserialize_context,
    create_one_hot_vector,
    create_zero_vector,
    serialize_encrypted_vector
)

# ============================================================================
# Global State & Setup
# ============================================================================

logger = logging.getLogger(__name__)

class AgentState:
    def __init__(self):
        self.game_id: Optional[str] = None  # Short UUID for game session
        self.agent_id: Optional[int] = None
        self.context: Optional[ts.Context] = None
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
# API Endpoints
# ============================================================================

@app.post("/init")
async def initialize_agent(request: InitRequest):
    """Initialize agent with game parameters and role."""
    try:
        state.game_id = request.game_id
        state.context = deserialize_context(request.public_context)
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
        # game_id와 agent_id로 구분 - 하나의 DB에 모든 게임/에이전트 데이터 저장
        session_id = f"game_{state.game_id}_agent_{state.agent_id}_player_{state.player_index}"
        db_path = "conversations.db"  # 하나의 DB 파일 사용
        state.session = SQLiteSession(session_id, db_path)
        await state.session.clear_session()  # 새 게임 시작 시 이전 대화 초기화
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
            encrypted_vector = create_zero_vector(state.num_players, state.context)
            return ActionResponse(encrypted_action=serialize_encrypted_vector(encrypted_vector), phase=request.phase)

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
                session=state.session,  # 자동으로 이전 대화 불러오고 저장
                max_turns=5 
            )

            # Log AI interaction - 깔끔하게 정리
            logger.info("")
            logger.info("┌─ AI Decision ─────────────────────────────────────────────┐")
            
            for item in result.new_items:
                if isinstance(item, ToolCallItem):
                    # Function call by AI
                    func_name = getattr(item.raw_item, 'name', 'unknown')
                    func_args = getattr(item.raw_item, 'arguments', '{}')
                    try:
                        args_dict = json.loads(func_args)
                        logger.info(f"│ 🔧 Function: {func_name}")
                        logger.info(f"│    Args: {args_dict}")
                    except:
                        logger.info(f"│ 🔧 Function: {func_name}({func_args})")
                    
                elif isinstance(item, ToolCallOutputItem):
                    # Function execution result
                    logger.info(f"│ ✅ Result: {item.output}")
                    
                elif isinstance(item, MessageOutputItem):
                    # AI's message/thought
                    message_text = ItemHelpers.text_message_output(item)
                    if message_text.strip():
                        logger.info(f"│ 💭 Thought: {message_text[:100]}...")
            
            logger.info("└───────────────────────────────────────────────────────────┘")
            logger.debug(f"Full AI output: {result.final_output}")
            # Session이 자동으로 대화 저장하므로 add_turn 불필요

            if not state.action_submitted:
                logger.warning("⚠️  AI did not submit an action, defaulting to abstain.")
                state.pending_action_target = None
        else:
            logger.info("ℹ️  No action required for this phase.")
            state.pending_action_target = None
        
        # Encrypt final action
        if state.pending_action_target is not None:
            encrypted_vector = create_one_hot_vector(state.num_players, state.pending_action_target, state.context)
            logger.info(f"🔒 Encrypted action → Target Player {state.pending_action_target}")
        else:
            encrypted_vector = create_zero_vector(state.num_players, state.context)
            logger.info("🔒 Encrypted dummy action (abstain/no-op)")
        
        return ActionResponse(
            encrypted_action=serialize_encrypted_vector(encrypted_vector),
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
    
    # 2개의 로그 파일: agent.log (게임 진행), debug.log (상세 디버깅)
    agent_log_path = os.path.join(logs_dir, f"agent_{port}.log")
    debug_log_path = os.path.join(logs_dir, f"debug_{port}.log")
    
    # Agent log handler - 게임 진행 상황만 (INFO 이상)
    agent_handler = logging.FileHandler(agent_log_path, mode='a')
    agent_handler.setLevel(logging.INFO)
    agent_handler.setFormatter(logging.Formatter(
        '%(asctime)s | %(message)s',
        datefmt='%H:%M:%S'
    ))
    
    # Debug log handler - 모든 디버그 정보 (DEBUG 이상)
    debug_handler = logging.FileHandler(debug_log_path, mode='a')
    debug_handler.setLevel(logging.DEBUG)
    debug_handler.setFormatter(logging.Formatter(
        '%(asctime)s [%(levelname)s] %(name)s: %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S'
    ))
    
    # Console handler - 중요한 정보만
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(logging.INFO)
    console_handler.setFormatter(logging.Formatter(
        '%(asctime)s | %(message)s',
        datefmt='%H:%M:%S'
    ))
    
    # Configure root logger
    root_logger = logging.getLogger()
    root_logger.handlers.clear()
    root_logger.setLevel(logging.DEBUG)
    root_logger.addHandler(agent_handler)
    root_logger.addHandler(debug_handler)
    root_logger.addHandler(console_handler)
    
    # Uvicorn/FastAPI 로그는 debug.log에만
    for logger_name in ['uvicorn', 'uvicorn.access', 'uvicorn.error']:
        uvicorn_logger = logging.getLogger(logger_name)
        uvicorn_logger.handlers.clear()
        uvicorn_logger.propagate = False  # root로 전파 안함
        uvicorn_logger.addHandler(debug_handler)
        uvicorn_logger.setLevel(logging.INFO)
    
    # OpenAI/HTTP 디버그는 debug.log에만
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

    # Setup logging BEFORE anything else
    setup_logging(args.port)

    # Set OpenAI API key and game ID
    os.environ["OPENAI_API_KEY"] = args.api_key
    state.game_id = args.game_id
    state.agent_id = args.agent_id
    
    logger.info("=" * 60)
    logger.info(f"🚀 Mafia AI Agent #{args.agent_id} | Port {args.port}")
    logger.info("=" * 60)
    
    # Run uvicorn with log_config to integrate with our logging
    uvicorn.run(
        app, 
        host="0.0.0.0", 
        port=args.port,
        log_config=None,  # Disable default logging
        access_log=True
    )
