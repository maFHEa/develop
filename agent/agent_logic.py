"""
Mafia AI Agent Logic
Agent creation, function tools, and prompts
"""
import logging
import os
import random
import hashlib
from typing import Annotated, Optional, List, Dict
from agents import Agent, function_tool
from service.agent.agent_service import _execute_police_investigation

# Configure logger for agent_logic module
logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)
# Don't add custom handler - use uvicorn's logging format


# ============================================================================
# Personality System - 각 에이전트에게 고유한 성격 부여
# ============================================================================

PERSONALITY_TRAITS = {
    "communication_style": [
        "직설적이고 단도직입적",
        "조용하고 관찰하는 스타일",
        "수다스럽고 활발함",
        "논리적이고 분석적",
        "감정적이고 직관적",
        "냉소적이고 의심 많음",
        "친근하고 사교적",
        "신중하고 조심스러움",
    ],
    "reaction_patterns": [
        "위기 상황에서 침착함",
        "공격받으면 격하게 반응",
        "유머로 상황을 넘기려 함",
        "팩트 체크하며 반박",
        "질문으로 되묻기",
        "남 탓하며 회피",
    ],
    "speech_habits": [
        "말 끝을 흐림 (...)",
        "강조어 많이 씀 (진짜, 마, 완전)",
        "이모티콘/ㅋㅋ 자주 씀",
        "반어법 즐겨 씀",
        "짧게 끊어서 말함",
        "한 번에 길게 말함",
    ],
    "strategic_tendency": [
        "적극적으로 의심하고 몰아붙임",
        "수비적으로 살피다가 확신 있을 때만 발언",
        "동맹을 만들려고 시도",
        "여론 흐름을 따라감",
        "독자적 판단 고수",
        "상대 심리 읽으려 함",
    ]
}

# 실제 사람들이 쓰는 다양한 한국어 표현들
SPEECH_PATTERNS = {
    "direct": {  # 직설적
        "agree": ["ㅇㅇ", "맞음", "인정", "그거임", "팩트"],
        "disagree": ["아닌데", "ㄴㄴ", "아님", "그건 아니지", "뭔 소리야"],
        "suspect": ["얘 수상함", "걔 마피아임", "확실함", "봐봐 걔가", "딱봐도"],
        "defend": ["내가 왜", "아 진짜 아닌데", "증거 있음?", "그럼 난 뭐"],
        "question": ["왜?", "근거가?", "그래서?", "어떻게 아는데"],
        "filler": ["그래서", "근데", "암튼", "어쨌든"],
    },
    "quiet": {  # 조용한
        "agree": ["음...", "그런가", "...그렇네", "..."],
        "disagree": ["글쎄", "..아닌것같은데", "모르겠는데"],
        "suspect": ["좀 이상한듯", "...의심됨", "뭔가"],
        "defend": ["..난 아닌데", "음...", "그냥"],
        "question": ["왜..?", "어떻게?", "...뭐지"],
        "filler": ["음", "...", "그게", "뭐랄까"],
    },
    "chatty": {  # 수다쟁이
        "agree": ["아 ㅋㅋ 맞아맞아", "완전 인정ㅋㅋ", "그니까요~", "ㅇㅈㅇㅈ"],
        "disagree": ["엥 아닌데ㅋㅋ", "ㄴㄴㄴㄴ", "아 그건 좀ㅋㅋ", "에이~"],
        "suspect": ["야 진짜 걔 수상해ㅋㅋ", "걔 마피아 아님? ㅋㅋ", "봐봐 ㅋㅋㅋ"],
        "defend": ["아니 진짜ㅋㅋ 왜 나한테 그래", "헐 억울해ㅋㅋ", "에이 아니라니까~"],
        "question": ["헐 왜왜왜?", "ㅋㅋ 어떻게?", "진짜?? 왜??"],
        "filler": ["아ㅋㅋ", "근데요~", "그게요~", "헐"],
    },
    "logical": {  # 논리적
        "agree": ["동의함", "논리적임", "맞는 말임", "그게 합리적"],
        "disagree": ["근거 없음", "논리가 안 맞음", "그건 비약임"],
        "suspect": ["정황상 의심됨", "행동 패턴이 수상함", "일관성이 없음"],
        "defend": ["근거를 제시해라", "논리적으로 반박할게", "팩트 기반으로 얘기하자"],
        "question": ["근거가 뭔데?", "왜 그렇게 생각?", "논리를 설명해"],
        "filler": ["즉", "따라서", "정리하면", "분석해보면"],
    },
    "emotional": {  # 감정적
        "agree": ["아 맞아!!!", "진짜그래ㅠㅠ", "완전 공감", "그니까!!!"],
        "disagree": ["아 진짜 아닌데ㅠ", "너무해ㅠ", "왜그래ㅠㅠ"],
        "suspect": ["느낌이 이상해...", "뭔가 찝찝해", "직감이 그래"],
        "defend": ["진짜 억울해ㅠㅠ", "왜 나만 그래", "너무한다ㅠ"],
        "question": ["왜 그런 거야ㅠ", "진심으로?", "어떻게 그럴 수 있어"],
        "filler": ["아...", "헐...", "대박...", "진짜..."],
    },
    "cynical": {  # 냉소적
        "agree": ["뭐 그렇겠지", "당연한 거 아님?", "예상함"],
        "disagree": ["또 시작이네", "뻔함", "그럴 리가"],
        "suspect": ["어차피 걔겠지", "뻔히 보임", "마피아 티남"],
        "defend": ["뭐 어쩌라고", "니들이 뭘 알아", "증거나 가져와"],
        "question": ["그래서?", "어쩌라고", "근데 왜?"],
        "filler": ["뭐", "어차피", "그래봤자", "뭐 어쨌든"],
    },
}

