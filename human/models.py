"""
Game Models - Player data structure
"""
from typing import Optional


class Player:
    """
    Represents a player in the game.
    
    BLIND PROTOCOL: Server does NOT store plaintext roles.
    Each player only knows their own role (via private channel).
    Server only stores encrypted_role_vector for threshold decryption.
    """
    def __init__(self, index: int, is_human: bool, address: Optional[str] = None):
        self.index = index
        self.is_human = is_human
        self.address = address
        self.alive = True
        self.name = f"Human (You)" if is_human else f"AI Agent {index}"
        
        # Encrypted role vector (only used for win condition check)
        self.encrypted_role_vector: Optional[str] = None
