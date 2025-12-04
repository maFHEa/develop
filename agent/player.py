"""
AI Agent Player - Autonomous Mafia Game Participant
Uses OpenAI Agents SDK for stateful autonomous behavior with session-based memory
"""
import argparse
import json
import os
import sys
import logging
from typing import Optional, List, Dict, Any, Annotated
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field
import uvicorn
import asyncio
import tenseal as ts

from agents import Agent, Runner, function_tool, ToolCallItem, ToolCallOutputItem, MessageOutputItem, ItemHelpers

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

class ChatMessage:
    """Single chat message with metadata"""
    def __init__(self, player_index: int, phase: str, message: str, turn: int, msg_id: int):
        self.player_index = player_index
        self.phase = phase
        self.message = message
        self.turn = turn
        self.msg_id = msg_id
        self.timestamp = asyncio.get_event_loop().time() if asyncio.get_event_loop().is_running() else 0
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "msg_id": self.msg_id,
            "player": self.player_index,
            "phase": self.phase,
            "message": self.message,
            "turn": self.turn,
            "timestamp": self.timestamp
        }


class GameChatHistory:
    """Stores P2P chat messages throughout the game session in memory"""
    def __init__(self):
        self.messages: List[ChatMessage] = []
        self.next_id: int = 0
    
    def add_message(self, player_index: int, phase: str, message: str, turn: int) -> int:
        msg = ChatMessage(player_index, phase, message, turn, self.next_id)
        self.messages.append(msg)
        self.next_id += 1
        return msg.msg_id
    
    def get_messages_from(self, from_id: int = 0, limit: Optional[int] = None) -> List[ChatMessage]:
        filtered = [m for m in self.messages if m.msg_id >= from_id]
        if limit:
            return filtered[:limit]
        return filtered

class SessionMemory:
    """In-memory conversation history for the agent during a game session"""
    def __init__(self):
        self.conversation: List[Dict[str, str]] = []
    
    def add_turn(self, user_input: str, assistant_output: str):
        self.conversation.append({"role": "user", "content": user_input})
        self.conversation.append({"role": "assistant", "content": assistant_output})
    
    def get_messages(self) -> List[Dict[str, str]]:
        return self.conversation.copy()
    
    def clear(self):
        self.conversation.clear()

class AgentState:
    def __init__(self):
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
        self.session_memory: SessionMemory = SessionMemory()
        self.last_read_msg_id: int = -1
        self.pending_action_target: Optional[int] = None
        self.action_submitted: bool = False
        self.pending_chat_messages: List[str] = []

state = AgentState()
app = FastAPI(title="Mafia AI Agent")


# ============================================================================
# Agent Function Tools
# ============================================================================

@function_tool
def submit_night_action(
    target_index: Annotated[int, "Index of player to target (0-indexed). Use -1 to abstain."]
) -> str:
    """
    REQUIRED for night phase if you have a night role (Mafia/Doctor/Police).
    - Mafia: Choose a player to kill.
    - Doctor: Choose a player to save.
    - Police: Choose a player to investigate.
    """
    if state.action_submitted:
        return "You have already submitted an action for this phase."
    
    action_type = state.role if state.role in ["mafia", "doctor", "police"] else "NONE"
    
    if action_type != "NONE":
        if 0 <= target_index < state.num_players and target_index != state.player_index:
            state.pending_action_target = target_index
            state.action_submitted = True
            logger.info(f"[ACTION] AI decided to perform {action_type.upper()} on Player {target_index}")
            return f"Night action submitted: targeting Player {target_index}"
        else:
            state.pending_action_target = None
            state.action_submitted = True
            logger.info(f"[ACTION] AI decided to ABSTAIN from night action.")
            return "Invalid target or abstained. No action will be taken."
    else: # Citizen
        state.pending_action_target = None
        state.action_submitted = True
        logger.info(f"[ACTION] AI is a Citizen, sending dummy action.")
        return "You have no night action (Citizen). Dummy data will be sent for security."

@function_tool
def submit_vote(
    target_index: Annotated[int, "Index of player to vote for elimination (0-indexed). Use -1 to abstain."]
) -> str:
    """REQUIRED for vote phase. Cast your vote to eliminate a player."""
    if state.action_submitted:
        return "You have already submitted a vote for this phase."
    
    if 0 <= target_index < state.num_players and target_index != state.player_index:
        state.pending_action_target = target_index
        state.action_submitted = True
        logger.info(f"[ACTION] AI decided to VOTE for Player {target_index}")
        return f"Vote submitted: voting to eliminate Player {target_index}"
    else:
        state.pending_action_target = None
        state.action_submitted = True
        logger.info(f"[ACTION] AI decided to ABSTAIN from voting.")
        return "Invalid vote target or abstained. You will abstain from voting."