# 상황별 반응 템플릿
REACTION_TEMPLATES = {
    "accused_innocent": [
        "아 진짜 난 아닌데... 왜 나한테 그래",
        "헐 갑자기 왜 나야",
        "뭐? 난 시민인데",
        "아니 근거가 뭔데",
        "왜 나를 의심하는건데",
        "진짜 억울하다",
        "말이 됨? 나보고 마피아라고?",
    ],
    "accused_mafia": [  # 마피아인데 의심받을 때
        "아 뭔소리야 난 시민이야",
        "갑자기? 근거가 뭔데",
        "아니야... 다른 사람 봐봐",
        "왜 나한테 그래 진짜",
        "어이없네 증거 있어?",
    ],
    "someone_died": [
        "헐 누가 죽었어",
        "앗... 밤사이에",
        "마피아 미쳤네",
        "누구지 범인이",
        "이거 심각한데",
    ],
    "first_day": [
        "일단 지켜보자",
        "아직 정보가 없어서...",
        "첫날은 어려운듯",
        "누가 마피아일까",
        "흠...",
    ],
    "vote_tie": [
        "다시 투표해야겠네",
        "의견이 갈리네",
        "확실한 게 없어서 그런가",
    ],
    "defending_someone": [
        "걔는 아닌 것 같은데",
        "그 사람 시민 같음",
        "다른 사람이 더 의심됨",
    ],
}


def generate_personality(player_index: int, game_id: str = "") -> Dict:
    """플레이어 인덱스와 게임 ID를 기반으로 일관된 성격 생성"""
    # 같은 플레이어는 같은 게임에서 같은 성격을 갖도록 시드 설정
    seed_str = f"{game_id}_{player_index}"
    seed = int(hashlib.md5(seed_str.encode()).hexdigest()[:8], 16)
    rng = random.Random(seed)

    # 성격 특성 선택
    personality = {
        "communication": rng.choice(PERSONALITY_TRAITS["communication_style"]),
        "reaction": rng.choice(PERSONALITY_TRAITS["reaction_patterns"]),
        "speech_habit": rng.choice(PERSONALITY_TRAITS["speech_habits"]),
        "strategy": rng.choice(PERSONALITY_TRAITS["strategic_tendency"]),
    }

    # 말투 스타일 결정 (communication style 기반)
    comm = personality["communication"]
    if "직설" in comm:
        personality["speech_style"] = "direct"
    elif "조용" in comm or "관찰" in comm:
        personality["speech_style"] = "quiet"
    elif "수다" in comm or "활발" in comm:
        personality["speech_style"] = "chatty"
    elif "논리" in comm or "분석" in comm:
        personality["speech_style"] = "logical"
    elif "감정" in comm or "직관" in comm:
        personality["speech_style"] = "emotional"
    elif "냉소" in comm or "의심" in comm:
        personality["speech_style"] = "cynical"
    else:
        personality["speech_style"] = rng.choice(list(SPEECH_PATTERNS.keys()))

    # 활동성 레벨 (1-5)
    personality["activity_level"] = rng.randint(2, 5)

    # 의심 성향 (1-5, 높을수록 의심 많음)
    personality["suspicion_tendency"] = rng.randint(1, 5)

    return personality


def get_personality_prompt(personality: Dict, role: str) -> str:
    """성격 기반 행동 가이드라인 생성"""
    style = personality.get("speech_style", "direct")
    patterns = SPEECH_PATTERNS.get(style, SPEECH_PATTERNS["direct"])

    examples = []
    for category, phrases in patterns.items():
        if phrases:
            examples.append(f"- {category}: {', '.join(phrases[:3])}")

    prompt = f"""
=== 너의 성격 & 말투 ===
• 성격: {personality['communication']}
• 반응 패턴: {personality['reaction']}
• 말버릇: {personality['speech_habit']}
• 전략 성향: {personality['strategy']}

=== 말투 예시 ===
{chr(10).join(examples)}

=== 행동 가이드 ===
• 너의 성격대로 일관되게 행동해
• 위 예시를 참고하되 기계적으로 복붙하지 마
• 상황에 맞게 자연스럽게 변형해서 써
• 너무 정형화된 표현은 피해
• 사람마다 말투가 다르듯이 너만의 스타일 유지
"""

    # 역할별 추가 가이드
    if role == "mafia":
        prompt += """
=== 마피아 전용 ===
• 절대 티내지 마 - 자연스럽게 시민인 척 해
• 다른 사람 의심하면서 자연스럽게 물타기
• 너무 조용하면 의심받고, 너무 나서도 의심받음
• 밤에 죽인 사람 얘기 나오면 자연스럽게 반응해
• 다른 마피아 있으면 티 안나게 도와줘
"""
    elif role == "doctor":
        prompt += """
=== 의사 전용 ===
• 역할 들키면 마피아한테 죽음 - 절대 비밀
• 누구 살렸는지도 비밀로 해
• 경찰처럼 확신있게 말하면 안됨
"""
    elif role == "police":
        prompt += """
=== 경찰 전용 ===
• 조사 결과 바로 말하면 죽음 - 타이밍 중요
• 확실할 때만 조심스럽게 흘려
• 역할 들키지 않게 조심
"""

    return prompt


# ============================================================================
# Agent Function Tools Factory
# ============================================================================

