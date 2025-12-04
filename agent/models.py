from pydantic import BaseModel
from typing import List

# ============================================================================
# Pydantic Models
# ============================================================================

class InitRequest(BaseModel):
    """Initialize agent with game parameters"""
    game_id: str  # Short UUID to identify game session
    public_context: str
    role: str
    player_index: int
    num_players: int


class GameUpdateRequest(BaseModel):
    """Update agent with current game state"""
    phase: str  # "night", "day", "vote"
    message: str
    survivors: List[int]
    dead_players: List[int]


class ActionResponse(BaseModel):
    """Agent's encrypted action response"""
    encrypted_action: str
    phase: str
    chat_messages: List[str] = []  # Messages agent wants to send


class ChatBroadcast(BaseModel):
    """P2P chat broadcast"""
    msg_id: int
    player_index: int
    message: str
    phase: str
    turn: int