# ============================================================================
# Agent Creation
# ============================================================================

def create_mafia_agent(role: str, player_index: int, num_players: int) -> Agent:
    """Create an OpenAI Agent with role-specific instructions."""
    
    role_instructions = {
        "mafia": f"You are Player {player_index}, a MAFIA member. Your goal is to eliminate citizens. Use submit_night_action() to kill someone.",
        "doctor": f"You are Player {player_index}, a DOCTOR. Your goal is to save citizens. Use submit_night_action() to save someone.",
        "police": f"You are Player {player_index}, a POLICE officer. Your goal is to find mafia. Use submit_night_action() to investigate someone.",
        "citizen": f"You are Player {player_index}, a CITIZEN. Your goal is to vote out mafia. You have no night action (call submit_night_action(-1))."
    }
    instructions = (
        f"You are playing a game of Mafia. Your player index is {player_index}. There are {num_players} players total.\n"
        f"{role_instructions.get(role, role_instructions['citizen'])}\n"
        "During the day, you can chat with other players (not yet implemented).\n"
        "You MUST call submit_night_action() during the night phase and submit_vote() during the vote phase before responding."
    )
    
    return Agent(
        name=f"MafiaPlayer{player_index}",
        instructions=instructions,
        tools=[submit_night_action, submit_vote],
        model="gpt-4o",
    )

# ============================================================================
# API Endpoints
# ============================================================================

