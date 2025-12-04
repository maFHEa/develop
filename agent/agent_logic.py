"""
Mafia AI Agent Logic
Agent creation, function tools, and prompts
"""
import logging
import os
from typing import Annotated, Optional
from agents import Agent, function_tool

# Configure logger for agent_logic module
logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

# Ensure logs directory exists and add handler if not already added
if not logger.handlers:
    os.makedirs('logs', exist_ok=True)
    handler = logging.StreamHandler()
    handler.setLevel(logging.INFO)
    formatter = logging.Formatter('%(asctime)s [%(levelname)s] %(name)s: %(message)s')
    handler.setFormatter(formatter)
    logger.addHandler(handler)


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
        
        logger.info(f"📖 Reading messages from ID {start_id}")
        messages = state.chat_history.get_messages_from(start_id)
        
        # Update last read position to latest
        latest_id = state.chat_history.get_latest_msg_id()
        if latest_id >= 0:
            state.last_read_msg_id = latest_id
        
        if messages:
            logger.info(f"📬 Found {len(messages)} new message(s)")
        else:
            logger.info("📭 No new messages")
        
        formatted = state.chat_history.format_messages(messages)
        return formatted
    
    @function_tool
    def send_chat_message(
        message: Annotated[str, "Your message to send to other players. Must be in Korean."]
    ) -> str:
        """Send a chat message to all players in the game. Message must be in Korean."""
        if not state.alive:
            return "죽은 플레이어는 메시지를 보낼 수 없습니다."
        
        logger.info(f"💬 Sending message: \"{message[:80]}{'...' if len(message) > 80 else ''}\"")
        
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
        
        logger.info(f"📝 Suspicion note: Player {player_index} = {suspicion_level.upper()} (reason: {reasoning[:50]}...)")
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
        
        logger.info("📋 Reviewing suspicion notes")
        formatted = state.suspicion_notes.format_all_notes()
        return formatted
    
    # 3. Voting Tools
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
            logger.info(f"✅ Vote submitted: Target=Player {target_index}")
            return f"Vote submitted: Player {target_index}"
        else:
            state.pending_action_target = None
            state.action_submitted = True
            logger.info("➖ Vote: Abstained")
            return "Vote abstained"
    
    # 4. Night Action Tools
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
                logger.info(f"✅ Night action: {action_type.upper()} targeting Player {target_index}")
                return f"Night action: {action_type.upper()} on Player {target_index}"
            else:
                state.pending_action_target = None
                state.action_submitted = True
                logger.info(f"➖ Night action: {action_type.upper()} abstained")
                return "Night action: Abstain"
        else:  # Citizen
            state.pending_action_target = None
            state.action_submitted = True
            logger.info("😴 No night action (Citizen role)")
            return "No night action (Citizen)"
    
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
    
    # Build tool list dynamically based on role and phase
    tools = []
    
    # Chat phase - continuous interaction
    if phase == "chat":
        tools.extend([
            read_chat_messages,
            send_chat_message,
            write_suspicion_note,
            view_suspicion_notes
        ])
        return tools
    
    # 1. Chat tools - available in all phases when alive
    if state.alive:
        tools.extend([read_chat_messages, send_chat_message])
    
    # 2. Suspicion notes - always available to track thoughts
    tools.extend([write_suspicion_note, view_suspicion_notes])
    
    # 3. Phase-specific tools
    if phase == "vote":
        tools.append(submit_vote)
    elif phase == "night":
        tools.append(submit_night_action)
        # Police gets investigation recording during night
        if state.role == "police":
            tools.append(record_investigation_result)
    
    return tools
# ============================================================================
# Agent Creation & Prompts
# ============================================================================

def get_role_instructions(role: str, player_index: int) -> str:
    """Get role-specific instructions for the agent."""
    role_instructions = {
        "mafia": f"You are Player {player_index}, a MAFIA member. Your goal is to eliminate citizens. Use submit_night_action() to kill someone.",
        "doctor": f"You are Player {player_index}, a DOCTOR. Your goal is to save citizens. Use submit_night_action() to save someone.",
        "police": f"You are Player {player_index}, a POLICE officer. Your goal is to find mafia. Use submit_night_action() to investigate someone.",
        "citizen": f"You are Player {player_index}, a CITIZEN. Your goal is to vote out mafia. You have no night action (call submit_night_action(-1))."
    }
    return role_instructions.get(role, role_instructions['citizen'])


def create_mafia_agent(state, role: str, player_index: int, num_players: int) -> Agent:
    """Create an OpenAI Agent with role-specific instructions."""
    
    role_instruction = get_role_instructions(role, player_index)
    tools = create_agent_tools(state)
    
    instructions = (
        f"You are an AI player in a Mafia game. Player index: {player_index}. Total players: {num_players}.\n"
        f"{role_instruction}\n\n"
        "BEHAVIORAL RULES:\n"
        "1. During CHAT phase: Call read_chat_messages() and send_chat_message() repeatedly in an infinite loop\n"
        "2. During NIGHT phase: Call submit_night_action() once with your choice\n"
        "3. During VOTE phase: Call submit_vote() once with your choice\n"
        "4. NEVER use words like 'finished', 'done', 'complete' during chat phase\n"
        "5. ALWAYS continue reading and responding to messages until externally cancelled\n\n"
        "When chatting, act like a real player: be conversational, ask questions, respond to others, and keep the discussion going.\n\n"
        "CRITICAL: ALL your chat messages MUST be in KOREAN. Speak naturally in Korean like a native Korean player."
    )
    
    return Agent(
        name=f"MafiaPlayer{player_index}",
        instructions=instructions,
        tools=tools,
        model="gpt-4o-mini",
    )


def create_action_prompt(phase: str, turn: int, survivors_str: str, role: str, message: str) -> str:
    """Create the prompt for requesting agent action."""
    return f"""Current Phase: {phase.upper()} - Turn {turn}
Survivors: [{survivors_str}]
Your Role: {role.upper()}
Host Message: '{message}'

Your task is to analyze the situation and decide on your action.
You MUST call the required function (submit_night_action or submit_vote) before finishing.
Think step-by-step about your strategy and then make your call."""
