"""
Crypto Operations Service - Modular crypto operations for the game

Structure:
- coordinator.py: CryptoOperations (Facade)
- action_collector.py: Collects actions from all players
- vector_factory.py: Creates encrypted vectors
- decryption_service.py: Threshold decryption
- network_client.py: Agent communication
"""

from .coordinator import CryptoOperations

__all__ = ['CryptoOperations']
