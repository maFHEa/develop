"""
Advanced Memory System for Mafia Agent
Tracks patterns, behaviors, and strategic insights
"""
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass, field
from collections import defaultdict
import json


@dataclass
class PlayerBehaviorProfile:
    """Tracks a player's behavior patterns"""
    player_index: int
    
    # Communication patterns
    message_count: int = 0
    avg_message_length: float = 0.0
    aggressive_tone_count: int = 0  # 공격적 발언 횟수
    defensive_tone_count: int = 0   # 방어적 발언 횟수
    
    # Voting patterns
    vote_history: List[int] = field(default_factory=list)  # 누구에게 투표했는지
    voted_against_by: List[int] = field(default_factory=list)  # 누가 자신을 투표했는지
    vote_changes: int = 0  # 투표를 바꾼 횟수 (의심스러움)
    
    # Behavioral flags
    stays_silent: bool = False  # 조용히 있는 편인가
    speaks_first: int = 0  # 먼저 말한 횟수
    bandwagons: int = 0  # 다수 의견에 편승한 횟수
    
    # Strategic insights
    likely_role: Optional[str] = None  # 추정 역할
    alliance_with: List[int] = field(default_factory=list)  # 동맹 관계로 보이는 플레이어
    conflicts_with: List[int] = field(default_factory=list)  # 갈등 관계
    
    # Credibility
    credibility_score: float = 5.0  # 1-10, 신뢰도
    contradiction_count: int = 0  # 모순 발언 횟수
    
    def update_message_stats(self, message: str, is_aggressive: bool = False, is_defensive: bool = False):
        """Update communication statistics"""
        self.message_count += 1
        # Update running average
        msg_len = len(message)
        self.avg_message_length = (
            (self.avg_message_length * (self.message_count - 1) + msg_len) / self.message_count
        )
        
        if is_aggressive:
            self.aggressive_tone_count += 1
        if is_defensive:
            self.defensive_tone_count += 1
    
    def add_vote(self, target: int):
        """Record a vote"""
        if self.vote_history and self.vote_history[-1] != target:
            self.vote_changes += 1
        self.vote_history.append(target)
    
    def is_suspicious(self) -> Tuple[bool, str]:
        """Determine if behavior is suspicious with reasoning"""
        reasons = []
        
        if self.vote_changes >= 2:
            reasons.append("투표를 자주 바꿈 (우유부단 또는 의도적)")
        
        if self.defensive_tone_count > self.message_count * 0.3:
            reasons.append("방어적 태도가 많음")
        
        if self.contradiction_count >= 2:
            reasons.append("말이 자주 바뀜")
        
        if len(self.alliance_with) == 0 and self.message_count > 5:
            reasons.append("누구와도 친하지 않음 (고립)")
        
        if self.stays_silent and self.message_count < 3:
            reasons.append("너무 조용함 (숨는 중?)")
        
        if self.bandwagons >= 3:
            reasons.append("다수 의견에 편승 (책임 회피?)")
        
        return len(reasons) > 0, " | ".join(reasons) if reasons else "정상"
    
    def to_summary(self) -> str:
        """Get a human-readable summary"""
        suspicious, reasons = self.is_suspicious()
        
        return f"""Player {self.player_index} Profile:
🗨️ Messages: {self.message_count} (avg {self.avg_message_length:.1f} chars)
🎯 Votes: {len(self.vote_history)} casts, {self.vote_changes} changes
⚔️ Tone: {self.aggressive_tone_count} aggressive, {self.defensive_tone_count} defensive
🤝 Allies: {self.alliance_with}
⚡ Conflicts: {self.conflicts_with}
💯 Credibility: {self.credibility_score:.1f}/10
🚨 Suspicious: {"YES - " + reasons if suspicious else "NO"}
💡 Likely Role: {self.likely_role or "Unknown"}"""


