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
    # Note: role is NOT sent here - it will be decrypted blindly later


# ============================================================================
# DKG (Distributed Key Generation) Models
# ============================================================================

class DKGSetupRequest(BaseModel):
    """Initial DKG setup - send crypto context to agent"""
    game_id: str
    crypto_context: str  # Base64 serialized CryptoContext
    num_players: int
    player_index: int


class DKGSetupResponse(BaseModel):
    """Agent acknowledges DKG setup"""
    success: bool
    message: str


class DKGRoundRequest(BaseModel):
    """DKG round - agent generates/joins key"""
    round_number: int  # 1 = lead, 2+ = join
    previous_public_key: Optional[str] = None  # Base64, None for lead


class DKGRoundResponse(BaseModel):
    """Agent returns its public key"""
    public_key: str  # Base64 serialized public key
    success: bool


class PartialDecryptRequest(BaseModel):
    """Request for partial decryption"""
    ciphertext: str  # Base64 serialized ciphertext
    is_lead: bool  # True for first party


class PartialDecryptResponse(BaseModel):
    """Partial decryption result"""
    partial_ciphertext: str  # Base64 serialized partial result
    success: bool


class RoleAssignmentRequest(BaseModel):
    """Notify agent of their assigned role after DKG"""
    role: str
    joint_public_key: str  # Base64 serialized joint public key


class GameUpdateRequest(BaseModel):
    """Update agent with current game state"""
    phase: str  # "night", "day", "vote", "chat"
    message: str
    survivors: List[int]
    dead_players: List[int]
    remaining_time: Optional[int] = None  # Seconds remaining in chat phase


class ActionResponse(BaseModel):
    """Agent's encrypted action response - BLIND PROTOCOL
    
    All players send all three vectors for every night phase:
    - attack_vector: Real if Mafia, dummy otherwise
    - heal_vector: Real if Doctor, dummy otherwise  
    - investigate_vector: Real if Police, dummy otherwise
    
    Server cannot determine roles from network traffic patterns!
    """
    attack_vector: str  # Base64 encrypted vector
    heal_vector: str    # Base64 encrypted vector
    investigate_vector: str  # Base64 encrypted vector
    phase: str
    chat_messages: List[str] = []


class ChatBroadcast(BaseModel):
    """P2P chat broadcast"""
    msg_id: int
    player_index: int
    message: str
    phase: str
    turn: int
