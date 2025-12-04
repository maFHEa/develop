"""
Advanced Strategic Tools for Mafia Agents
Provides sophisticated analysis and decision-making capabilities
"""
from typing import List, Tuple, Optional
import random


class BluffingStrategy:
    """Handles lying and misdirection for Mafia agents"""
    
    @staticmethod
    def should_claim_role(role: str, suspicion_level: str, turn: int) -> Tuple[bool, Optional[str]]:
        """Decide if agent should claim a fake role"""
        if role != "mafia":
            return False, None
        
        # Mafia should claim citizen early, doctor/police if heavily suspected
        if suspicion_level == "high" and turn >= 3:
            # Claim doctor or police to seem valuable
            fake_role = random.choice(["doctor", "police"])
            return True, fake_role
        
        return False, "citizen"
    
    @staticmethod
    def generate_fake_investigation(alive_players: List[int], known_citizens: List[int]) -> Tuple[int, bool]:
        """Generate a fake police investigation result"""
        # Accuse a non-mafia player
        targets = [p for p in alive_players if p in known_citizens]
        if targets:
            target = random.choice(targets)
            # Sometimes say they're mafia to create chaos
            is_mafia_claim = random.random() < 0.3
            return target, is_mafia_claim
        
        return -1, False
    
    @staticmethod
    def deflect_suspicion(accusers: List[int], alive_players: List[int]) -> str:
        """Generate deflection strategy"""
        if not accusers:
            return "maintain_innocence"
        
        # Counter-accuse the most vocal accuser
        target = random.choice(accusers)
        return f"counter_accuse:{target}"


class VotingStrategy:
    """Advanced voting decision algorithms"""
    
    @staticmethod
    def calculate_threat_level(
        player_index: int,
        credibility: float,
        vote_power: int,
        role: str,
        is_mafia: bool
    ) -> float:
        """Calculate how threatening a player is"""
        threat = 0.0
        
        # High credibility players are threats to mafia
        if is_mafia:
            threat += credibility * 2
            
            # Active voters are dangerous
            threat += vote_power * 0.5
            
            # Doctor/Police claims are priority targets
            if role in ["doctor", "police"]:
                threat += 5.0
        else:
            # For citizens, suspected mafia are threats
            threat = 10.0 - credibility
        
        return threat
    
    @staticmethod
    def decide_vote_target(
        alive_players: List[int],
        suspicion_scores: dict,
        alliances: List[int],
        own_role: str,
        strategic_memory
    ) -> Tuple[int, str]:
        """Decide who to vote for with reasoning"""
        if own_role == "mafia":
            return VotingStrategy._mafia_vote_strategy(
                alive_players, suspicion_scores, strategic_memory
            )
        else:
            return VotingStrategy._citizen_vote_strategy(
                alive_players, suspicion_scores, alliances, strategic_memory
            )
    
    @staticmethod
    def _mafia_vote_strategy(alive_players, suspicion_scores, memory):
        """Mafia voting strategy: blend in, eliminate threats"""
        # Vote with the crowd to blend in
        # Target: high credibility players or accusers
        
        # Get most suspicious according to memory
        suspicious_list = memory.get_most_suspicious_players(3)
        
        if suspicious_list:
            # Vote for most suspicious to blend in
            target = suspicious_list[0][0]
            reason = f"Following crowd - Player {target} is suspicious"
            return target, reason
        
        # Fallback: vote for random non-ally
        if alive_players:
            target = random.choice(alive_players)
            return target, "No strong suspicion, voting randomly"
        
        return -1, "Abstaining"
    
    @staticmethod
    def _citizen_vote_strategy(alive_players, suspicion_scores, alliances, memory):
        """Citizen voting strategy: eliminate mafia"""
        # Vote based on analysis
        suspicious_list = memory.get_most_suspicious_players(3)
        
        if suspicious_list:
            target = suspicious_list[0][0]
            reason = suspicious_list[0][1]
            return target, f"Most suspicious: {reason}"
        
        # Vote for someone outside alliance
        non_allies = [p for p in alive_players if p not in alliances]
        if non_allies:
            target = random.choice(non_allies)
            return target, "Not in alliance group"
        
        return -1, "No clear target"


