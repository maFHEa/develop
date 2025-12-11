"""
Action Handlers - Phase별 게임 액션 처리 로직 분리
각 phase의 복잡한 로직을 독립적인 함수로 추출하여 가독성과 테스트 가능성 향상
"""
import logging
import asyncio
import random
from typing import Optional, Tuple, List

from agents import Runner, ToolCallItem, ToolCallOutputItem, MessageOutputItem, ItemHelpers
from service.crypto.vector_operations import create_one_hot_vector, create_zero_vector
from service.crypto.serialization import serialize_ciphertext
from agent_logic import create_agent_tools, create_action_prompt, create_chat_prompt

logger = logging.getLogger(__name__)
logger.propagate = False  # Prevent duplicate logs


# ============================================================================
# Helper Functions
# ============================================================================

def log_phase_start(phase: str, turn: int, survivors: List[int], dead_players: List[int], message: str):
    """Phase 시작 로깅 (생존자 순서 랜덤화하여 편향 방지)"""
    shuffled_survivors = list(survivors)
    random.shuffle(shuffled_survivors)
    survivors_str = ", ".join(str(s) for s in shuffled_survivors)
    dead_str = ", ".join(str(d) for d in dead_players)
    
    logger.info("")
    logger.info("━" * 60)
    logger.info(f"📍 {phase.upper()} PHASE | Turn {turn}")
    logger.info(f"👥 Alive (randomized order): {survivors_str}")
    logger.info(f"💀 Dead: {dead_str}")
    logger.info(f"💬 Message: {message}")
    logger.info("━" * 60)
    
    return survivors_str, dead_str


def log_ai_interaction(result):
    """AI 호출 결과 로깅"""
    logger.info("")
    logger.info("┌─ AI Decision ─────────────────────────────────────────────┐")
    
    for item in result.new_items:
        if isinstance(item, ToolCallItem):
            import json
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


async def call_ai_with_retry(state, prompt: str, max_turns: int = 20) -> bool:
    """AI 호출 및 자동 재시도 (action이 제출되지 않으면 리마인더 전송)"""
    # Initial AI call with conversation lock retry
    max_lock_retries = 3
    for attempt in range(max_lock_retries):
        try:
            result = await Runner.run(
                starting_agent=state.agent,
                input=prompt,
                session=state.session,
                max_turns=max_turns
            )
            break  # Success
        except Exception as e:
            if "conversation_lock_failed" in str(e) and attempt < max_lock_retries - 1:
                wait_time = (attempt + 1) * 0.5  # 0.5s, 1s, 1.5s
                logger.warning(f"🔒 Conversation lock failed, retrying in {wait_time}s... (attempt {attempt + 1}/{max_lock_retries})")
                await asyncio.sleep(wait_time)
            else:
                raise  # Re-raise if not lock error or max retries exceeded
    
    log_ai_interaction(result)
    
    # Check if action was submitted
    if state.action_submitted:
        return True
    
    # Retry with urgent reminder
    logger.warning("⚠️  AI did not submit an action, sending urgent reminder...")
    
    action_tool = "submit_night_action" if state.current_phase == "night" else "submit_vote"
    survivors_list = [i for i in range(state.num_players) if i in state.chat_history.messages or i == state.player_index]
    
    reminder_prompt = f"""🚨 URGENT: Submit your action NOW!

ALIVE players: {survivors_list}

Call {action_tool}(target_index) immediately.
Choose any alive player from the list above.

No more analysis - act now!"""
    
    try:
        # Retry with lock handling
        for attempt in range(max_lock_retries):
            try:
                retry_result = await Runner.run(
                    starting_agent=state.agent,
                    input=reminder_prompt,
                    session=state.session,
                    max_turns=3
                )
                break  # Success
            except Exception as retry_err:
                if "conversation_lock_failed" in str(retry_err) and attempt < max_lock_retries - 1:
                    wait_time = (attempt + 1) * 0.5
                    logger.warning(f"🔒 Retry lock failed, waiting {wait_time}s...")
                    await asyncio.sleep(wait_time)
                else:
                    raise
        
        if state.action_submitted:
            logger.info("✅ AI submitted action after reminder")
            return True
        else:
            logger.error("❌ AI still did not submit action after reminder, forcing abstain")
            state.pending_action_target = None
            return False
    except Exception as e:
        logger.error(f"Retry failed: {e}")
        state.pending_action_target = None
        return False


