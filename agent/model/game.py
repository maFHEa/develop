"""
Game State and Update Models

Models for communicating game state and phase information.
"""
from pydantic import BaseModel
from typing import List, Optional


class InitRequest(BaseModel):
    """Initialize agent with game parameters before role assignment"""
    game_id: str
    crypto_context: str  # Base64 serialized CryptoContext
    joint_public_key: str  # Base64 serialized joint public key
    player_index: int
    num_players: int


class GameUpdateRequest(BaseModel):
    """Update agent with current game state"""
    phase: str  # "night", "day", "vote", "chat"
    message: str
    survivors: List[int]
    dead_players: List[int]
    remaining_time: Optional[int] = None  # Seconds remaining in chat phase