class MafiaCoordination:
    """Implicit coordination between mafia members"""
    
    @staticmethod
    def encode_signal_in_message(target_player: int, signal_type: str) -> str:
        """Encode hidden signals in casual messages"""
        signals = {
            "suggest_target": [
                f"Player {target_player} 좀 이상하지 않아?",
                f"{target_player}번 발언이 수상해 보이는데",
                f"내 생각엔 {target_player}가 의심스러워"
            ],
            "defend_ally": [
                f"Player {target_player}는 아닌 것 같은데",
                f"{target_player}번은 시민 같아",
                f"{target_player} 의심하는 사람들이 더 이상해"
            ],
            "deflect": [
                f"다들 {target_player}는 생각 안 해봤어?",
                f"근데 {target_player}는 너무 조용한데"
            ]
        }
        
        return random.choice(signals.get(signal_type, [f"Player {target_player} 어떻게 생각해?"]))
    
    @staticmethod
    def detect_mafia_signals(messages: List[str], player_index: int) -> List[Tuple[str, int]]:
        """Detect potential mafia signals in messages"""
        # Pattern: repeated mentions of same player = coordinated attack
        # Pattern: defending same person = protecting ally
        
        # This is a simplified version - real implementation would use NLP
        signals = []
        
        # Count mentions per player
        from collections import Counter
        mentions = Counter()
        
        for msg in messages:
            for i in range(10):  # Assume max 10 players
                if str(i) in msg or f"Player {i}" in msg:
                    mentions[i] += 1
        
        # If a player is mentioned 3+ times, it's coordinated
        for player, count in mentions.items():
            if count >= 3:
                signals.append(("coordinated_mention", player))
        
        return signals


class PsychologicalProfile:
    """Psychological modeling of players"""
    
    @staticmethod
    def detect_emotional_state(messages: List[str]) -> str:
        """Detect emotional state from messages"""
        # Simplified emotion detection
        
        angry_words = ["짜증", "화", "진짜", "대체", "왜"]
        defensive_words = ["아니", "오해", "억울", "그게아니"]
        nervous_words = ["음", "글쎄", "몰라", "잘모르겠"]
        confident_words = ["확실", "분명", "틀림없", "절대"]
        
        text = " ".join(messages).lower()
        
        if sum(word in text for word in angry_words) >= 2:
            return "angry/frustrated"
        elif sum(word in text for word in defensive_words) >= 2:
            return "defensive"
        elif sum(word in text for word in nervous_words) >= 2:
            return "nervous/uncertain"
        elif sum(word in text for word in confident_words) >= 2:
            return "confident"
        
        return "neutral"
    
    @staticmethod
    def predict_role_from_behavior(
        message_count: int,
        tone: str,
        vote_pattern: List[int],
        turn: int
    ) -> Tuple[str, float]:
        """Predict player's role from behavior (role, confidence)"""
        
        # Mafia indicators
        if tone == "defensive" and len(vote_pattern) > 2:
            if len(set(vote_pattern)) > len(vote_pattern) * 0.5:
                return "mafia", 0.6  # Vote switching
        
        # Police indicators  
        if tone == "confident" and turn >= 2:
            return "police", 0.5  # Confident from investigation
        
        # Doctor indicators
        if message_count < 3 and tone == "neutral":
            return "doctor", 0.4  # Staying quiet to hide
        
        # Citizen (default)
        return "citizen", 0.3


class ConversationTactics:
    """Advanced conversation strategies"""
    
    @staticmethod
    def choose_response_timing(
        messages_since_last: int,
        topic_relevance: float,
        suspicion_on_self: float
    ) -> Tuple[bool, str]:
        """Decide when to respond and why"""
        
        # Respond if directly relevant
        if topic_relevance > 0.7:
            return True, "relevant_to_me"
        
        # Respond if being accused
        if suspicion_on_self > 0.6:
            return True, "defend_self"
        
        # Don't spam - wait if recently spoke
        if messages_since_last < 3:
            return False, "too_soon"
        
        # Random participation to seem natural
        if random.random() < 0.3 and messages_since_last >= 5:
            return True, "natural_participation"
        
        return False, "wait_and_observe"
    
    @staticmethod
    def generate_strategic_message(
        context: str,
        own_role: str,
        suspicion_level: str,
        turn: int
    ) -> str:
        """Generate contextually appropriate message"""
        
        if context == "defend_self":
            if own_role == "mafia":
                return random.choice([
                    "이건 좀 억울한데? 근거가 뭔데",
                    "나 아닌데 ㅋㅋ 오해임",
                    "의심하는 사람들이 더 수상해 보이는데"
                ])
            else:
                return random.choice([
                    "아 진짜 시민임 ㅋㅋ",
                    "왜 나를 의심해? 이상한데",
                    "다른 사람 보는 게 나을 듯"
                ])
        
        elif context == "accuse":
            return random.choice([
                "쟤 행동 패턴이 이상함",
                "발언이 앞뒤가 안 맞는데?",
                "쟤 투표 바꾼 거 봤어?"
            ])
        
        elif context == "analyze":
            return random.choice([
                "지금까지 죽은 사람들 보면...",
                "투표 패턴 생각해보면",
                "누가 이득 보는지 생각해야 해"
            ])
        
        return "음 잘 모르겠네"
