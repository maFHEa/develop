"""
Agent Models Package

Provides all Pydantic models for agent-server communication.
Re-exports for backward compatibility.
"""

# DKG Models
from .dkg import (
    DKGSetupRequest,
    DKGSetupResponse,
    DKGRoundRequest,
    DKGRoundResponse,
    PartialDecryptRequest,
    PartialDecryptResponse,
    RoleAssignmentRequest,
)

# Game Models
from .game import InitRequest, GameUpdateRequest

# Action Models
from .action import ActionResponse

# Chat Models (Pydantic)
from .chat_models import ChatBroadcast

from .chat import GameChatHistory

# Chat Classes (not exported - use from chat directly)
# from .chat import ChatMessage, GameChatHistory

__all__ = [
    # DKG
    "DKGSetupRequest",
    "DKGSetupResponse",
    "DKGRoundRequest",
    "DKGRoundResponse",
    "PartialDecryptRequest",
    "PartialDecryptResponse",
    "RoleAssignmentRequest",
    # Game
    "InitRequest",
    "GameUpdateRequest",
    # Action
    "ActionResponse",
    # Chat
    "ChatBroadcast",
    "GameChatHistory",
]
