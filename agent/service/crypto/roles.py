from typing import List

# ============================================================================
# Role Encoding/Decoding
# ============================================================================

ROLE_ENCODING = {
    "citizen": 0,
    "mafia": 1,
    "doctor": 2,
    "police": 3
}

ROLE_DECODING = {v: k for k, v in ROLE_ENCODING.items()}


def encode_roles(roles: List[str]) -> List[int]:
    """
    Encode role strings to integers.

    Args:
        roles: List of role names

    Returns:
        List of encoded integers
    """
    return [ROLE_ENCODING[role.lower()] for role in roles]


def decode_roles(encoded: List[int]) -> List[str]:
    """
    Decode role integers to strings.

    Args:
        encoded: List of encoded integers

    Returns:
        List of role names
    """
    return [ROLE_DECODING[code] for code in encoded]
