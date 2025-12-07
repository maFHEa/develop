from typing import List

# ============================================================================
# Vector Operations (Game Actions)
# ============================================================================

def create_zero_vector(size: int, cc, public_key):
    """
    Create an encrypted zero vector for dummy traffic (Anti-Traffic-Analysis).

    This is CRITICAL for security: All players must send encrypted data
    even when they have no action, to prevent network analysis attacks.
    
    Used in two contexts:
    1. Dummy traffic when player has no action
    2. Blind protocol - all players send encrypted vectors regardless of role

    Args:
        size: Vector dimension (number of players)
        cc: CryptoContext
        public_key: Joint public key for encryption

    Returns:
        Encrypted zero vector
    """
    plaintext = cc.MakePackedPlaintext([0] * size)
    return cc.Encrypt(public_key, plaintext)


def create_one_hot_vector(size: int, target_index: int, cc, public_key):
    """
    Create an encrypted one-hot vector for targeting a specific player.

    Args:
        size: Vector dimension (number of players)
        target_index: Index of the target player (0-indexed)
        cc: CryptoContext
        public_key: Joint public key for encryption

    Returns:
        Encrypted one-hot vector
    """
    vector = [0] * size
    if target_index is not None and 0 <= target_index < size:
        vector[target_index] = 1
    plaintext = cc.MakePackedPlaintext(vector)
    return cc.Encrypt(public_key, plaintext)


def aggregate_encrypted_vectors(cc, vectors: List):
    """
    Sum multiple encrypted vectors homomorphically.

    This is the core of the "blind" computation - the server aggregates
    without ever seeing individual player actions.

    Args:
        cc: CryptoContext
        vectors: List of encrypted vectors

    Returns:
        Sum of all vectors (still encrypted)
    """
    if not vectors:
        raise ValueError("Cannot aggregate empty vector list")

    result = vectors[0]
    for vec in vectors[1:]:
        result = cc.EvalAdd(result, vec)
    return result


def multiply_encrypted_vectors(cc, vec1, vec2):
    """
    Multiply two encrypted vectors element-wise (homomorphic multiplication).

    Args:
        cc: CryptoContext
        vec1: First encrypted vector
        vec2: Second encrypted vector

    Returns:
        Element-wise product (still encrypted)
    """
    return cc.EvalMult(vec1, vec2)


def subtract_from_ones(cc, size: int, public_key, vector):
    """
    Compute (1, 1, ..., 1) - vector homomorphically.
    
    Uses EvalSub with plaintext to avoid creating new ciphertext with different key tag.

    Args:
        cc: CryptoContext
        size: Vector dimension
        public_key: Public key (unused, kept for API compatibility)
        vector: Encrypted vector to subtract

    Returns:
        Encrypted result of ones - vector
    """
    # Create plaintext ones vector
    ones_plaintext = cc.MakePackedPlaintext([1] * size)
    
    # Negate the vector first: -vector
    neg_vector = cc.EvalNegate(vector)
    
    # Then add plaintext ones: 1 + (-vector) = 1 - vector
    result = cc.EvalAdd(neg_vector, ones_plaintext)
    
    return result


def compute_killed_vector(cc, attack_vector, heal_vector, size: int, public_key):
    """
    Compute who is killed: Attack AND NOT Healed.

    Formula: Killed = Attack * (1 - Heal)

    Args:
        cc: CryptoContext
        attack_vector: Aggregated encrypted attack vector
        heal_vector: Aggregated encrypted heal vector
        size: Vector dimension
        public_key: Public key

    Returns:
        Encrypted kill result vector
    """
    # Compute 1 - heal
    not_healed = subtract_from_ones(cc, size, public_key, heal_vector)

    # Attack * (1 - Heal)
    killed = multiply_encrypted_vectors(cc, attack_vector, not_healed)

    return killed


def homomorphic_dot_product(cc, encrypted_vector, plaintext_vector: List[int]):
    """
    Compute dot product between encrypted vector and plaintext vector.
    
    Used for police investigation: role_vector · mafia_check_vector
    
    Args:
        cc: CryptoContext
        encrypted_vector: Encrypted vector (e.g., role vector)
        plaintext_vector: Plaintext vector (e.g., [0, 1, 0, 0] for mafia check)
    
    Returns:
        Encrypted scalar result (dot product)
    """
    # Multiply encrypted vector with plaintext vector element-wise
    plaintext = cc.MakePackedPlaintext(plaintext_vector)
    result = cc.EvalMult(encrypted_vector, plaintext)
    
    # Sum all elements to get dot product
    # Since we can't easily sum encrypted vector elements, we use a rotation trick
    # For now, return the element-wise product (caller will sum after decryption)
    return result