@app.post("/init")
async def initialize_agent(request: InitRequest):
    """Initialize agent with game parameters and role."""
    try:
        state.context = deserialize_context(request.public_context)
        state.role = request.role.lower()
        state.player_index = request.player_index
        state.num_players = request.num_players
        state.alive = True
        state.session_memory.clear()
        state.last_read_msg_id = -1
        state.agent = create_mafia_agent(state.role, state.player_index, state.num_players)
        
        logger.info("="*50)
        logger.info(f"AGENT INITIALIZED")
        logger.info(f"  - Player Index: {state.player_index}")
        logger.info(f"  - Role: {state.role.upper()}")
        logger.info("="*50)
        
        return {"success": True, "message": f"Agent initialized as {state.role}"}
    except Exception as e:
        logger.error(f"Error in /init: {e}", exc_info=True)
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
        logger.info("-" * 50)
        logger.info(f"PHASE START: {request.phase.upper()} (Turn {state.current_turn})")
        logger.info(f"SURVIVORS: [{survivors_str}]")

        if not state.alive:
            logger.info("Agent is dead. Sending dummy zero vector.")
            encrypted_vector = create_zero_vector(state.num_players, state.context)
            return ActionResponse(encrypted_action=serialize_encrypted_vector(encrypted_vector), phase=request.phase)

        if request.phase in ["night", "vote"]:
            if request.phase == "night":
                state.current_turn += 1
            
            prompt = f"""Current Phase: {request.phase.upper()} - Turn {state.current_turn}
Survivors: [{survivors_str}]
Your Role: {state.role.upper()}
Host Message: '{request.message}'

Your task is to analyze the situation and decide on your action.
You MUST call the required function (submit_night_action or submit_vote) before finishing.
Think step-by-step about your strategy and then make your call."""
            
            logger.info(f"TASK: Prompting AI.\n---PROMPT START---\n{prompt}\n---PROMPT END---")

            messages = state.session_memory.get_messages()
            messages.append({"role": "user", "content": prompt})

            result = await Runner.run(
                starting_agent=state.agent,
                input=messages,
                max_turns=5 
            )

            # Log AI interaction with detailed information
            logger.info("=" * 60)
            logger.info("AI EXECUTION SUMMARY")
            logger.info("=" * 60)
            logger.info(f"Total items generated: {len(result.new_items)}")
            logger.info("")
            
            for idx, item in enumerate(result.new_items, 1):
                logger.info(f"--- Item {idx}/{len(result.new_items)} ---")
                
                if isinstance(item, ToolCallItem):
                    # Function call by AI
                    func_name = getattr(item.raw_item, 'name', 'unknown')
                    func_args = getattr(item.raw_item, 'arguments', '{}')
                    logger.info(f"[FUNCTION CALL]")
                    logger.info(f"  Function: {func_name}")
                    logger.info(f"  Arguments: {func_args}")
                    
                elif isinstance(item, ToolCallOutputItem):
                    # Function execution result
                    logger.info(f"[FUNCTION RESULT]")
                    logger.info(f"  Output: {item.output}")
                    
                elif isinstance(item, MessageOutputItem):
                    # AI's message/thought
                    message_text = ItemHelpers.text_message_output(item)
                    logger.info(f"[AI MESSAGE]")
                    logger.info(f"  Content: {message_text}")
                    
                else:
                    # Other types
                    item_type = type(item).__name__
                    logger.info(f"[OTHER: {item_type}]")
                    if hasattr(item, 'raw_item'):
                        raw_type = getattr(item.raw_item, 'type', 'unknown')
                        logger.info(f"  Raw type: {raw_type}")
                
                logger.info("")
            
            logger.info(f"[FINAL OUTPUT] {result.final_output}")
            logger.info("=" * 60)

            state.session_memory.add_turn(prompt, str(result.final_output))

            if not state.action_submitted:
                logger.warning("AI did not submit an action, defaulting to abstain.")
                state.pending_action_target = None
        else:
            logger.info("No action required for this phase.")
            state.pending_action_target = None
        
        # Encrypt final action
        if state.pending_action_target is not None:
            encrypted_vector = create_one_hot_vector(state.num_players, state.pending_action_target, state.context)
            logger.info(f"Submitting ENCRYPTED action for target: {state.pending_action_target}")
        else:
            encrypted_vector = create_zero_vector(state.num_players, state.context)
            logger.info("Submitting ENCRYPTED dummy/abstain action.")
        
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
    
    log_file_path = os.path.join(logs_dir, f"agent_{port}.log")
    
    # Create file handler with append mode to keep all logs
    file_handler = logging.FileHandler(log_file_path, mode='a')
    file_handler.setLevel(logging.DEBUG)
    file_handler.setFormatter(logging.Formatter(
        '%(asctime)s [%(levelname)s] %(name)s: %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S'
    ))
    
    # Console handler
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(logging.INFO)
    console_handler.setFormatter(logging.Formatter(
        '%(asctime)s [%(levelname)s] %(message)s',
        datefmt='%H:%M:%S'
    ))
    
    # Configure root logger - clear existing handlers first
    root_logger = logging.getLogger()
    root_logger.handlers.clear()  # 중복 방지
    root_logger.setLevel(logging.DEBUG)
    root_logger.addHandler(file_handler)
    root_logger.addHandler(console_handler)
    
    # Configure uvicorn loggers - clear and set handlers
    for logger_name in ['uvicorn', 'uvicorn.access', 'uvicorn.error']:
        uvicorn_logger = logging.getLogger(logger_name)
        uvicorn_logger.handlers.clear()  # 중복 방지
        uvicorn_logger.propagate = True  # root logger로 전파
        uvicorn_logger.setLevel(logging.INFO)
    
    # OpenAI SDK loggers - 너무 상세하므로 WARNING만
    for logger_name in ['openai', 'httpx', 'httpcore']:
        sdk_logger = logging.getLogger(logger_name)
        sdk_logger.setLevel(logging.WARNING)
        sdk_logger.propagate = True

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Mafia AI Agent Player")
    parser.add_argument("--port", type=int, required=True, help="Port to run on")
    parser.add_argument("--api-key", type=str, required=True, help="OpenAI API key")
    parser.add_argument("--agent-id", type=int, required=True, help="Agent ID")
    
    args = parser.parse_args()

    # Setup logging BEFORE anything else
    setup_logging(args.port)

    # Set OpenAI API key
    os.environ["OPENAI_API_KEY"] = args.api_key
    state.agent_id = args.agent_id
    
    logger.info(f"="*60)
    logger.info(f"Starting Mafia AI Agent #{args.agent_id} on port {args.port}")
    logger.info(f"OpenAI API Key: {args.api_key[:10]}...")
    logger.info(f"="*60)
    
    # Run uvicorn with log_config to integrate with our logging
    uvicorn.run(
        app, 
        host="0.0.0.0", 
        port=args.port,
        log_config=None,  # Disable default logging
        access_log=True
    )