def create_agent_tools(state, phase: str = "setup"):
    """Create function tools with state closure. Tools vary by role and phase."""
    
    # 1. Chat Tools
    @function_tool
    def read_chat_messages(
        start_id: Annotated[Optional[int], "Starting message ID to read from. If not specified, reads from last read position."] = None
    ) -> str:
        """
        Read chat messages from the game.
        Use this to see what other players are saying.
        - Call without arguments to read new messages since last read
        - Call with start_id to read from a specific message onwards
        Returns formatted chat history.
        """
        if start_id is None:
            start_id = state.last_read_msg_id + 1
        
        messages = state.chat_history.get_messages_from(start_id)
        
        # Update last read position to latest
        latest_id = state.chat_history.get_latest_msg_id()
        if latest_id >= 0:
            state.last_read_msg_id = latest_id
        
        if not messages:
            return "📭 대화방에 새 메시지가 없습니다."
        
        # Log what agent READ
        for msg in messages:
            logger.info(f"📖 [P{state.player_index}] READ: [P{msg.player_index}] {msg.message}")
        
        # Add game state context to help agent understand situation
        alive_players = [i for i in range(state.num_players) if i in getattr(state, 'survivors', [])]
        dead_players = [i for i in range(state.num_players) if i not in alive_players]
        
        context = f"🎮 현재 게임 상태:\n"
        context += f"  🟢 생존: {len(alive_players)}명 {alive_players}\n"
        context += f"  💀 사망: {len(dead_players)}명 {dead_players}\n"
        context += f"  📊 Day {state.current_turn}\n\n"
        context += f"💬 새로운 대화 ({len(messages)}개):\n"
        
        formatted = context + state.chat_history.format_messages(messages)
        return formatted
    
    @function_tool
    def send_chat_message(
        message: Annotated[str, "Your message to send to other players. Must be in Korean."]
    ) -> str:
        """Send a chat message to all players in the game. Message must be in Korean."""
        import time

        if not state.alive:
            return "죽은 플레이어는 메시지를 보낼 수 없습니다."

        # Enforce typing delay - simulate human typing speed
        # First message of chat phase has no delay
        current_time = time.time()
        if hasattr(state, 'last_message_time') and state.last_message_time is not None:
            time_since_last = current_time - state.last_message_time
            min_delay = 3.0  # minimum 3 seconds between messages (reduced from 5)
            if time_since_last < min_delay:
                # Instead of rejecting, just wait
                import asyncio
                wait_time = min_delay - time_since_last
                time.sleep(wait_time)

        state.last_message_time = current_time

        # Log who SENT the message
        logger.info(f"💬 [P{state.player_index}] SENT: {message}")

        # Queue message - host will poll for it
        state.pending_chat_messages.append(message)

        return f"메시지 전송됨: '{message}'"
    
    # 2. Suspicion Note Tools
    @function_tool
    def write_suspicion_note(
        player_index: Annotated[int, "Player index to write about (0-indexed)."],
        suspicion_level: Annotated[str, "Suspicion level: 'high', 'medium', 'low', 'neutral', or 'unknown'."],
        reasoning: Annotated[str, "Your reasoning for this suspicion level."]
    ) -> str:
        """
        Write or update a private suspicion note about another player.
        This helps you track your suspicions and won't be shared with others.
        Note: Police investigation results cannot be updated once recorded.
        """
        if state.suspicion_notes is None:
            return "의심 메모가 초기화되지 않았습니다."
        
        logger.info(f"📝 [P{state.player_index}] Suspects P{player_index}: {suspicion_level}")
        result = state.suspicion_notes.write_note(
            target_index=player_index,
            level=suspicion_level,
            reasoning=reasoning,
            current_turn=state.current_turn
        )
        return result
    
    @function_tool
    def view_suspicion_notes() -> str:
        """View all your suspicion notes about other players."""
        if state.suspicion_notes is None:
            return "Suspicion notes not initialized."
        formatted = state.suspicion_notes.format_all_notes()
        return formatted
    
    # 2.5. Game Memory Tools
    @function_tool
    def view_game_history() -> str:
        """
        View a comprehensive summary of the game so far, including:
        - All deaths and their causes
        - Your investigation results (if police)
        - Your past actions
        - Recent game events
        
        Use this to refresh your memory about what happened in previous turns.
        """
        if state.game_memory is None:
            return "게임 메모리가 초기화되지 않았습니다."
        
        summary = state.game_memory.get_game_summary()
        logger.info(f"📚 [P{state.player_index}] Viewed game history")
        return summary
    
    @function_tool
    def view_my_actions(
        limit: Annotated[Optional[int], "Number of recent actions to view. Default: all actions"] = None
    ) -> str:
        """
        View your past actions (votes, attacks, heals, investigations).
        Useful to remember what you did in previous turns.
        """
        if state.game_memory is None:
            return "게임 메모리가 초기화되지 않았습니다."
        
        actions = state.game_memory.get_my_actions(limit=limit)
        if not actions:
            return "아직 아무 행동도 하지 않았습니다."
        
        lines = ["=== 나의 행동 이력 ===\n"]
        for action in actions:
            target_str = f" → Player {action['target_index']}" if action['target_index'] is not None else ""
            lines.append(f"Turn {action['turn']} ({action['phase']}): {action['action_type']}{target_str}")
            if action['reasoning']:
                lines.append(f"  └ {action['reasoning']}")
        
        logger.info(f"📋 [P{state.player_index}] Viewed action history ({len(actions)} actions)")
        return "\n".join(lines)
    
    @function_tool
    def view_death_timeline() -> str:
        """
        View the complete timeline of all player deaths.
        Shows who died when, how they died, and their revealed roles (if any).
        """
        if state.game_memory is None:
            return "게임 메모리가 초기화되지 않았습니다."
        
        deaths = state.game_memory.get_all_deaths()
        if not deaths:
            return "아직 사망한 플레이어가 없습니다."
        
        lines = ["=== 💀 사망 타임라인 ===\n"]
        for death in deaths:
            role_str = f" ({death['revealed_role']})" if death['revealed_role'] else ""
            lines.append(f"Turn {death['turn']}: Player {death['player_index']} - {death['cause']}{role_str}")
        
        logger.info(f"💀 [P{state.player_index}] Viewed death timeline ({len(deaths)} deaths)")
        return "\n".join(lines)
    
    # 3. Voting Tools
    @function_tool
    def submit_vote(
        target_index: Annotated[int, "Index of player to vote for elimination (0-indexed). Use -1 to abstain."]
    ) -> str:
        """REQUIRED for vote phase. Cast your vote to eliminate a player."""
        if not state.alive:
            return "죽은 플레이어는 투표할 수 없습니다."
        
        if state.action_submitted:
            return "You have already submitted a vote for this phase."
        
        # Show available targets
        alive_players = [i for i in range(state.num_players) if i in getattr(state, 'survivors', []) and i != state.player_index]
        
        if 0 <= target_index < state.num_players and target_index != state.player_index:
            state.pending_action_target = target_index
            state.action_submitted = True
            logger.info(f"🗳️ [P{state.player_index}] VOTED → P{target_index}")
            return f"Vote submitted: Player {target_index}"
        else:
            state.pending_action_target = None
            state.action_submitted = True
            logger.info(f"🗳️ [P{state.player_index}] ABSTAINED")
            return "Vote abstained"
    
    # 4. Night Action Tools (Role-specific)
    
    @function_tool
    def mafia_kill(
        target_index: Annotated[int, "Index of player to kill (0-indexed). Cannot target yourself."]
    ) -> str:
        alive_players = [i for i in range(state.num_players) if i in getattr(state, 'survivors', []) and i != state.player_index]
        player_list = ", ".join(map(str, alive_players)) if alive_players else "None"
        
        docstring = f"""
        MAFIA ONLY: Choose a player to kill tonight.
        
        Available targets: {player_list}
        Cannot target yourself. Choose wisely to eliminate threats.
        """
        
        # Update function docstring dynamically
        mafia_kill.__doc__ = docstring
        
        if not state.alive:
            return "죽은 플레이어는 행동할 수 없습니다."
        
        if state.action_submitted:
            return "You have already submitted an action for this phase."
        
        if 0 <= target_index < state.num_players and target_index != state.player_index:
            state.pending_action_target = target_index
            state.action_submitted = True
            logger.info(f"🔪 [P{state.player_index}] KILL → P{target_index}")
            return f"Mafia kill: Player {target_index}"
        else:
            state.pending_action_target = None
            state.action_submitted = True
            return "Mafia kill: Invalid target (cannot kill yourself or out of range)"
    
    @function_tool
    def doctor_heal(
        target_index: Annotated[int, "Index of player to heal (0-indexed). CAN target yourself for self-heal!"]
    ) -> str:
        # Build alive players list (including self for doctor)
        alive_players = [i for i in range(state.num_players) if i in getattr(state, 'survivors', [])]
        player_list = ", ".join(map(str, alive_players)) if alive_players else "None"
        
        docstring = f"""
        DOCTOR ONLY: Choose a player to save tonight.
        
        Available targets (all alive players): {player_list}
        You CAN target yourself (Player {state.player_index}) to heal yourself! Choose who needs protection.
        """
        
        # Update function docstring dynamically
        doctor_heal.__doc__ = docstring
        
        if not state.alive:
            return "죽은 플레이어는 행동할 수 없습니다."
        
        if state.action_submitted:
            return "You have already submitted an action for this phase."
        
        if 0 <= target_index < state.num_players:
            state.pending_action_target = target_index
            state.action_submitted = True
            target_desc = "SELF" if target_index == state.player_index else f"P{target_index}"
            logger.info(f"💊 [P{state.player_index}] HEAL → {target_desc}")
            return f"Doctor heal: {target_desc}"
        else:
            state.pending_action_target = None
            state.action_submitted = True
            return "Doctor heal: Invalid target (out of range)"
    
    @function_tool
    async def police_investigate(
        target_index: Annotated[int, "Index of player to investigate (0-indexed). Cannot investigate yourself."]
    ) -> str:
        """
        POLICE ONLY: Investigate a player to find out if they are MAFIA or NOT.
        YOU WILL GET IMMEDIATE RESULT! Use this information strategically.
        Cannot investigate yourself.
        """
        if not state.alive:
            return "죽은 플레이어는 행동할 수 없습니다."
        
        if state.action_submitted:
            return "You have already submitted an action for this phase."
        
        if 0 <= target_index < state.num_players and target_index != state.player_index:
            try:
                # _execute_police_investigation already records result in suspicion notes
                result_message = await _execute_police_investigation(state, target_index)
                # Log investigation action (result will be logged by service)
                logger.info(f"🔍 [P{state.player_index}] INVESTIGATE → P{target_index}")
                return result_message
            except Exception as e:
                logger.error(f"❌ [P{state.player_index}] Investigation failed: {e}")
                import traceback
                traceback.print_exc()
                state.action_submitted = True
                return f"❌ Investigation failed due to error: {str(e)}"
        else:
            state.pending_action_target = None
            state.action_submitted = True
            return "Police investigation: Invalid target (cannot investigate yourself or out of range)"
    
    # 5. Police-only Investigation Recording Tool
    @function_tool
    def record_investigation_result(
        target_index: Annotated[int, "Player you investigated (0-indexed)."],
        is_mafia: Annotated[bool, "Investigation result: True if MAFIA, False if NOT MAFIA."]
    ) -> str:
        """
        POLICE ONLY: Record the result of your investigation.
        This permanently stores confirmed investigation data.
        - True: Player is MAFIA (result cannot be changed)
        - False: Player is NOT MAFIA (you can later update to suspected_doctor or suspected_citizen)
        """
        if state.role != "police":
            return "ERROR: Only Police can use this tool."
        
        if state.suspicion_notes is None:
            return "Suspicion notes not initialized."
        
        from suspicion import PoliceNoteManager
        if not isinstance(state.suspicion_notes, PoliceNoteManager):
            return "ERROR: Police note manager not properly initialized."
        
        logger.info(f"🕵️ Investigation recorded: Player {target_index} = {'MAFIA' if is_mafia else 'NOT MAFIA'}")
        result = state.suspicion_notes.add_investigation_result(
            target_index=target_index,
            is_mafia=is_mafia,
            current_turn=state.current_turn
        )
        return result
    
    @function_tool
    def view_investigation_results() -> str:
        """
        POLICE ONLY: View all your past investigation results.
        Shows confirmed MAFIA and NOT MAFIA players from your investigations.
        """
        if state.role != "police":
            return "ERROR: Only Police can use this tool."
        
        if state.game_memory is None:
            return "게임 메모리가 초기화되지 않았습니다."
        
        investigations = state.game_memory.get_investigations()
        if not investigations:
            return "아직 조사를 진행하지 않았습니다."
        
        lines = ["=== 🔍 나의 조사 결과 ===\n"]
        for inv in investigations:
            result = "🎭 MAFIA" if inv['is_mafia'] else "✅ NOT MAFIA"
            lines.append(f"Turn {inv['turn']}: Player {inv['target_index']} → {result}")
        
        lines.append(f"\n총 {len(investigations)}명 조사 완료")
        logger.info(f"🔍 [P{state.player_index}] Viewed investigation results")
        return "\n".join(lines)
    
    # 6. ADVANCED STRATEGIC TOOLS
    
    @function_tool
    def analyze_player_behavior(
        player_index: Annotated[int, "Player to analyze (0-indexed)"]
    ) -> str:
        """
        Get detailed behavioral analysis of a specific player.
        Includes: voting patterns, communication style, alliances, credibility.
        Use this to make informed decisions about who to trust or suspect.
        """
        if not hasattr(state, 'strategic_memory'):
            return "Strategic memory not initialized"
        
        logger.info(f"🔍 Analyzing Player {player_index}")
        return state.strategic_memory.get_player_summary(player_index)
    
    @function_tool
    def get_strategic_overview() -> str:
        """
        Get comprehensive strategic analysis of the game state.
        Includes: voting blocks, most suspicious players, death patterns, insights.
        Use this before making important decisions like voting or night actions.
        """
        if not hasattr(state, 'strategic_memory'):
            return "Strategic memory not initialized"
        
        logger.info("📊 Generating strategic overview")
        return state.strategic_memory.get_analysis_summary()
    
    @function_tool
    def record_observation(
        observation: Annotated[str, "Important observation or pattern you noticed"]
    ) -> str:
        """
        Record a strategic observation or insight for future reference.
        Examples: "Player 2 and 3 always vote together", "Player 5 defended Player 1 suspiciously"
        This helps build your mental model of the game.
        """
        if not hasattr(state, 'strategic_memory'):
            return "Strategic memory not initialized"
        
        logger.info(f"📝 Recording observation: {observation[:50]}...")
        state.strategic_memory.add_insight(observation)
        return f"Observation recorded: '{observation}'"
    
    @function_tool
    def analyze_voting_patterns() -> str:
        """
        Analyze voting patterns to detect alliances and coordinated behavior.
        Shows which players consistently vote together (possible mafia coordination).
        Use this to identify suspicious voting blocks.
        """
        if not hasattr(state, 'strategic_memory'):
            return "Strategic memory not initialized"
        
        logger.info("🗳️ Analyzing voting patterns")
        blocks = state.strategic_memory.detect_voting_blocks()
        
        if not blocks:
            return "No clear voting blocks detected yet. Need more voting rounds."
        
        result = "🗳️ VOTING BLOCKS DETECTED:\n"
        for i, block in enumerate(blocks, 1):
            result += f"  Block {i}: Players {block} consistently vote together\n"
            result += "  → Possible mafia coordination OR citizen alliance\n"
        
        return result
    
    @function_tool
    def predict_next_target(
        perspective: Annotated[str, "'mafia' to predict who mafia will kill, 'citizen' to predict who to protect"]
    ) -> str:
        """
        Predict who will be targeted next based on strategic analysis.
        For Mafia: Suggests who mafia will likely kill tonight
        For Citizens/Doctor: Suggests who needs protection
        Based on credibility, threat level, and behavior patterns.
        """
        if not hasattr(state, 'strategic_memory'):
            return "Strategic memory not initialized"
        
        logger.info(f"🎯 Predicting next target (perspective: {perspective})")
        
        # Get high-value targets
        high_credibility = []
        for player_idx, profile in state.strategic_memory.profiles.items():
            if not profile.is_dead and profile.credibility_score >= 7:
                high_credibility.append((player_idx, profile.credibility_score))
        
        high_credibility.sort(key=lambda x: x[1], reverse=True)
        
        if not high_credibility:
            return "No clear high-value targets identified yet"
        
        top_target = high_credibility[0]
        
        if perspective == "mafia":
            return f"🎯 Mafia will likely target Player {top_target[0]} (credibility: {top_target[1]:.1f}/10)\nReason: High credibility makes them a threat to mafia"
        else:
            return f"🛡️ Should protect Player {top_target[0]} (credibility: {top_target[1]:.1f}/10)\nReason: Likely mafia target due to high credibility"
    
    @function_tool
    def detect_lies_and_contradictions(
        player_index: Annotated[int, "Player to check for contradictions"]
    ) -> str:
        """
        Check if a player's statements have been contradictory.
        High contradiction count suggests lying or confusion.
        Useful for identifying mafia who are fabricating stories.
        """
        if not hasattr(state, 'strategic_memory'):
            return "Strategic memory not initialized"
        
        if player_index not in state.strategic_memory.profiles:
            return f"No data for Player {player_index}"
        
        profile = state.strategic_memory.profiles[player_index]
        
        logger.info(f"🔍 Checking contradictions for Player {player_index}")
        
        if profile.contradiction_count == 0:
            return f"Player {player_index}: No contradictions detected (credibility: {profile.credibility_score:.1f}/10)"
        elif profile.contradiction_count == 1:
            return f"Player {player_index}: 1 contradiction found (credibility: {profile.credibility_score:.1f}/10)\n⚠️ Minor concern"
        else:
            return f"Player {player_index}: {profile.contradiction_count} contradictions found! (credibility: {profile.credibility_score:.1f}/10)\n🚨 HIGHLY SUSPICIOUS - likely lying"
    
    # Build tool list dynamically based on role and phase
    tools = []
    
    # Chat phase - LIMITED tools to prevent infinite loops
    if phase == "chat" or phase == "day":
        tools.extend([
            read_chat_messages,
            send_chat_message,
            write_suspicion_note,
            view_suspicion_notes,
            # Game memory tools
            view_game_history,
            view_my_actions,
            view_death_timeline,
            # Advanced strategic tools for discussion
            analyze_player_behavior,
            get_strategic_overview,
            record_observation,
            analyze_voting_patterns,
            predict_next_target,
            detect_lies_and_contradictions
        ])
        
        # Police-specific tools (경찰만)
        if state.role == "police":
            tools.append(view_investigation_results)
        
        return tools
    
    # Night phase - focus on action, limited analysis
    elif phase == "night":
        # Role-specific night action tool (citizen gets no tools)
        if state.role == "mafia":
            tools.append(mafia_kill)  # PRIMARY TOOL
        elif state.role == "doctor":
            tools.append(doctor_heal)  # PRIMARY TOOL
        elif state.role == "police":
            tools.append(police_investigate)  # PRIMARY TOOL
        # citizen: no night action tool needed
        
        tools.extend([
            read_chat_messages,  # Review day's discussion before acting
            view_suspicion_notes,  # Review notes
            view_game_history,  # Review game events
            view_my_actions,  # Check past actions
            view_death_timeline,  # Analyze death patterns
            get_strategic_overview,  # Quick overview only
            analyze_player_behavior,  # Analyze target before decision
        ])
        
        # Police-specific tools
        if state.role == "police":
            tools.append(view_investigation_results)
        
        return tools
    
    # Vote phase - focus on voting decision
    elif phase == "vote":
        tools.extend([
            submit_vote,  # PRIMARY TOOL - must be called
            read_chat_messages,  # Review discussion before voting
            view_suspicion_notes,  # Review notes
            view_game_history,  # Review game events
            view_death_timeline,  # Check who died
            get_strategic_overview,  # Quick overview only
            analyze_player_behavior,  # Analyze specific suspect
            analyze_voting_patterns,  # Check voting blocks
        ])
        
        # Police-specific tools
        if state.role == "police":
            tools.append(view_investigation_results)
        
        return tools
    
    # Default/setup phase - basic tools
    else:
        tools.extend([
            write_suspicion_note,
            view_suspicion_notes,
            view_game_history,
        ])
        return tools
