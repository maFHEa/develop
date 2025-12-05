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
        
        # Add game state context to help agent understand situation
        alive_players = [i for i in range(state.num_players) if i in getattr(state, 'survivors', [])]
        dead_players = [i for i in range(state.num_players) if i not in alive_players]
        
        context = f"\n🎮 GAME STATE:\n"
        context += f"🟢 Alive: {len(alive_players)} players {alive_players}\n"
        context += f"💀 Dead: {len(dead_players)} players {dead_players}\n"
        context += f"📊 Day: {state.current_turn}\n\n"
        
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
        # Check when last message was sent
        current_time = time.time()
        if hasattr(state, 'last_message_time'):
            time_since_last = current_time - state.last_message_time
            min_delay = 5.0  # minimum 5 seconds between messages
            if time_since_last < min_delay:
                wait_time = min_delay - time_since_last
                return f"너무 빨라. {wait_time:.1f}초 후에 다시 시도해."
        
        state.last_message_time = current_time
        
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
        if not state.alive:
            return "죽은 플레이어는 투표할 수 없습니다."
        
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
        target_index: Annotated[int, "Index of player to target (0-indexed). Use -1 to abstain. Doctor CAN target themselves for self-heal."]
    ) -> str:
        """
        REQUIRED for night phase if you have a night role (Mafia/Doctor/Police).
        - Mafia: Choose a player to kill (cannot target self).
        - Doctor: Choose a player to save (CAN target self to heal yourself!).
        - Police: Choose a player to investigate (cannot target self).
        """
        if not state.alive:
            return "죽은 플레이어는 행동할 수 없습니다."
        
        if state.action_submitted:
            return "You have already submitted an action for this phase."
        
        action_type = state.role if state.role in ["mafia", "doctor", "police"] else "NONE"
        
        if action_type != "NONE":
            # Doctor can target themselves for self-heal
            can_target_self = (state.role == "doctor")
            
            # Check if target is valid
            is_valid_target = (
                0 <= target_index < state.num_players and
                (target_index != state.player_index or can_target_self)
            )
            
            if is_valid_target:
                state.pending_action_target = target_index
                state.action_submitted = True
                target_desc = "yourself" if target_index == state.player_index else f"Player {target_index}"
                logger.info(f"✅ Night action: {action_type.upper()} targeting {target_desc}")
                return f"Night action: {action_type.upper()} on {target_desc}"
            else:
                state.pending_action_target = None
                state.action_submitted = True
                logger.info(f"➖ Night action: {action_type.upper()} abstained (invalid target)")
                return "Night action: Abstain (invalid target)"
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
    
    # Chat phase - full strategic tools for discussion
    if phase == "chat" or phase == "day":
        tools.extend([
            read_chat_messages,
            send_chat_message,
            write_suspicion_note,
            view_suspicion_notes,
            # Advanced strategic tools for discussion
            analyze_player_behavior,
            get_strategic_overview,
            record_observation,
            analyze_voting_patterns,
            predict_next_target,
            detect_lies_and_contradictions
        ])
        return tools
    
    # Night phase - focus on action, limited analysis
    elif phase == "night":
        tools.extend([
            submit_night_action,  # PRIMARY TOOL - must be called
            view_suspicion_notes,  # Review notes
            get_strategic_overview,  # Quick overview only
        ])
        # Police gets investigation recording
        if state.role == "police":
            tools.append(record_investigation_result)
        return tools
    
    # Vote phase - focus on voting decision
    elif phase == "vote":
        tools.extend([
            submit_vote,  # PRIMARY TOOL - must be called
            view_suspicion_notes,  # Review notes
            get_strategic_overview,  # Quick overview only
            analyze_player_behavior,  # Analyze specific suspect
        ])
        return tools
    
    # Default/setup phase - basic tools
    else:
        tools.extend([
            write_suspicion_note,
            view_suspicion_notes,
        ])
        return tools
# ============================================================================
# Agent Creation & Prompts
# ============================================================================

