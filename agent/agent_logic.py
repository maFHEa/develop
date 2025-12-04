"""
Mafia AI Agent Logic
Agent creation, function tools, and prompts
"""
import logging
from typing import Annotated, Optional
from agents import Agent, function_tool

logger = logging.getLogger(__name__)


# ============================================================================
# Agent Function Tools Factory
# ============================================================================

def create_agent_tools(state):
    """Create function tools with state closure to avoid global variables."""
    
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
        
        formatted = state.chat_history.format_messages(messages)
        logger.info(f"[CHAT] AI read {len(messages)} messages (from ID {start_id})")
        return formatted
    
    @function_tool
    def send_chat_message(
        message: Annotated[str, "Your message to send to other players."]
    ) -> str:
        """Send a chat message to all players in the game."""
        if not state.alive:
            return "You are dead and cannot send messages."
        
        state.pending_chat_messages.append(message)
        logger.info(f"[CHAT] AI queued message: {message}")
        return f"Message queued: '{message}'"
    
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
            return "Suspicion notes not initialized."
        
        result = state.suspicion_notes.write_note(
            target_index=player_index,
            level=suspicion_level,
            reasoning=reasoning,
            current_turn=state.current_turn
        )
        logger.info(f"[SUSPICION] {result}")
        return result
    
    @function_tool
    def view_suspicion_notes() -> str:
        """View all your suspicion notes about other players."""
        if state.suspicion_notes is None:
            return "Suspicion notes not initialized."
        
        formatted = state.suspicion_notes.format_all_notes()
        logger.info("[SUSPICION] AI viewed suspicion notes")
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
            logger.info(f"[ACTION] AI decided to VOTE for Player {target_index}")
            return f"Vote submitted: voting to eliminate Player {target_index}"
        else:
            state.pending_action_target = None
            state.action_submitted = True
            logger.info(f"[ACTION] AI decided to ABSTAIN from voting.")
            return "Invalid vote target or abstained. You will abstain from voting."
    
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
                logger.info(f"[ACTION] AI decided to perform {action_type.upper()} on Player {target_index}")
                return f"Night action submitted: targeting Player {target_index}"
            else:
                state.pending_action_target = None
                state.action_submitted = True
                logger.info(f"[ACTION] AI decided to ABSTAIN from night action.")
                return "Invalid target or abstained. No action will be taken."
        else:  # Citizen
            state.pending_action_target = None
            state.action_submitted = True
            logger.info(f"[ACTION] AI is a Citizen, sending dummy action.")
            return "You have no night action (Citizen). Dummy data will be sent for security."
    
    return [
        read_chat_messages,
        send_chat_message,
        write_suspicion_note,
        view_suspicion_notes,
        submit_vote,
        submit_night_action
    ]
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
        f"You are playing a game of Mafia. Your player index is {player_index}. There are {num_players} players total.\n"
        f"{role_instruction}\n"
        "During the day, you can chat with other players (not yet implemented).\n"
        "You MUST call submit_night_action() during the night phase and submit_vote() during the vote phase before responding."
    )
    
    return Agent(
        name=f"MafiaPlayer{player_index}",
        instructions=instructions,
        tools=tools,
        model="gpt-4o",
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
