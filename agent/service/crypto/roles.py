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

NUM_ROLE_TYPES = 4  # citizen, mafia, doctor, police


def role_to_one_hot(role: str) -> List[int]:
    """
    Convert role to one-hot vector.
    
    Args:
        role: Role name
    
    Returns:
        One-hot vector of length NUM_ROLE_TYPES
        Example: "mafia" -> [0, 1, 0, 0]
    """
    vector = [0] * NUM_ROLE_TYPES
    role_index = ROLE_ENCODING[role.lower()]
    vector[role_index] = 1
    return vector


def one_hot_to_role(vector: List[int]) -> str:
    """
    Convert one-hot vector to role name.
    
    Args:
        vector: One-hot vector
    
    Returns:
        Role name
    """
    for i, val in enumerate(vector):
        if val == 1:
            return ROLE_DECODING[i]
    return "unknown"


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