# ============================================================================
# Phase Handlers
# ============================================================================

async def handle_vote_phase(state, request) -> Tuple[str, str, str]:
    """
    투표 단계 처리
    Returns: (vote_vector_b64, attack_vector_b64, heal_vector_b64)
    """
    survivors_str, dead_str = log_phase_start(
        request.phase, state.current_turn, request.survivors, request.dead_players, request.message
    )
    
    # Update agent tools for vote phase
    state.agent.tools = create_agent_tools(state, phase="vote")
    
    # Create AI prompt
    prompt = create_action_prompt(
        phase="vote",
        turn=state.current_turn,
        survivors_str=survivors_str,
        dead_str=dead_str,
        role=state.role,
        message=request.message,
        state=state  # 스마트 컨텍스트 생성을 위해 state 전달
    )
    
    logger.debug(f"AI Prompt:\n{prompt}")
    logger.info("🤖 Calling AI agent for vote decision...")
    
    # Call AI
    await call_ai_with_retry(state, prompt)
    
    # Generate vote vectors
    if state.pending_action_target is not None and state.pending_action_target >= 0:
        vote_vec = create_one_hot_vector(
            state.num_players,
            state.pending_action_target,
            state.cc,
            state.joint_public_key
        )
        logger.info(f"🗳️ Vote: Player {state.pending_action_target}")
        
        # Record vote action in game memory
        if state.game_memory:
            state.game_memory.record_action(
                turn=state.current_turn,
                phase="vote",
                action_type="vote",
                target_index=state.pending_action_target,
                reasoning=f"Voted for Player {state.pending_action_target}"
            )
    else:
        vote_vec = create_zero_vector(state.num_players, state.cc, state.joint_public_key)
        logger.info("🗳️ Vote: Abstained")
        
        # Record abstention
        if state.game_memory:
            state.game_memory.record_action(
                turn=state.current_turn,
                phase="vote",
                action_type="abstain",
                target_index=None,
                reasoning="Abstained from voting"
            )
    
    # Heal and investigate are not used in vote phase
    attack_vec = create_zero_vector(state.num_players, state.cc, state.joint_public_key)
    heal_vec = create_zero_vector(state.num_players, state.cc, state.joint_public_key)
    
    # Serialize
    vote_b64 = serialize_ciphertext(state.cc, vote_vec)
    attack_b64 = serialize_ciphertext(state.cc, attack_vec)
    heal_b64 = serialize_ciphertext(state.cc, heal_vec)
    
    return vote_b64, attack_b64, heal_b64


async def handle_night_phase(state, request) -> Optional[int]:
    """
    밤 단계 처리 (마피아/의사/경찰 액션)
    Returns: target_index (or None)
    """
    state.current_turn += 1
    
    survivors_str, dead_str = log_phase_start(
        request.phase, state.current_turn, request.survivors, request.dead_players, request.message
    )
    
    # 시민인 경우 시간을 지연하고 실제로 vector 만들 때 0 벡터 생성을 함.
    if state.role == "citizen":
        delay = random.uniform(1.0, 2.5)  # Reduced from 3-7s to 1-2.5s
        await asyncio.sleep(delay)
        state.pending_action_target = None
        state.action_submitted = True
        asyncio.create_task(send_dummy_investigation_packets(state))
        return None
    
    # Update agent tools for night phase
    state.agent.tools = create_agent_tools(state, phase="night")
    
    # Create AI prompt
    prompt = create_action_prompt(
        phase="night",
        turn=state.current_turn,
        survivors_str=survivors_str,
        dead_str=dead_str,
        role=state.role,
        message=request.message,
        state=state  # 스마트 컨텍스트 생성을 위해 state 전달
    )
    
    logger.debug(f"AI Prompt:\n{prompt}")
    logger.info("🤖 Calling AI agent for night action...")
    
    # Call AI
    await call_ai_with_retry(state, prompt)
    
    return state.pending_action_target


