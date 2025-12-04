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
from investigation import InvestigationResult
from memory import StrategicMemory

from models import (
    InitRequest,
    GameUpdateRequest,
    ActionResponse,
    ChatBroadcast,
    ChatPhaseRequest
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
        self.context: Optional[ts.Context] = None
        self.role: Optional[str] = None
        self.player_index: Optional[int] = None
        self.num_players: int = 0
        self.agent: Optional[Agent] = None
        self.alive: bool = True
        self.survivors: List[int] = []  # Track alive players
        self.current_phase: str = "setup"
        self.current_turn: int = 0
        self.chat_history: GameChatHistory = GameChatHistory()
        self.suspicion_notes: Optional[SuspicionNoteManager] = None
        self.strategic_memory: Optional[StrategicMemory] = None  # Advanced strategic memory
        self.session: Optional[SQLiteSession] = None
        self.last_read_msg_id: int = -1
        self.pending_action_target: Optional[int] = None
        self.action_submitted: bool = False
        self.pending_chat_messages: List[str] = []
        self.chat_phase_active: bool = False  # 대화 phase 활성 여부
        self.chat_phase_task: Optional[any] = None  # 비동기 태스크 참조
        self.host_address: str = "http://localhost:5000"  # Host address
        self.last_message_time: float = 0.0  # Track last message time for rate limiting
        self.last_night_result: str = ""  # What happened last night

state = AgentState()
app = FastAPI(title="Mafia AI Agent")

# Track if shutdown is requested
shutdown_requested = False


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
        state.host_address = request.host_address
        state.alive = True
        
        # Initialize survivors list with all players
        state.survivors = list(range(state.num_players))
        
        # Initialize suspicion notes manager (Police gets special version)
        if state.role == "police":
            state.suspicion_notes = PoliceNoteManager(state.num_players, state.player_index)
        else:
            state.suspicion_notes = SuspicionNoteManager(state.num_players, state.player_index)
        
        # Initialize strategic memory system
        state.strategic_memory = StrategicMemory(state.num_players, state.player_index)
        logger.info("🧠 Strategic memory system initialized")
        
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
        
        # Update survivors state for chat phase to use
        state.survivors = request.survivors
        
        # Process death information
        death_notice = ""
        if request.recently_killed:
            killed_str = ", ".join(str(k) for k in request.recently_killed)
            death_notice = f"💀 NIGHT DEATHS: Players [{killed_str}] were killed"
            logger.info(death_notice)
        
        if request.recently_voted_out >= 0:
            death_notice = f"🗳️ VOTED OUT: Player {request.recently_voted_out} was eliminated"
            logger.info(death_notice)
        
        # Store night result if this is day start
        if request.phase == "day_start":
            state.last_night_result = request.message
            if death_notice:
                state.last_night_result += f"\n{death_notice}"
            logger.info(f"🌅 {request.message}")

        survivors_str = ", ".join(str(s) for s in request.survivors)
        dead_str = ", ".join(str(d) for d in request.dead_players) if request.dead_players else "none"
        logger.info(f"🎮 Turn {state.current_turn} | {request.phase.upper()}")
        logger.info(f"   🟢 Alive: [{survivors_str}]")
        logger.info(f"   💀 Dead: [{dead_str}]")
        
        # Update strategic memory with deaths
        if state.strategic_memory:
            # Record night kills
            if request.recently_killed:
                for victim in request.recently_killed:
                    state.strategic_memory.record_death(victim, state.current_turn, "night")
                    # Mark as dead in profile
                    if victim in state.strategic_memory.profiles:
                        state.strategic_memory.profiles[victim].is_dead = True
            
            # Record vote elimination
            if request.recently_voted_out >= 0:
                state.strategic_memory.record_death(request.recently_voted_out, state.current_turn, "vote")
                if request.recently_voted_out in state.strategic_memory.profiles:
                    state.strategic_memory.profiles[request.recently_voted_out].is_dead = True
        
        # Update suspicion notes with dead players
        if state.suspicion_notes:
            for i in range(state.num_players):
                if i not in request.survivors and i != state.player_index:
                    state.suspicion_notes.mark_player_dead(i)

        if not state.alive:
            logger.info("💀 Agent is dead. Sending dummy action.")
            encrypted_vector = create_zero_vector(state.num_players, state.context)
            return ActionResponse(encrypted_action=serialize_encrypted_vector(encrypted_vector), phase=request.phase)

        # Optimization: If it's night and the agent has no special role, just sleep.
        is_night_action_role = state.role in ["mafia", "doctor", "police"]
        if request.phase == "night" and not is_night_action_role:
            sleep_time = random.uniform(2, 5)
            logger.info(f"😴 Non-acting role. Sleeping for {sleep_time:.2f}s...")
            await asyncio.sleep(sleep_time)
            
            encrypted_vector = create_zero_vector(state.num_players, state.context)
            logger.info("➖ Action: Abstain (slept)")
            
            return ActionResponse(
                encrypted_action=serialize_encrypted_vector(encrypted_vector),
                phase=request.phase,
                chat_messages=[] # No chat messages while sleeping
            )

        if request.phase in ["night", "vote"]:
            if request.phase == "night":
                state.current_turn += 1
            
            from agent_logic import create_agent_tools
            phase_tools = create_agent_tools(state, phase=request.phase)
            state.agent.tools = phase_tools
            
            dead_str = ", ".join(str(d) for d in request.dead_players) if request.dead_players else "none"
            
            prompt = create_action_prompt(
                phase=request.phase,
                turn=state.current_turn,
                survivors_str=survivors_str,
                dead_str=dead_str,
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
            encrypted_vector = create_one_hot_vector(state.num_players, state.pending_action_target, state.context)
            logger.info(f"✅ Action: Target={state.pending_action_target}")
        else:
            encrypted_vector = create_zero_vector(state.num_players, state.context)
            logger.info("➖ Action: Abstain")
        
        return ActionResponse(
            encrypted_action=serialize_encrypted_vector(encrypted_vector),
            phase=request.phase,
            chat_messages=state.pending_chat_messages
        )
    except Exception as e:
        logger.error(f"Error in /request_action: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/health")
async def health_check():
    return {"status": "healthy", "alive": state.alive}


@app.post("/shutdown")
async def shutdown():
    """Graceful shutdown endpoint - called when agent dies"""
    global shutdown_requested
    logger.info("💀 Shutdown requested - Agent is dead. Cleaning up...")
    shutdown_requested = True
    state.alive = False
    
    # Clean up session (keep history for analysis)
    if state.session:
        try:
            await state.session.close()
        except Exception as e:
            logger.error(f"Error during session cleanup: {e}")
    
    # Schedule exit
    import asyncio
    asyncio.create_task(delayed_exit())
    
    return {"message": "Agent shutting down gracefully"}


async def delayed_exit():
    """Exit after a short delay to allow response to be sent"""
    import asyncio
    await asyncio.sleep(2)
    logger.info("👋 Goodbye!")
    os._exit(0)


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
        
        # Record in strategic memory for behavior analysis
        if state.strategic_memory:
            state.strategic_memory.record_message(
                broadcast.player_index,
                broadcast.message,
                broadcast.turn
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
            # If already active, force stop first
            if state.chat_phase_active:
                logger.warning("⚠️  Chat phase already active, stopping old session first...")
                state.chat_phase_active = False
                if state.chat_phase_task:
                    state.chat_phase_task.cancel()
                    try:
                        await state.chat_phase_task
                    except asyncio.CancelledError:
                        pass
                    state.chat_phase_task = None
            
            state.chat_phase_active = True
            logger.info(f"💬 Chat phase started (Turn {request.turn}, {request.duration_seconds}s)")
            
            import asyncio
            state.chat_phase_task = asyncio.create_task(
                _chat_phase_session(request.turn)
            )
            
            return {"success": True, "message": f"Chat phase started for turn {request.turn}"}
        
        elif request.action == "stop":
            state.chat_phase_active = False
            if state.chat_phase_task:
                state.chat_phase_task.cancel()
                try:
                    await state.chat_phase_task
                except asyncio.CancelledError:
                    pass  # Expected when cancelling
                except Exception as e:
                    logger.error(f"Error while stopping chat task: {e}")
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
        
        # Use the actual survivors list from state
        survivors_str = ", ".join(f"Player {i}" for i in state.survivors if i != state.player_index)
        role = state.role
        
        # 다양한 페르소나 풀 - 각 역할마다 랜덤 선택
        persona_pools = {
            "mafia": [
                ("냉철한 전략가", "침착하고 논리적임. 차분하게 상황 분석하고 다른 사람 실수 지적하는 스타일"),
                ("사교적인 사람", "친근하고 말 많음. 농담도 하고 분위기 띄우면서 자연스럽게 의심 피해가는 스타일"),
                ("조용한 관찰자", "말 적고 필요할 때만 한마디씩. 핵심만 찌르는 스타일"),
                ("의심 많은 타입", "뭐든 의심함. 다른 사람들도 같이 의심하게 만드는 스타일"),
            ],
            "police": [
                ("논리적 분석가", "차근차근 따지는 스타일. 행동 패턴 분석하고 추론함"),
                ("직감형 탐정", "느낌으로 캐치함. 직관 믿고 빠르게 판단하는 스타일"),
                ("신중한 수사관", "증거 중시. 확실한 거 아니면 말 안하는 스타일"),
                ("질문 폭격형", "의심되는 사람한테 질문 계속 던지는 스타일"),
            ],
            "doctor": [
                ("보호자 타입", "시민들 걱정하고 지키려는 마음이 큰 스타일"),
                ("전략적 의사", "누구 살릴지 전략적으로 생각하는 스타일"),
                ("조용한 지원군", "뒤에서 서포트. 말 많이 안하고 핵심만 찌르는 스타일"),
                ("분석형 의사", "누가 위험한지 패턴 보면서 판단하는 스타일"),
            ],
            "citizen": [
                ("열정적 시민", "마피아 잡는데 열심. 적극적으로 의견 내는 스타일"),
                ("신중한 시민", "함부로 말 안함. 확실한 거 아니면 조심스러운 스타일"),
                ("불안한 시민", "살아남고 싶어서 누구 믿어야 할지 모르겠는 스타일"),
                ("무심한 시민", "별로 적극적이지 않음. 필요하면 한마디 하는 스타일"),
            ],
        }
        
        # 랜덤으로 페르소나 선택
        persona_list = persona_pools.get(role, [("일반 플레이어", "평범하게 행동함")])
        persona_name, persona_desc = random.choice(persona_list)
        
        # 역할별 상세 전략 가이드
        strategy_guides = {
            "mafia": """🎭 마피아 전략 가이드:

1. 거짓말 & 위장:
   - 시민인 척 행동해. 적극적으로 마피아 찾는 척
   - "나도 궁금하네", "Player X 수상한데?" 같이 자연스럽게
   - 절대 방어적으로 굴지 마. 의심받으면 오히려 당당하게 반박
   
2. 선동 & 프레임:
   - 진짜 경찰/의사를 가짜라고 몰아가
   - "경찰이라고? 증거는?" "왜 하필 그 사람 조사?"
   - 무고한 시민한테 의심 돌려. 투표 유도해
   
3. 대화 패턴:
   - 다른 사람 말 잘 듣는 척. "그거 좋은 지적이네"
   - 가끔 맞는 추론도 해. 신뢰 쌓기
   - 시민들끼리 싸우게 만들어. "Player X랑 Y 중 하나 수상함"
   
4. 위기 대응:
   - 의심받으면: "나 시민인데? 왜 나를?" + 반대로 의심한 사람 공격
   - 동료 마피아 위험: 거리두기. "나도 그 사람 의심했음"
   - 투표 받을 때: 다른 타겟 만들어. "Player Z가 더 수상한데?"

⚠️ 절대 금지:
- 마피아끼리 너무 편들기
- 방어만 하기 (공격이 최선의 방어)
- 일관성 없는 주장
- 진짜 경찰 말 너무 쉽게 믿기""",
            
            "police": """🔍 경찰 전략 가이드:

1. 정보 관리 (가장 중요):
   - 초반엔 역할 숨겨. 마피아가 알면 타겟됨
   - 마피아 찾았어도 바로 말하지 마. 타이밍 중요
   - "내 생각엔..." 형식으로 조심스럽게 힌트
   
2. 가짜 경찰 대응:
   - 마피아가 "나 경찰" 하면: 일단 침묵하고 관찰
   - 거짓말 포인트 찾아: "왜 하필 그 사람?", "어제 행동 이상했는데"
   - 시민들이 믿을 때만 "나도 경찰인데 그건 거짓말"
   
3. 조사 결과 공유:
   - 마피아 확정: 2-3명 동의 얻고 나서 공개
   - 시민 확정: "Player X는 믿을만함" 정도로만
   - 증거 기반으로: "어제 행동 패턴보면...", "투표 보면..."
   
4. 생존 전략:
   - 너무 똑똑해 보이지 마. 마피아가 노림
   - 의사한테 힌트: "난 밤에 일하는 사람", "날 지켜줬으면"
   - 위험하면 커밍아웃: "난 경찰. Player X 마피아 확정"

⚠️ 절대 금지:
- 1턴에 "나 경찰" (자살행위)
- 모든 조사 결과 다 말하기
- 가짜 경찰 말 그냥 믿기
- 혼자 싸우기 (동료 만들어)""",
            
            "doctor": """💊 의사 전략 가이드:

1. 역할 은폐 (생존 핵심):
   - 절대 "나 의사" 하지 마. 마피아가 죽임
   - 일반 시민처럼 행동
   - 누구 살렸는지 힌트 주지 마
   
2. 힐 우선순위:
   - 초반: 랜덤 or 자신
   - 경찰 의심되면: 경찰 보호
   - 중반: 리더급 시민
   - 위급: 자신 (살아야 계속 힐)
   
3. 대화 전략:
   - 추리 참여해. 똑똑하지만 너무 튀지 않게
   - "아무도 안 죽었네?" → 모르는 척. "운 좋았나?"
   - 경찰 찾기: 행동 패턴으로 추측, 은밀히 보호
   
4. 위기 시:
   - 의심받으면: 시민인 척 방어
   - 마지막 순간: "나 의사야, 날 살려야 이긴다"
   - 경찰이 위험: 커밍아웃 고려

⚠️ 절대 금지:
- 역할 공개
- "Player X 어제 살렸어"
- 패턴 노출 (같은 사람만 계속 힐)
- 너무 조용함 (의심받음)""",
            
            "citizen": """👥 시민 전략 가이드:

1. 추리 & 관찰:
   - 대화 패턴 주시: 누가 선동하나? 누가 방어적인가?
   - 투표 패턴: 마피아는 서로 안 찍음
   - 거짓말 포착: "아까 말 바뀜", "왜 갑자기 의견 변경?"
   
2. 정보 수집:
   - 질문 많이 해: "Player X, 왜 그렇게 생각해?"
   - 압박: "증거 있어?", "어제 뭐 했어?"
   - 반응 보기: 방어적이면 의심
   
3. 연합 & 신뢰:
   - 믿을 만한 시민 찾기
   - 경찰/의사 보호하려 노력
   - 투표할 때 이유 명확히: "왜냐하면..."
   
4. 가짜 정보 대응:
   - "나 경찰" → "증거는? 왜 이제 말해?"
   - 선동 → "근거 없는 몰이", "Player Y가 선동중"
   - 프레임 → "나 아니야" + 증거 대기
   
5. 투표 전략:
   - 확신 없으면 다수 따라가되, 이유 물어봐
   - 의심가는 사람 있으면 설득 시도
   - 투표 패턴으로 마피아 찾기

⚠️ 절대 금지:
- 근거 없이 투표
- 선동에 쉽게 휘말림
- 침묵 (의심받음)
- 중요 역할 의심 (경찰/의사 죽이면 패배)"""
        }
        
        role_strategy = strategy_guides.get(role, "일반 플레이")
        
        # 죽은 사람 목록
        all_players = set(range(state.num_players))
        survivors_set = set(state.survivors)
        dead_set = all_players - survivors_set - {state.player_index}
        dead_str = ", ".join(f"Player {d}" for d in sorted(dead_set)) if dead_set else "아무도 없음"
        
        # 밤 결과 정보
        night_info = f"\n📰 지난 밤 결과:\n{state.last_night_result}\n" if state.last_night_result else ""
        
        prompt = f"""{turn}턴 - 대화 토론 단계
{night_info}
🟢 생존자: {survivors_str}
💀 죽은 사람: {dead_str}

=== 너의 캐릭터 ===
역할: {role}
성격: {persona_name}
특징: {persona_desc}

{role_strategy}

=== 핵심 행동 원칙 ===

🎯 전략 실행:
- 위 전략 가이드 따라서 행동해
- 역할에 맞게 거짓말하거나 진실 말하기
- 상황 보고 유연하게 대응

🕵️ 거짓말 탐지:
- 누가 "나 경찰"이라고 하면: 증거 요구, 의심해봐
- 말 바뀌는 사람: "아까는 다르게 말했는데?"
- 선동하는 사람: "왜 그 사람만 공격해?" 
- 너무 방어적: "왜 그렇게 변명해?"

💭 이전 대화 기억:
- read_chat_messages()로 최근 대화 확인
- 누가 뭐라고 했는지 기억
- 말 바뀌면 지적: "아까는 Player X 의심했잖아"
- 투표 패턴 기억: "Player Y는 항상 시민만 찍네"

🛡️ 방어 전략:
- 의심받으면: 당당하게 + 반대로 공격
- "나 아닌데?" (X) → "Player Z가 더 수상함" (O)
- 증거 기반으로 반박
- 동료 만들기: "Player A도 같은 생각 아님?"

=== 말투 가이드 (중요!) ===
반드시 이런 스타일로 말해:
- 반말 사용: "~야", "~임", "~인가?", "~였음?", "~ㄴ가?", "~던데", "~나봐"
- 축약형: "그건", "뭔가", "좀", "진짜", "ㄹㅇ", "ㅇㅇ"
- 자연스러운 표현: "아 ㅋㅋ", "어?", "음..", "흠..", "그니까", "근데", "암튼"
- 짧게 말하기: 1-2문장이면 충분. 길게 떠들지 마.

예시:
❌ "저는 Player 2가 의심스럽습니다. 왜냐하면..."
✅ "Player 2 좀 수상한데? 말이 너무 없음"
❌ "동의합니다. 투표는 신중하게 해야 할 것 같습니다."
✅ "ㅇㅇ 맞음 조심해야됨"

=== 대화 흐름 (자연스럽게!) ===

1. 먼저 read_chat_messages() 호출해서 채팅 읽어

2. 메시지 읽은 후 행동 선택:
   
   ✅ 말할 거 있으면 -> 5-10초 기다린 후 send_chat_message()
   
   ✅ 말할 거 없으면 -> 그냥 read_chat_messages() 다시 호출
      (침묵도 자연스러움. 매번 말할 필요 없어)
   
   ✅ 누가 너한테 질문했으면 -> 반드시 답변해야 함
   
   ✅ 대화 흐름이 끊겼으면 -> 새로운 주제 던지거나 질문해

3. 타이밍이 중요함:
   - 너무 빨리 말하지 마 (사람처럼 생각하는 시간 필요)
   - 5-10초 정도 기다렸다가 말해
   - 다른 사람 말 끊지 마
   - 말 없으면 그냥 기다려도 됨

4. 대화 맥락 유지:
   - 최근 3-5개 메시지 확인
   - 대화 주제 파악하고 거기에 맞춰 말해
   - 갑자기 동떨어진 얘기 하지 마
   - 다른 사람 말 언급하면서 이어가: "Player X 말인데~", "아까 Player Y가~"

5. 자연스러운 참여:
   - 항상 말해야 하는 건 아님
   - 할 말 없으면 read만 하고 넘어가도 됨
   - 3-4번 read 하다가 한번 말하는 것도 자연스러움
   - 질문 받았거나 네 얘기 나오면 그때 반응해

=== 금지 사항 ===
❌ "말이 없군요", "쓰고 있나보네요" 같은 메타 발언 절대 금지
❌ 연속으로 혼자 떠들기 금지
❌ 너무 정중한 말투 ("~습니다", "~해주세요") 금지
❌ 같은 말 반복 금지
❌ 긴 문장 금지 (1-2문장 max)

다른 플레이어: {survivors_str}

패턴: read_chat_messages() -> [생각] -> (말할 거 있으면) 5-10초 대기 -> send_chat_message() -> 반복

시작해. 한국어 반말로만 말해.
"""
        
        # Add initial random delay so agents don't all start at once
        # Longer delay for more natural conversation start
        initial_delay = random.uniform(3.0, 8.0)
        await asyncio.sleep(initial_delay)
        
        logger.info(f"💬 Starting autonomous chat session (Turn {turn})...")
        
        # Use very large max_turns for autonomous chat (SDK doesn't support None)
        result = await Runner.run(
            starting_agent=state.agent,
            input=prompt,
            session=state.session,
            max_turns=10000  # Extremely high limit - agent continues until cancelled
        )
        
        logger.info(f"💬 Chat session ended naturally (Turn {turn})")
    
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