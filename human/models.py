"""
Game Models - Player data structure
"""
from typing import Optional


class Player:
    """Represents a player in the game"""
    def __init__(self, index: int, role: str, is_human: bool, address: Optional[str] = None):
        self.index = index
        self.role = role
        self.is_human = is_human
        self.address = address
        self.alive = True
        self.name = f"Human (You)" if is_human else f"AI Agent {index}"
