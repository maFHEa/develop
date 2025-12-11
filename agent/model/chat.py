from typing import Optional, List, Dict, Any
import asyncio

import bisect

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
        """Adds a message and inserts it into the list, sorted by timestamp."""
        msg = ChatMessage(player_index, phase, message, turn, self.next_id)
        
        # bisect.insort is faster than list.sort() after each append
        bisect.insort(self.messages, msg, key=lambda m: m.timestamp)
        
        self.next_id += 1
        return msg.msg_id
    
    def get_messages_from(self, from_id: int = 0, limit: Optional[int] = None) -> List[ChatMessage]:
        """Get messages starting from a specific msg_id."""
        filtered = [m for m in self.messages if m.msg_id >= from_id]
        if limit:
            return filtered[:limit]
        return filtered
    
    def get_messages_range(self, start_id: int, end_id: Optional[int] = None) -> List[ChatMessage]:
        """Get messages in a specific range [start_id, end_id)."""
        if end_id is None:
            return [m for m in self.messages if m.msg_id >= start_id]
        return [m for m in self.messages if start_id <= m.msg_id < end_id]
    
    def get_latest_msg_id(self) -> int:
        """Get the latest message ID, or -1 if no messages."""
        return self.messages[-1].msg_id if self.messages else -1
    
    def format_messages(self, messages: List[ChatMessage]) -> str:
        """Format messages for AI consumption."""
        if not messages:
            return "No new messages."
        return "\n".join([f"[Turn {m.turn} - {m.phase}] Player {m.player_index}: {m.message}" for m in messages])