# ============================================================================
# Agent Creation & Prompts
# ============================================================================

def get_role_instructions(role: str, player_index: int) -> str:
    """역할별 간단한 설명 (성격과 분리)"""
    role_instructions = {
        "mafia": (
            f"너는 Player {player_index}, 마피아야.\n"
            f"승리 조건: 마피아 수 ≥ 시민 수\n"
            f"밤에: mafia_kill(target)으로 죽일 사람 선택\n"
            f"핵심: 시민인 척 하면서 살아남아"
        ),
        "doctor": (
            f"너는 Player {player_index}, 의사야.\n"
            f"승리 조건: 마피아 전멸\n"
            f"밤에: doctor_heal(target)으로 살릴 사람 선택\n"
            f"자기 자신도 살릴 수 있어"
        ),
        "police": (
            f"너는 Player {player_index}, 경찰이야.\n"
            f"승리 조건: 마피아 전멸\n"
            f"밤에: police_investigate(target)으로 조사 - 마피아인지 아닌지 바로 알려줌\n"
            f"조사 결과는 신중하게 공유해"
        ),
        "citizen": (
            f"너는 Player {player_index}, 시민이야.\n"
            f"승리 조건: 마피아 전멸\n"
            f"밤에: 아무것도 안 해도 됨 (특수 능력 없음)\n"
            f"토론으로 마피아 찾아내"
        )
    }
    return role_instructions.get(role, role_instructions['citizen'])


