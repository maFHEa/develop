"""
Configuration for Human Host & Player
"""
from typing import Dict, Any


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
    "openai_api_key": "",  # 여기에 API 키 설정하거나 실행 시 입력
    
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
