"""
Configuration for Human Host & Player
"""
from typing import Dict, Any
import os
from pathlib import Path


def _load_openai_api_key() -> str:
    """
    Load OPENAI_API_KEY from environment variables or the root .env file.
    Supports both underscore and dash separators.
    """
    for key in ("OPENAI_API_KEY", "OPENAI-API-KEY"):
        value = os.getenv(key)
        if value:
            return value.strip()

    env_path = Path(__file__).resolve().parent / ".env"
    if env_path.exists():
        try:
            with env_path.open("r", encoding="utf-8") as env_file:
                for raw_line in env_file:
                    line = raw_line.strip()
                    if not line or line.startswith("#"):
                        continue

                    if "=" in line and (":" not in line or line.index("=") < line.index(":")):
                        key, val = line.split("=", 1)
                    elif ":" in line:
                        key, val = line.split(":", 1)
                    else:
                        continue

                    key = key.strip()
                    val = val.strip().strip('"').strip("'")
                    if key in ("OPENAI_API_KEY", "OPENAI-API-KEY"):
                        return val
        except Exception:
            pass

    return ""


# Game Configuration
GAME_CONFIG: Dict[str, Any] = {
    # Game Rules
    "min_players": 4,
    "max_players": 10,
    
    # Role Distribution (for N players)
    "role_distribution": {
        4: {"mafia": 1, "doctor": 1, "police": 1, "citizen": 1},
        5: {"mafia": 1, "doctor": 1, "police": 1, "citizen": 2},
        6: {"mafia": 2, "doctor": 1, "police": 1, "citizen": 2},
        7: {"mafia": 2, "doctor": 1, "police": 1, "citizen": 3},
        8: {"mafia": 2, "doctor": 1, "police": 1, "citizen": 4},
        9: {"mafia": 3, "doctor": 1, "police": 1, "citizen": 4},
        10: {"mafia": 3, "doctor": 1, "police": 1, "citizen": 5},
    },
    
    # Phase Timeouts (seconds)
    "night_phase_timeout": 60,
    "day_phase_timeout": 120,
    "vote_phase_timeout": 60,
}


# Network Configuration
NETWORK_CONFIG: Dict[str, Any] = {
    # Lobby Server Addresses
    # 각 Lobby 서버가 게임용 Agent 1개씩 spawn함
    # 예: 4명 게임 = 3개 Lobby 필요
    "lobby_addresses": [
        "http://localhost:8000",
        "http://localhost:8001",
        "http://localhost:8002",
        "http://localhost:8003"
    ],
    
    # OpenAI API Key (모든 Agent가 사용)
    "openai_api_key": _load_openai_api_key(),
    
    # True면 config의 lobby_addresses 사용, False면 실행 시 입력
    "use_config_lobbies": True,
    
    "connection_timeout": 10,
    "action_request_timeout": 60,
}


# Cryptography Configuration
CRYPTO_CONFIG: Dict[str, Any] = {
    "scheme": "BFV",
    "poly_modulus_degree": 8192,
    "plain_modulus": 1032193,
}


# UI Configuration
UI_CONFIG: Dict[str, Any] = {
    "clear_screen": True,
    "show_debug": False,
}