class StrategicMemory:
    """Advanced memory system for strategic gameplay"""
    
    def __init__(self, num_players: int, own_index: int):
        self.num_players = num_players
        self.own_index = own_index
        
        # Player profiles
        self.profiles: Dict[int, PlayerBehaviorProfile] = {
            i: PlayerBehaviorProfile(i) for i in range(num_players) if i != own_index
        }
        
        # Game state memory
        self.death_timeline: List[Tuple[int, int, str]] = []  # (turn, player, cause)
        self.vote_rounds: List[Dict[int, int]] = []  # [{voter: target}, ...]
        
        # Pattern detection
        self.voting_blocks: List[List[int]] = []  # Groups that vote together
        self.suspicious_patterns: List[str] = []
        
        # Strategic notes
        self.strategic_insights: List[str] = []
        self.current_strategy: str = ""
        
    def record_message(self, player_index: int, message: str, turn: int):
        """Record and analyze a message"""
        if player_index == self.own_index or player_index not in self.profiles:
            return
        
        profile = self.profiles[player_index]
        
        # Simple tone analysis (can be improved with NLP)
        is_aggressive = any(word in message for word in ["확실", "분명", "틀림없", "절대"])
        is_defensive = any(word in message for word in ["아니", "그게아니", "오해", "억울"])
        
        profile.update_message_stats(message, is_aggressive, is_defensive)
    
    def record_vote(self, voter: int, target: int, turn: int):
        """Record voting behavior"""
        if voter == self.own_index:
            return
            
        if voter in self.profiles:
            self.profiles[voter].add_vote(target)
        
        if target in self.profiles:
            self.profiles[target].voted_against_by.append(voter)
    
    def record_death(self, player_index: int, turn: int, cause: str):
        """Record a death and analyze implications"""
        self.death_timeline.append((turn, player_index, cause))
        
        # Analyze who benefits from this death
        if cause == "night":
            # Mafia likely killed a threat
            if player_index in self.profiles:
                profile = self.profiles[player_index]
                if profile.credibility_score > 7:
                    self.add_insight(f"Player {player_index} (high credibility) killed → mafia felt threatened")
                if len(profile.conflicts_with) > 0:
                    self.add_insight(f"Check conflicts: {profile.conflicts_with} might be mafia")
        elif cause == "vote":
            # Check who pushed for this vote
            pass
    
    def detect_voting_blocks(self) -> List[List[int]]:
        """Detect groups that consistently vote together"""
        if len(self.vote_rounds) < 2:
            return []
        
        # Simple algorithm: find players who voted for same target 2+ times
        vote_pairs = defaultdict(int)
        
        for vote_round in self.vote_rounds:
            targets = defaultdict(list)
            for voter, target in vote_round.items():
                targets[target].append(voter)
            
            # Count pairs
            for voters in targets.values():
                if len(voters) >= 2:
                    for i in range(len(voters)):
                        for j in range(i + 1, len(voters)):
                            pair = tuple(sorted([voters[i], voters[j]]))
                            vote_pairs[pair] += 1
        
        # Find consistent pairs (voted together 2+ times)
        blocks = []
        for pair, count in vote_pairs.items():
            if count >= 2:
                blocks.append(list(pair))
        
        return blocks
    
    def detect_alliances(self):
        """Detect and update alliance relationships"""
        blocks = self.detect_voting_blocks()
        
        for block in blocks:
            for player in block:
                if player in self.profiles:
                    for ally in block:
                        if ally != player and ally not in self.profiles[player].alliance_with:
                            self.profiles[player].alliance_with.append(ally)
    
    def add_insight(self, insight: str):
        """Add a strategic insight"""
        if insight not in self.strategic_insights:
            self.strategic_insights.append(insight)
    
    def get_most_suspicious_players(self, n: int = 3) -> List[Tuple[int, str]]:
        """Get top N most suspicious players with reasons"""
        results = []
        
        for player_idx, profile in self.profiles.items():
            if not hasattr(profile, 'is_dead') or not profile.is_dead:
                suspicious, reasons = profile.is_suspicious()
                if suspicious:
                    results.append((player_idx, reasons))
        
        return results[:n]
    
    def get_analysis_summary(self) -> str:
        """Get comprehensive analysis for decision making"""
        lines = ["=== STRATEGIC ANALYSIS ===\n"]
        
        # Voting blocks
        blocks = self.detect_voting_blocks()
        if blocks:
            lines.append(f"🤝 Voting Blocks: {blocks}")
            lines.append("   → Possible mafia coordination or citizen alliance\n")
        
        # Most suspicious
        suspicious = self.get_most_suspicious_players(3)
        if suspicious:
            lines.append("🚨 Most Suspicious Players:")
            for player_idx, reasons in suspicious:
                lines.append(f"   Player {player_idx}: {reasons}")
            lines.append("")
        
        # Recent insights
        if self.strategic_insights:
            lines.append("💡 Strategic Insights:")
            for insight in self.strategic_insights[-5:]:
                lines.append(f"   • {insight}")
            lines.append("")
        
        # Death analysis
        if self.death_timeline:
            lines.append(f"💀 Death Timeline ({len(self.death_timeline)} deaths):")
            for turn, player, cause in self.death_timeline[-3:]:
                lines.append(f"   Turn {turn}: Player {player} ({cause})")
        
        return "\n".join(lines)
    
    def get_player_summary(self, player_index: int) -> str:
        """Get detailed summary of a specific player"""
        if player_index not in self.profiles:
            return f"No data for Player {player_index}"
        
        return self.profiles[player_index].to_summary()
    
    def export_state(self) -> dict:
        """Export memory state for persistence"""
        return {
            "profiles": {k: v.__dict__ for k, v in self.profiles.items()},
            "death_timeline": self.death_timeline,
            "voting_blocks": self.voting_blocks,
            "insights": self.strategic_insights,
            "strategy": self.current_strategy
        }
