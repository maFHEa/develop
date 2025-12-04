"""
Homomorphic Encryption & Security Utilities
Provides TenSEAL-based encryption for secure game actions
"""
import tenseal as ts
import base64
import json
from typing import List, Tuple


def create_tenseal_context() -> ts.Context:
    """
    Create BFV context with parameters suitable for Mafia game computations.
    
    Returns:
        TenSEAL context with public key (secret key retained on host)
    """
    context = ts.context(
        ts.SCHEME_TYPE.BFV,
        poly_modulus_degree=8192,  # Required for multiplication depth
        plain_modulus=1032193
    )
    context.generate_galois_keys()
    context.global_scale = 2**40
    return context


def serialize_context_public(context: ts.Context) -> str:
    """
    Serialize only the public components of the context.
    
    Args:
        context: Full TenSEAL context
        
    Returns:
        Base64-encoded public context
    """
    public_context = context.copy()
    public_context.make_context_public()
    return base64.b64encode(public_context.serialize()).decode('utf-8')


def deserialize_context(context_bytes: str) -> ts.Context:
    """
    Deserialize a TenSEAL context from base64 string.
    
    Args:
        context_bytes: Base64-encoded context
        
    Returns:
        TenSEAL context
    """
    return ts.context_from(base64.b64decode(context_bytes))


def create_zero_vector(size: int, context: ts.Context) -> ts.BFVVector:
    """
    Create an encrypted zero vector for dummy traffic (Anti-Traffic-Analysis).
    
    This is CRITICAL for security: All players must send encrypted data
    even when they have no action, to prevent network analysis attacks.
    
    Args:
        size: Vector dimension (number of players)
        context: TenSEAL context with public key
        
    Returns:
        Encrypted zero vector
    """
    zero_vector = [0] * size
    return ts.bfv_vector(context, zero_vector)


def create_one_hot_vector(size: int, target_index: int, context: ts.Context) -> ts.BFVVector:
    """
    Create an encrypted one-hot vector for targeting a specific player.
    
    Args:
        size: Vector dimension (number of players)
        target_index: Index of the target player (0-indexed)
        context: TenSEAL context with public key
        
    Returns:
        Encrypted one-hot vector
    """
    vector = [0] * size
    if 0 <= target_index < size:
        vector[target_index] = 1
    return ts.bfv_vector(context, vector)


def serialize_encrypted_vector(encrypted_vector: ts.BFVVector) -> str:
    """
    Serialize an encrypted vector to base64 string for network transmission.
    
    Args:
        encrypted_vector: TenSEAL BFV vector
        
    Returns:
        Base64-encoded encrypted vector
    """
    return base64.b64encode(encrypted_vector.serialize()).decode('utf-8')


def deserialize_encrypted_vector(vector_bytes: str, context: ts.Context) -> ts.BFVVector:
    """
    Deserialize an encrypted vector from base64 string.
    
    Args:
        vector_bytes: Base64-encoded encrypted vector
        context: TenSEAL context (must match the encryption context)
        
    Returns:
        TenSEAL BFV vector
    """
    return ts.bfv_vector_from(context, base64.b64decode(vector_bytes))


def aggregate_encrypted_vectors(vectors: List[ts.BFVVector]) -> ts.BFVVector:
    """
    Sum multiple encrypted vectors homomorphically.
    
    This is the core of the "blind" computation - the server aggregates
    without ever seeing individual player actions.
    
    Args:
        vectors: List of encrypted BFV vectors
        
    Returns:
        Sum of all vectors (still encrypted)
    """
    if not vectors:
        raise ValueError("Cannot aggregate empty vector list")
    
    result = vectors[0]
    for vec in vectors[1:]:
        result = result + vec
    return result


def multiply_encrypted_vectors(vec1: ts.BFVVector, vec2: ts.BFVVector) -> ts.BFVVector:
    """
    Multiply two encrypted vectors element-wise (homomorphic multiplication).
    
    Args:
        vec1: First encrypted vector
        vec2: Second encrypted vector
        
    Returns:
        Element-wise product (still encrypted)
    """
    return vec1 * vec2


def compute_killed_vector(
    attack_vector: ts.BFVVector,
    heal_vector: ts.BFVVector,
    context: ts.Context
) -> ts.BFVVector:
    """
    Compute who is killed: Attack AND NOT Healed.
    
    Formula: Killed = Attack * (1 - Heal)
    
    Args:
        attack_vector: Aggregated encrypted attack vector
        heal_vector: Aggregated encrypted heal vector
        context: TenSEAL context
        
    Returns:
        Encrypted kill result vector
    """
    # Create vector of ones
    ones = ts.bfv_vector(context, [1] * len(heal_vector.decrypt()))
    
    # Compute 1 - heal
    not_healed = ones - heal_vector
    
    # Attack * (1 - Heal)
    killed = multiply_encrypted_vectors(attack_vector, not_healed)
    
    return killed


def decrypt_vector(encrypted_vector: ts.BFVVector) -> List[int]:
    """
    Decrypt a vector to plaintext.
    
    SECURITY NOTE: Only the host with the secret key can do this.
    This should ONLY be called on aggregated results, never on individual inputs.
    
    Args:
        encrypted_vector: Encrypted BFV vector
        
    Returns:
        Plaintext integer list
    """
    return encrypted_vector.decrypt()


def dot_product_encrypted(vec1: ts.BFVVector, vec2: ts.BFVVector) -> ts.BFVVector:
    """
    Compute dot product of two encrypted vectors.
    
    Used for police investigation: Query vector · Role vector
    
    Args:
        vec1: First encrypted vector
        vec2: Second encrypted vector
        
    Returns:
        Encrypted scalar (as single-element vector)
    """
    product = multiply_encrypted_vectors(vec1, vec2)
    # Sum all elements (this returns encrypted scalar)
    decrypted = product.decrypt()
    return sum(decrypted)