def get_role_instructions(role: str, player_index: int) -> str:
    """Get role-specific instructions for the agent."""
    role_instructions = {
        "mafia": (
            f"You are Player {player_index}, a MAFIA member.\n"
            f"🎯 WIN CONDITION: Mafia wins when mafia members ≥ living citizens\n"
            f"🌙 NIGHT ACTION: Use submit_night_action(target) to KILL a citizen\n"
            f"💀 STRATEGY: Blend in, deflect suspicion, eliminate threats\n"
            f"🎲 TARGET SELECTION: DON'T always pick the same target! Vary your choices strategically:\n"
            f"  - Prioritize vocal players who lead discussions\n"
            f"  - Target players who seem intelligent or analytical\n"
            f"  - Eliminate players who suspected you or other mafia\n"
            f"  - Consider who the doctor might protect\n"
            f"⚠️ CRITICAL: During the day, pretend to be a citizen. NEVER reveal you are mafia!"
        ),
        "doctor": (
            f"You are Player {player_index}, a DOCTOR (citizen team).\n"
            f"🎯 WIN CONDITION: Citizens win when ALL mafia are eliminated\n"
            f"🌙 NIGHT ACTION: Use submit_night_action(target) to SAVE someone from mafia attack\n"
            f"💡 TIP: You can save yourself! If mafia attack your target, they survive\n"
            f"🤫 STRATEGY: Hide your role, save key players"
        ),
        "police": (
            f"You are Player {player_index}, a POLICE officer (citizen team).\n"
            f"🎯 WIN CONDITION: Citizens win when ALL mafia are eliminated\n"
            f"🌙 NIGHT ACTION: Use submit_night_action(target) to INVESTIGATE if they are mafia\n"
            f"🔍 RESULT: Private - only you will learn if target is MAFIA or NOT MAFIA\n"
            f"💡 TIP: Use record_investigation_result() to save findings\n"
            f"🤫 STRATEGY: Investigate suspects, share findings carefully to avoid being killed"
        ),
        "citizen": (
            f"You are Player {player_index}, a CITIZEN.\n"
            f"🎯 WIN CONDITION: Citizens win when ALL mafia are eliminated\n"
            f"🌙 NIGHT ACTION: None - call submit_night_action(-1) to abstain\n"
            f"💬 STRATEGY: Discuss, deduce, vote out suspicious players\n"
            f"🤔 Look for: Inconsistencies, defensive behavior, deflection tactics"
        )
    }
    return role_instructions.get(role, role_instructions['citizen'])


def create_mafia_agent(state, role: str, player_index: int, num_players: int) -> Agent:
    """Create an OpenAI Agent with role-specific instructions."""
    
    role_instruction = get_role_instructions(role, player_index)
    tools = create_agent_tools(state)
    
    instructions = (
        "=== MAFIA GAME AI PLAYER ===\n"
        f"Player Index: {player_index} | Total Players: {num_players}\n\n"
        f"{role_instruction}\n\n"
        
        "=== CORE RULES ===\n"
        "• NIGHT phase: MUST call submit_night_action(target) immediately\n"
        "• VOTE phase: MUST call submit_vote(target) immediately\n"
        "• CHAT phase: Read and respond naturally in Korean\n"
        "• Use tools to analyze, but ALWAYS submit your action!\n\n"
        
        "=== ACTION PRIORITY ===\n"
        "1. Night/Vote phase → Check notes briefly → SUBMIT ACTION\n"
        "2. Don't overthink - make a decision and act\n"
        "3. You can use get_strategic_overview() ONCE if needed\n"
        "4. Then IMMEDIATELY call submit_night_action() or submit_vote()\n\n"
        
        "=== KOREAN CHAT STYLE ===\n"
        "• Use 반말: ~야, ~임, ~던데, ~나봐, ~거같음\n"
        "• Short: 1-2 sentences max\n"
        "• Natural: 그건, 뭔가, 좀, 진짜, 근데\n"
        "• React: 어?, 헐, 아닌데?, ㅋㅋ\n"
        "• NO formal speech (~습니다, ~세요)\n"
    )
    
    return Agent(
        name=f"MafiaPlayer{player_index}",
        instructions=instructions,
        tools=tools,
        model="gpt-4o-mini",
    )


