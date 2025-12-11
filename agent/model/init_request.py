from pydantic import BaseModel
from typing import List, Optional

# ============================================================================
# Pydantic Models
# ============================================================================

class InitRequest(BaseModel):
    """Initialize agent with game parameters (after DKG, before role assignment)"""
    game_id: str  # Short UUID to identify game session
    crypto_context: str  # Base64 serialized CryptoContext
    joint_public_key: str  # Base64 serialized joint public key
    player_index: int
    num_players: int
    player_addresses: List[str] = []  # All player HTTP addresses for relay decrypt
    # Note: role is NOT sent here - it will be decrypted blindly later

