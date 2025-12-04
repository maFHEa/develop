"""
Suspicion Note Management
Tracks player suspicions and investigation results
"""
from typing import Optional, Dict, List
from enum import Enum


class SuspicionLevel(Enum):
    """Basic suspicion levels for non-police roles"""
    HIGH_SUSPICION = "high"                  # 높은 의심
    MEDIUM_SUSPICION = "medium"              # 중간 의심
    LOW_SUSPICION = "low"                    # 낮은 의심
    NEUTRAL = "neutral"                      # 중립 (의심 없음)
    UNKNOWN = "unknown"                      # 아직 판단 안 함


class PoliceSuspicionLevel(Enum):
    """Extended suspicion levels for Police (includes investigation results)"""
    CONFIRMED_MAFIA = "confirmed_mafia"      # 확정 마피아 (경찰 조사 결과)
    CONFIRMED_CITIZEN = "confirmed_citizen"  # 확정 시민 (경찰 조사 결과)
    HIGH_SUSPICION = "high"                  # 높은 의심
    MEDIUM_SUSPICION = "medium"              # 중간 의심
    LOW_SUSPICION = "low"                    # 낮은 의심
    NEUTRAL = "neutral"                      # 중립 (의심 없음)
    UNKNOWN = "unknown"                      # 아직 판단 안 함


class SuspicionNote:
    """Single suspicion note about a player"""
    def __init__(
        self,
        player_index: int,
        level,  # SuspicionLevel or PoliceSuspicionLevel
        reasoning: str,
        is_confirmed: bool = False,
        turn: int = 0
    ):
        self.player_index = player_index
        self.level = level
        self.reasoning = reasoning
        self.is_confirmed = is_confirmed  # True면 경찰 조사 결과 (수정 불가)
        self.turn = turn  # 어느 턴에 작성되었는지
        self.is_dead = False  # 플레이어가 죽었는지
    
    def mark_dead(self):
        """Mark this player as dead"""
        self.is_dead = True
    
    def can_update(self) -> bool:
        """Check if this note can be updated (경찰 조사 결과는 수정 불가)"""
        return not self.is_confirmed
    
    def to_dict(self) -> dict:
        return {
            "player_index": self.player_index,
            "level": self.level.value,
            "reasoning": self.reasoning,
            "is_confirmed": self.is_confirmed,
            "is_dead": self.is_dead,
            "turn": self.turn
        }
    
    def __str__(self) -> str:
        status = []
        if self.is_dead:
            status.append("💀 DEAD")
        if self.is_confirmed:
            status.append("✓ CONFIRMED")
        
        status_str = f" [{', '.join(status)}]" if status else ""
        return f"Player {self.player_index}: {self.level.value.upper()}{status_str} - {self.reasoning}"


class SuspicionNoteManager:
    """Manages suspicion notes for all players (일반 역할용)"""
    LEVEL_ENUM = SuspicionLevel  # 사용할 Enum 타입
    
    def __init__(self, num_players: int, player_index: int):
        self.num_players = num_players
        self.player_index = player_index
        self.notes: Dict[int, SuspicionNote] = {}
        
        # Initialize all players as UNKNOWN
        for i in range(num_players):
            if i != player_index:
                self.notes[i] = SuspicionNote(
                    player_index=i,
                    level=self.LEVEL_ENUM.UNKNOWN,
                    reasoning="No information yet",
                    turn=0
                )
    
    def write_note(
        self,
        target_index: int,
        level: str,
        reasoning: str,
        current_turn: int,
        is_confirmed: bool = False
    ) -> str:
        """Write or update a suspicion note"""
        if target_index == self.player_index:
            return "Cannot write a note about yourself."
        
        if target_index < 0 or target_index >= self.num_players:
            return f"Invalid player index: {target_index}"
        
        # Check if note exists and can be updated
        if target_index in self.notes:
            existing = self.notes[target_index]
            if not existing.can_update():
                return f"Cannot update Player {target_index}: This is a confirmed investigation result."
        
        # Parse suspicion level
        try:
            suspicion_level = self.LEVEL_ENUM(level.lower())
        except ValueError:
            valid_levels = [e.value for e in self.LEVEL_ENUM]
            return f"Invalid suspicion level: {level}. Valid options: {', '.join(valid_levels)}"
        
        # Create or update note
        self.notes[target_index] = SuspicionNote(
            player_index=target_index,
            level=suspicion_level,
            reasoning=reasoning,
            is_confirmed=is_confirmed,
            turn=current_turn
        )
        
        return f"Suspicion note updated: {self.notes[target_index]}"
    
    def mark_player_dead(self, player_index: int):
        """Mark a player as dead in notes"""
        if player_index in self.notes:
            self.notes[player_index].mark_dead()
    
    def get_note(self, player_index: int) -> Optional[SuspicionNote]:
        """Get suspicion note for a specific player"""
        return self.notes.get(player_index)
    
    def get_all_notes(self) -> List[SuspicionNote]:
        """Get all suspicion notes"""
        return list(self.notes.values())
    
    def format_all_notes(self) -> str:
        """Format all notes for AI viewing"""
        if not self.notes:
            return "No suspicion notes yet."
        
        alive_notes = [n for n in self.notes.values() if not n.is_dead]
        dead_notes = [n for n in self.notes.values() if n.is_dead]
        
        lines = ["=== SUSPICION NOTES ==="]
        
        if alive_notes:
            lines.append("\n[ALIVE PLAYERS]")
            for note in sorted(alive_notes, key=lambda n: n.player_index):
                lines.append(str(note))
        
        if dead_notes:
            lines.append("\n[DEAD PLAYERS]")
            for note in sorted(dead_notes, key=lambda n: n.player_index):
                lines.append(str(note))
        
        return "\n".join(lines)


class PoliceNoteManager(SuspicionNoteManager):
    """Manages suspicion notes for Police (경찰 전용 - 조사 결과 추가)"""
    LEVEL_ENUM = PoliceSuspicionLevel  # 경찰은 확장된 Enum 사용
    
    def add_investigation_result(
        self,
        target_index: int,
        is_mafia: bool,
        current_turn: int
    ) -> str:
        """Add confirmed investigation result (경찰만 사용)"""
        if target_index == self.player_index:
            return "Cannot investigate yourself."
        
        if target_index < 0 or target_index >= self.num_players:
            return f"Invalid player index: {target_index}"
        
        level = PoliceSuspicionLevel.CONFIRMED_MAFIA if is_mafia else PoliceSuspicionLevel.CONFIRMED_CITIZEN
        reasoning = f"[INVESTIGATION TURN {current_turn}] Police investigation confirmed: {'MAFIA' if is_mafia else 'CITIZEN'}"
        
        self.notes[target_index] = SuspicionNote(
            player_index=target_index,
            level=level,
            reasoning=reasoning,
            is_confirmed=True,  # 확정 결과 - 수정 불가
            turn=current_turn
        )
        
        return f"Investigation result recorded: Player {target_index} is {'MAFIA' if is_mafia else 'CITIZEN'}"
    
    def get_confirmed_mafia(self) -> List[int]:
        """Get list of confirmed mafia members"""
        return [
            note.player_index
            for note in self.notes.values()
            if note.level == PoliceSuspicionLevel.CONFIRMED_MAFIA and not note.is_dead
        ]
    
    def get_confirmed_citizens(self) -> List[int]:
        """Get list of confirmed citizens"""
        return [
            note.player_index
            for note in self.notes.values()
            if note.level == PoliceSuspicionLevel.CONFIRMED_CITIZEN and not note.is_dead
        ]