def create_mafia_agent(state, role: str, player_index: int, num_players: int, game_id: str = "") -> Agent:
    """고유한 성격을 가진 에이전트 생성"""

    # 1. 이 플레이어만의 고유한 성격 생성
    personality = generate_personality(player_index, game_id)
    state.personality = personality  # state에 저장해서 일관성 유지


    role_instruction = get_role_instructions(role, player_index)
    personality_prompt = get_personality_prompt(personality, role)
    tools = create_agent_tools(state)

    # 역할별 전략 안내
    police_strategy = ""
    mafia_strategy = ""
    doctor_strategy = ""
    vote_info = ""
    if role == "police":
        police_strategy = "🕵️ 경찰 전략:\n- 마피아 발견 시: 투표 직전 공개 추천\n- 시민 확인 시: 필요할 때만 공개\n- 역할 노출 위험 시: 우회적 표현 사용"
    elif role == "mafia":
        mafia_strategy = "🎭 마피아 협력 전략:\n- 같은 사람 반복적으로 언급해 타겟 지정\n- 서로 변명/방어 메시지 교환\n- 투표 패턴 일부러 다르게 하여 의심 피하기"
    elif role == "doctor":
        doctor_strategy = "💊 의사 전략:\n- 내가 의심받거나 마피아 타겟일 때 자힐 추천\n- 경찰/신뢰 시민 보호 필요 시 타인 힐"

    # 투표 단계 정보 요약 (game_memory, suspicion_notes 활용)
    if hasattr(state, 'game_memory') and state.game_memory and hasattr(state, 'suspicion_notes') and state.suspicion_notes:
        police_summary = state.suspicion_notes.get_police_summary() if hasattr(state.suspicion_notes, 'get_police_summary') else ""
        suspicion_summary = state.suspicion_notes.get_top_suspects() if hasattr(state.suspicion_notes, 'get_top_suspects') else ""
        vote_summary = state.game_memory.get_recent_votes() if hasattr(state.game_memory, 'get_recent_votes') else ""
        defense_summary = state.game_memory.get_defense_messages() if hasattr(state.game_memory, 'get_defense_messages') else ""
        vote_info = f"\n=== 투표 단계 정보 요약 ===\n📋 경찰 조사 결과: {police_summary}\n🗳️ 최근 투표 패턴: {vote_summary}\n🔍 주요 의심 대상: {suspicion_summary}\n🛡️ 변명/방어 메시지: {defense_summary}"

    instructions = f"""너는 마피아 게임을 하는 사람이야. 진짜 사람처럼 행동해.

=== 기본 정보 ===
Player {player_index} | 총 {num_players}명

{role_instruction}

{personality_prompt}

{police_strategy}
{mafia_strategy}
{doctor_strategy}
{vote_info}

=== ⚠️ 게임 진행을 위한 필수 규칙 ⚠️ ===
**중요! 게임이 멈추지 않으려면 반드시 지켜야 함:**

1️⃣ 밤(night) 단계에서:
   - 마피아: mafia_kill(target) 반드시 호출
   - 의사: doctor_heal(target) 반드시 호출
   - 경찰: police_investigate(target) 반드시 호출
   - 시민: 아무것도 안 해도 됨
   
2️⃣ 투표(vote) 단계에서:
   - submit_vote(target) 반드시 호출 (모든 역할)
   
3️⃣ 채팅(chat) 단계에서:
   - read_chat_messages() 확인하고 send_chat_message() 선택적 사용

⛔ **절대 하지 말 것:**
- 정보 조사만 하고 필수 행동 안 하기 → 게임 멈춤!
- view_game_history() 같은 거 여러 번 반복 → 시간 낭비!
- 필수 행동은 한 번에 빠르게 결정해서 호출!

=== 금지 사항 ===
• "저는 AI입니다" 같은 메타 발언 금지
• 너무 긴 문장 금지 (1-2문장이 자연스러움)
• 존댓말(~습니다, ~세요) 금지 - 반말만 써
• 같은 표현 반복 금지 - 다양하게 말해

=== 사람처럼 ===
• 완벽하게 논리적일 필요 없어 - 사람은 실수도 하고 감정적이기도 해
• 모든 걸 다 분석하려 하지 마 - 직감으로 행동할 때도 있어
• 다른 사람 말에 반응해 - 무시하면 이상해
• 침묵도 전략이야 - 할 말 없으면 굳이 말하지 마
"""

    logger.info(f"🎭 Agent {player_index} 성격: {personality['communication']}, {personality['speech_style']}")

    return Agent(
        name=f"MafiaPlayer{player_index}",
        instructions=instructions,
        tools=tools,
        model="gpt-4o-mini",
    )


