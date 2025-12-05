"""
Investigation Result Model
For sending police investigation results to agents
"""
from pydantic import BaseModel


class InvestigationResult(BaseModel):
    """Police investigation result notification"""
    target_index: int  # Who was investigated
    is_mafia: bool     # Investigation result
    turn: int          # When the investigation happened