async def handle_chat_phase(state, request) -> Tuple[str, str, str]:
    """
    채팅 단계 처리 (백그라운드에서 AI가 계속 채팅)
    Returns: (vote_vector_b64, attack_vector_b64, heal_vector_b64)
    """
    survivors_str, dead_str = log_phase_start(
        request.phase, state.current_turn, request.survivors, request.dead_players, request.message
    )
    
    # Update agent tools for chat phase
    state.agent.tools = create_agent_tools(state, phase="chat")
    
    remaining_time = request.remaining_time if request.remaining_time else 120
    state.last_message_time = None  # Reset for first message
    
    # Run chat in background
    async def run_chat_loop():
        import time as time_module
        start_time = time_module.time()
        chat_round = 0
        
        while state.current_phase in ["chat", "day"]:
            chat_round += 1
            elapsed = time_module.time() - start_time
            time_left = max(0, remaining_time - elapsed)
            
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
                result = await Runner.run(
                    starting_agent=state.agent,
                    input=prompt,
                    session=state.session,
                    max_turns=10
                )
                
                msgs_sent = len(state.pending_chat_messages)
                logger.info(f"💬 Round {chat_round} complete - {msgs_sent} total messages sent")
                await asyncio.sleep(2)
            except Exception as e:
                logger.error(f"Chat round {chat_round} error: {e}")
                await asyncio.sleep(2)
        
        logger.info(f"💬 Chat phase ended - {chat_round} rounds, {len(state.pending_chat_messages)} messages sent")
    
    # Cancel any existing chat task first
    if hasattr(state, 'chat_task') and state.chat_task and not state.chat_task.done():
        logger.warning("⚠️  Previous chat task still running - cancelling it")
        state.chat_task.cancel()
        try:
            await state.chat_task
        except asyncio.CancelledError:
            logger.info("✓ Previous chat task cancelled")
    
    # Start chat in background and store task reference
    state.chat_task = asyncio.create_task(run_chat_loop())
    logger.info("💬 Chat phase started in background - returning immediately")
    
    # Return zero vectors (no action needed in chat phase)
    zero_vec = create_zero_vector(state.num_players, state.cc, state.joint_public_key)
    zero_vec_b64 = serialize_ciphertext(state.cc, zero_vec)
    
    return zero_vec_b64, zero_vec_b64, zero_vec_b64


# ============================================================================
# Blind Protocol Vector Generation
# ============================================================================

def generate_night_work_vectors(state, phase: str, target_index: Optional[int]) -> Tuple[str, str, str]:
    """
    BLIND PROTOCOL: 3개의 암호화된 벡터 생성 (vote/attack/heal)
    자신의 역할에 해당하는 벡터만 실제 데이터, 나머지는 더미
    경찰 조사는 client-side parallel decrypt로 처리
    
    Returns: (vote_b64, attack_b64, heal_b64)
    """
    # Vote phase: vote_vector에 투표 저장
    if phase == "vote":
        return generate_vote_vector(state, target_index)

    # Night phase: Initialize all vectors first
    vote_vec = create_zero_vector(state.num_players, state.cc, state.joint_public_key)
    attack_vec = create_zero_vector(state.num_players, state.cc, state.joint_public_key)
    heal_vec = create_zero_vector(state.num_players, state.cc, state.joint_public_key)

    if phase == "night":
        # Role-specific vector generation
        if state.role == "mafia" and target_index is not None:
            attack_vec = _generate_night_vectors(state, target_index)
            logger.info(f"🔪 Mafia → P{target_index}")
            
            # Record action in game memory
            if state.game_memory:
                state.game_memory.record_action(
                    turn=state.current_turn,
                    phase="night",
                    action_type="attack",
                    target_index=target_index,
                    reasoning=f"Mafia attacked Player {target_index}"
                )
        elif state.role == "doctor" and target_index is not None:
            heal_vec = _generate_night_vectors(state, target_index)
            logger.info(f"💊 Doctor → P{target_index}")
            
            # Record action in game memory
            if state.game_memory:
                state.game_memory.record_action(
                    turn=state.current_turn,
                    phase="night",
                    action_type="heal",
                    target_index=target_index,
                    reasoning=f"Doctor healed Player {target_index}"
                )
        elif state.role == "citizen":
            # Record citizen abstention
            if state.game_memory:
                state.game_memory.record_action(
                    turn=state.current_turn,
                    phase="night",
                    action_type="none",
                    target_index=None,
                    reasoning="Citizen has no night action"
                )
        # Police investigation은 client-side에서 처리, 서버에는 dummy만 전송
        elif state.role == "police":
            # Record police action (target will be recorded when investigation result comes)
            if state.game_memory and target_index is not None:
                state.game_memory.record_action(
                    turn=state.current_turn,
                    phase="night",
                    action_type="investigate_request",
                    target_index=target_index,
                    reasoning=f"Police requested investigation of Player {target_index}"
                )
    
    # Serialize
    vote_b64 = serialize_ciphertext(state.cc, vote_vec)
    attack_b64 = serialize_ciphertext(state.cc, attack_vec)
    heal_b64 = serialize_ciphertext(state.cc, heal_vec)
    
    return vote_b64, attack_b64, heal_b64