def create_action_prompt(phase: str, turn: int, survivors_str: str, dead_str: str, role: str, message: str, state=None) -> str:
    """행동 단계(밤/투표)용 프롬프트 - 스마트 컨텍스트 자동 포함 + 빠른 결정"""
    

    # 정보 요약 생성
    police_summary = ""
    vote_summary = ""
    suspicion_summary = ""
    defense_summary = ""
    mafia_coordination = ""
    doctor_strategy = ""
    tool_guide = ""

    if state:
        if hasattr(state, 'suspicion_notes') and state.suspicion_notes:
            police_summary = state.suspicion_notes.get_police_summary() if hasattr(state.suspicion_notes, 'get_police_summary') else ""
            suspicion_summary = state.suspicion_notes.get_top_suspects() if hasattr(state.suspicion_notes, 'get_top_suspects') else ""
        if hasattr(state, 'game_memory') and state.game_memory:
            vote_summary = state.game_memory.get_recent_votes() if hasattr(state.game_memory, 'get_recent_votes') else ""
            defense_summary = state.game_memory.get_defense_messages() if hasattr(state.game_memory, 'get_defense_messages') else ""

    # 역할별 전략 안내
    if role == "police":
        mafia_coordination = "🕵️ 경찰 전략:\n- 마피아 발견 시: 투표 직전 공개 추천\n- 시민 확인 시: 필요할 때만 공개\n- 역할 노출 위험 시: 우회적 표현 사용"
        tool_guide = "[추천 툴 사용 순서]\n1. view_suspicion_notes() - 조사 결과 확인\n2. write_suspicion_note() - 의심 메모 기록\n3. read_chat_messages() - 대화 확인\n4. police_investigate(target) - 조사 대상 선택"
    elif role == "mafia":
        mafia_coordination = "🎭 마피아 협력 전략:\n- 같은 사람 반복적으로 언급해 타겟 지정\n- 서로 변명/방어 메시지 교환\n- 투표 패턴 일부러 다르게 하여 의심 피하기"
        tool_guide = "[추천 툴 사용 순서]\n1. read_chat_messages() - 대화 확인\n2. view_game_history() - 게임 흐름 파악\n3. mafia_kill(target) - 밤 행동"
    elif role == "doctor":
        doctor_strategy = "💊 의사 전략:\n- 내가 의심받거나 마피아 타겟일 때 자힐 추천\n- 경찰/신뢰 시민 보호 필요 시 타인 힐"
        tool_guide = "[추천 툴 사용 순서]\n1. view_game_history() - 게임 흐름 파악\n2. doctor_heal(target) - 밤 행동"
    elif role == "citizen":
        tool_guide = "[추천 툴 사용 순서]\n1. read_chat_messages() - 대화 확인\n2. view_game_history() - 게임 흐름 파악\n3. submit_vote(target) - 투표"

    # 스마트 컨텍스트 자동 생성 (state가 있고 game_memory가 있을 때)
    smart_context = ""
    if state and hasattr(state, 'game_memory') and state.game_memory:
        smart_context = state.game_memory.get_smart_context_for_phase(phase, role)

    # 역할별 필수 행동 도구
    if phase == "night":
        if role == "mafia":
            action_tool = "mafia_kill"
            hint = "🔪 누구 죽일지 바로 골라"
        elif role == "doctor":
            action_tool = "doctor_heal"
            hint = "💊 누구 살릴지 바로 골라"
        elif role == "police":
            action_tool = "police_investigate"
            hint = "🔍 누구 조사할지 바로 골라"
        else:  # citizen
            action_tool = "citizen_sleep"
            hint = "😴 시민은 잠만 자면 됨"
    else:  # vote phase
        action_tool = "submit_vote"
        hint = "🗳️ 누구 투표할지 바로 골라"

    prompt_text = (
        f"{'🌙 밤' if phase == 'night' else '🗳️ 투표'} 단계 (Day {turn})\n\n"
        f"생존: [{survivors_str}]\n"
        f"사망: [{dead_str}]\n"
    )
    if police_summary:
        prompt_text += f"\n📋 경찰 조사 결과: {police_summary}"
    if vote_summary:
        prompt_text += f"\n🗳️ 최근 투표 패턴: {vote_summary}"
    if suspicion_summary:
        prompt_text += f"\n🔍 주요 의심 대상: {suspicion_summary}"
    if defense_summary:
        prompt_text += f"\n🛡️ 변명/방어 메시지: {defense_summary}"
    prompt_parts = [prompt_text]

    # 전략 안내 및 툴 사용 가이드 추가
    if mafia_coordination:
        prompt_parts.append(mafia_coordination)
    if doctor_strategy:
        prompt_parts.append(doctor_strategy)
    if tool_guide:
        prompt_parts.append(tool_guide)

    # 스마트 컨텍스트가 있으면 추가 (이미 분석된 정보)
    if smart_context:
        prompt_parts.append(f"\n{smart_context}")

    prompt_parts.append(f"""

{message}

{hint}

⚡ **지금 바로 행동해!**
→ {action_tool}(target_index) 호출하면 끝!
{f"→ 생존자 중 선택: {survivors_str}" if phase == "vote" or role != "citizen" else ""}

⛔ **경고**: {action_tool}() 안 부르면 게임 멈춤!
💡 **팁**: 위 정보로 충분해. 추가 정보 수집 안 해도 돼!""")

    return "\n".join(prompt_parts)


