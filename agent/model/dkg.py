"""
DKG (Distributed Key Generation) Models

Models for distributed key generation protocol used in role assignment.
"""
from pydantic import BaseModel
from typing import Optional


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
