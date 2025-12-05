"""
Chat Message Models for API Communication

Pydantic models for chat broadcast between players.
"""
from pydantic import BaseModel


class ChatBroadcast(BaseModel):
    """P2P chat broadcast"""
    msg_id: int
    player_index: int
    message: str
    phase: str
    turn: int