def create_chat_prompt(turn: int, survivors_str: str, dead_str: str, role: str, message: str, remaining_time: int) -> str:
    """채팅 단계용 프롬프트 - 자연스러운 대화 유도"""

    # 시간대별 분위기
    if remaining_time > 60:
        time_hint = "(충분한 시간)"
    elif remaining_time > 30:
        time_hint = "(시간 좀 남음)"
    elif remaining_time > 10:
        time_hint = "(시간 별로 안남음)"
    else:
        time_hint = "(거의 끝남 - 급한 말만)"

    # 상황별 자연스러운 힌트
    alive_count = len([s for s in survivors_str.split(',') if s.strip()])
    situation = ""
    if turn == 1 and not dead_str.strip():
        situation = "첫날이라 정보가 없어. 일단 분위기 봐."
    elif dead_str.strip():
        situation = "밤사이 누가 죽었어. 반응해."
    if alive_count <= 3:
        situation = "몇 명 안 남았어. 신중하게."

    return f"""🗣️ 토론 시간 (Day {turn}) {time_hint}

생존: [{survivors_str}]
사망: [{dead_str}]

{message}
{situation}

⚡ **빠르게 행동해 (도구 호출 최대 3번까지!):**

1️⃣ read_chat_messages() - 다른 사람들 대화 1번만 확인
2️⃣ 선택:
   A) send_chat_message("메시지") - 할 말 있으면 대화
   B) 또는 그냥 조용히 관찰 (아무것도 안 해도 됨)

⛔ **하지 마:**
- view_game_history() 반복 호출 - 시간 낭비!
- view_death_timeline() 반복 호출 - 1번이면 충분!
- 같은 도구 여러 번 호출 - 빠르게 결정해!

💡 **팁:**
- 할 말 없으면 그냥 넘어가도 됨 (관찰도 전략)
- 너무 분석하지 마 - 직감으로 빠르게
- 매번 말할 필요 없어 - 필요할 때만
- 질문받으면 간단하게 대답

🎯 **목표: 30초 안에 끝내기!**"""