def generate_vote_vector(state, target_index: Optional[int]):
    if target_index is not None and target_index >= 0:
        vote_vec = create_one_hot_vector(
            state.num_players, target_index, state.cc, state.joint_public_key
        )
        logger.info(f"🗳️ Vote → P{target_index}")
    else:
        vote_vec = create_zero_vector(state.num_players, state.cc, state.joint_public_key)
        logger.info("🗳️ Vote: Abstain")
    
    attack_vec = create_zero_vector(state.num_players, state.cc, state.joint_public_key)
    heal_vec = create_zero_vector(state.num_players, state.cc, state.joint_public_key)
    # Serialize
    vote_b64 = serialize_ciphertext(state.cc, vote_vec)
    attack_b64 = serialize_ciphertext(state.cc, attack_vec)
    heal_b64 = serialize_ciphertext(state.cc, heal_vec)
    
    return vote_b64, attack_b64, heal_b64


def _generate_night_vectors(state, target_index: int):
    vector = create_one_hot_vector(state.num_players, target_index, state.cc, state.joint_public_key)
    return vector

def generate_all_zero_vectors(state):
    vote_vec = create_zero_vector(state.num_players, state.cc, state.joint_public_key)
    attack_vec = create_zero_vector(state.num_players, state.cc, state.joint_public_key)
    heal_vec = create_zero_vector(state.num_players, state.cc, state.joint_public_key)
    # Serialize
    vote_b64 = serialize_ciphertext(state.cc, vote_vec)
    attack_b64 = serialize_ciphertext(state.cc, attack_vec)
    heal_b64 = serialize_ciphertext(state.cc, heal_vec)
    
    return vote_b64, attack_b64, heal_b64


async def send_dummy_investigation_packets(state):
    """
    모든 플레이어가 네트워크 obfuscation을 위해 dummy investigation packet 전송
    경찰의 실제 조사 패킷과 비경찰의 dummy 패킷이 비슷한 시간대에 전송되도록 함
    """
    
    dummy_ciphertext = serialize_ciphertext(
        state.cc,
        create_zero_vector(state.num_players, state.cc, state.joint_public_key)
    )
    
    # Send to all other players
    tasks = []
    for i in range(state.num_players):
        if i != state.player_index:
            if i == 0:
                port = 9000  # Human player
            else:
                port = 8764 + i  # Agents
            
            player_address = f"http://localhost:{port}"
            tasks.append(_send_single_dummy_packet(player_address, dummy_ciphertext))
    
    if tasks:
        await asyncio.gather(*tasks, return_exceptions=True)


async def _send_single_dummy_packet(address: str, ciphertext_b64: str):
    """Helper to send single dummy investigate packet"""
    import httpx
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            await client.post(
                f"{address}/investigate_parallel",
                json={"ciphertext": ciphertext_b64}
            )
    except Exception:
        pass  # Ignore errors silently
