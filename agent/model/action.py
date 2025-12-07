"""
Action Response Models

Models for blind protocol action responses where all players send all action types.
"""
from pydantic import BaseModel
from typing import List


class ActionResponse(BaseModel):
    """Agent's encrypted action response - BLIND PROTOCOL
    
    All players send all three vectors for every night phase:
    - attack_vector: Real if Mafia, dummy otherwise
    - heal_vector: Real if Doctor, dummy otherwise  
    
    Server cannot determine roles from network traffic patterns!
    """
    vote_vector: str  # Base64 encrypted vector
    attack_vector: str  # Base64 encrypted vector
    heal_vector: str    # Base64 encrypted vector
    phase: str
    chat_messages: List[str] = []