def create_action_prompt(phase: str, turn: int, survivors_str: str, dead_str: str, role: str, message: str) -> str:
    """Create the prompt for requesting agent action with clear context."""
    
    action_tool = "submit_night_action(target)" if phase == "night" else "submit_vote(target)"
    
    # Add strategic guidance based on role
    strategic_tip = ""
    if role == "mafia" and phase == "night":
        # Only add "don't default to Player 0" warning on first night (turn 1)
        if turn == 1:
            strategic_tip = (
                "\n🎯 TARGETING STRATEGY (First Night!):\n"
                "• Analyze ALL alive players - don't just default to the first option!\n"
                "• Who has been most vocal or influential in discussions?\n"
                "• Who seems intelligent and might figure out you're mafia?\n"
                "• Consider all players strategically\n"
            )
        else:
            strategic_tip = (
                "\n🎯 TARGETING STRATEGY:\n"
                "• Who has been most vocal or influential in discussions?\n"
                "• Who seems intelligent and might figure out you're mafia?\n"
                "• Who accused you or seemed suspicious of you?\n"
                "• Vary your targets - unpredictability helps mafia win\n"
            )
    elif role == "doctor" and phase == "night":
        strategic_tip = (
            "\n🎯 PROTECTION STRATEGY:\n"
            "• Who is most likely to be targeted by mafia?\n"
            "• Consider protecting vocal, smart players\n"
            "• You CAN protect yourself if you feel threatened\n"
            "• Vary your choices - don't be predictable\n"
        )
    elif role == "police" and phase == "night":
        strategic_tip = (
            "\n🎯 INVESTIGATION STRATEGY:\n"
            "• Investigate suspicious or defensive players\n"
            "• Don't waste investigations on obvious citizens\n"
            "• Build evidence to share strategically during day\n"
        )
    
    # Only add Player 0 warning for mafia on first night
    action_hint = ""
    if role == "mafia" and phase == "night":
        if turn == 1:
            action_hint = "🔪 Mafia: Pick someone to kill - think strategically about ALL options!"
        else:
            action_hint = "🔪 Mafia: Pick someone to kill"
    elif role == "doctor":
        action_hint = "💊 Doctor: Pick someone to save (can be yourself!)"
    elif role == "police":
        action_hint = "🔍 Police: Pick someone to investigate"
    elif phase == "night":
        action_hint = "😴 Citizen: Call submit_night_action(-1) to abstain"
    else:
        action_hint = "🗳️ Vote for who you think is Mafia"
    
    return f"""🎮 {phase.upper()} PHASE (Turn {turn})

🟢 ALIVE: [{survivors_str}]
💀 DEAD: [{dead_str}]

📢 {message}

🎯 YOUR ROLE: {role.upper()}{strategic_tip}

⚡ WORKFLOW:
1. (Optional) Call get_strategic_overview() or view_suspicion_notes() to review
2. Analyze ALL available targets - consider each player's behavior
3. ⚠️ CRITICAL: MUST call {action_tool}(target_index) before finishing!

{action_hint}

🚨 WARNING: If you don't call {action_tool}(), you will be forced to abstain!
Analyze if you want, but ALWAYS end by calling {action_tool}(your_choice)!"""


def create_chat_prompt(turn: int, survivors_str: str, dead_str: str, role: str, message: str, remaining_time: int) -> str:
    """Create the prompt for chat/day phase with time awareness."""
    
    time_guidance = ""
    if remaining_time > 90:
        time_guidance = "⏰ Plenty of time - read messages and participate naturally"
    elif remaining_time > 60:
        time_guidance = "⏰ Mid-phase - continue discussion, share your thoughts"
    elif remaining_time > 30:
        time_guidance = "⏰ Getting late - make your key points now"
    elif remaining_time > 10:
        time_guidance = "⏰ Final moments - wrap up your thoughts"
    else:
        time_guidance = "⏰ TIME ALMOST UP - send final message if needed, then stay quiet"
    
    return f"""💬 CHAT/DISCUSSION PHASE (Turn {turn})

🕐 Time Remaining: {remaining_time} seconds
{time_guidance}

🟢 ALIVE: [{survivors_str}] ({len([s for s in survivors_str.split(',') if s.strip()])} players)
💀 DEAD: [{dead_str}] ({len([d for d in dead_str.split(',') if d.strip()]) if dead_str else 0} players)

📢 {message}

🎯 YOUR ROLE: {role.upper()}
{'🔴 CRITICAL: Only ' + str(len([s for s in survivors_str.split(',') if s.strip()])) + ' players remain! Game is in final stage!' if len([s for s in survivors_str.split(',') if s.strip()]) <= 3 else ''}

💡 WHAT TO DO:
• ALWAYS start by calling read_chat_messages() to see what others are saying
• PAY ATTENTION to who died and who is alive - this is critical information!
• If there are new messages, respond to them naturally and ANSWER QUESTIONS
• If no new messages yet, you can still send an opening statement
• Use view_suspicion_notes() to review your notes
• Use analysis tools (get_strategic_overview, analyze_player_behavior) to gather intel
• Call send_chat_message() to participate in discussion
• React to deaths, accusations, and important events

⚠️ BEHAVIORAL RULES:
• This is a CONTINUOUS chat session - you'll be called multiple times
• Each round: read messages → think → respond if you have something to say
• If nothing to say this round, just call read_chat_messages() and wait
• Short messages (1-2 sentences per message)
• Korean casual speech (반말)
• Natural reactions: 어?, 헐, 그니까, ㄴㄴ, 아닌데?
• When time < 30s, start wrapping up
• When time < 10s, only send critical messages

🔄 This chat round will end soon, but you'll be called again if time remains!
Act like a human player - selective, reactive, natural!"""
