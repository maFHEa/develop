"""
Homomorphic Encryption & Security Utilities
OpenFHE-based Threshold FHE for secure distributed game actions
"""
from openfhe import *
import base64
import tempfile
import os
from typing import List, Tuple, Optional


# ============================================================================
# OpenFHE Context & Parameters
# ============================================================================

def create_openfhe_context(num_parties: int):
    """
    Create BFVrns context for threshold FHE with small integer operations.

    Args:
        num_parties: Total number of parties participating in threshold scheme

    Returns:
        OpenFHE CryptoContext configured for multiparty operations
    """
    parameters = CCParamsBFVRNS()
    
    # Use smaller plaintext modulus for better noise management with small values
    parameters.SetPlaintextModulus(65537)  # Keep as prime
    
    # Batch size must be power of 2 for BFV
    parameters.SetBatchSize(8)  # Support up to 8 players
    
    # Increase multiplicative depth for EvalMult operations
    parameters.SetMultiplicativeDepth(2)
    
    # Threshold FHE settings
    parameters.SetThresholdNumOfParties(num_parties)
    parameters.SetMultipartyMode(NOISE_FLOODING_MULTIPARTY)

    cc = GenCryptoContext(parameters)
    cc.Enable(PKESchemeFeature.PKE)
    cc.Enable(PKESchemeFeature.KEYSWITCH)
    cc.Enable(PKESchemeFeature.LEVELEDSHE)
    cc.Enable(PKESchemeFeature.ADVANCEDSHE)  # CRITICAL: Required for EvalMult
    cc.Enable(PKESchemeFeature.MULTIPARTY)

    return cc


# ============================================================================
# Distributed Key Generation (DKG)
# ============================================================================

def dkg_keygen_lead(cc):
    """
    Lead party generates initial keypair for DKG.

    Args:
        cc: CryptoContext

    Returns:
        KeyPair containing public and secret keys
    """
    return cc.KeyGen()


def dkg_keygen_join(cc, prev_public_key):
    """
    Subsequent parties join DKG with previous public key.

    Args:
        cc: CryptoContext
        prev_public_key: Public key from previous party

    Returns:
        KeyPair with updated joint public key
    """
    return cc.MultipartyKeyGen(prev_public_key)


# ============================================================================
# Serialization (File-based for reliability)
# ============================================================================

def _serialize_to_base64(obj, serialize_func) -> str:
    """
    Helper: Serialize OpenFHE object to base64 string via temp file.
    """
    with tempfile.NamedTemporaryFile(delete=False, suffix='.bin') as f:
        temp_path = f.name

    try:
        result = serialize_func(temp_path)
        if not result:
            raise RuntimeError(f"Serialization failed for {type(obj)}")

        with open(temp_path, 'rb') as f:
            data = f.read()

        return base64.b64encode(data).decode('utf-8')
    finally:
        if os.path.exists(temp_path):
            os.remove(temp_path)


def _deserialize_from_base64(b64_str: str, deserialize_func):
    """
    Helper: Deserialize OpenFHE object from base64 string via temp file.
    """
    data = base64.b64decode(b64_str)

    with tempfile.NamedTemporaryFile(delete=False, suffix='.bin') as f:
        f.write(data)
        temp_path = f.name

    try:
        obj, success = deserialize_func(temp_path)
        if not success:
            raise RuntimeError("Deserialization failed")
        return obj
    finally:
        if os.path.exists(temp_path):
            os.remove(temp_path)


def serialize_crypto_context(cc) -> str:
    """
    Serialize CryptoContext to base64 string.
    """
    return _serialize_to_base64(cc, lambda path: SerializeToFile(path, cc, BINARY))


def deserialize_crypto_context(cc_b64: str):
    """
    Deserialize CryptoContext from base64 string.
    Note: You must call cc.Enable() on features after deserialization.
    """
    cc = _deserialize_from_base64(cc_b64, lambda path: DeserializeCryptoContext(path, BINARY))
    # Re-enable features
    cc.Enable(PKESchemeFeature.PKE)
    cc.Enable(PKESchemeFeature.KEYSWITCH)
    cc.Enable(PKESchemeFeature.LEVELEDSHE)
    cc.Enable(PKESchemeFeature.MULTIPARTY)
    return cc


def serialize_public_key(cc, public_key) -> str:
    """
    Serialize public key to base64 string.
    """
    return _serialize_to_base64(public_key, lambda path: SerializeToFile(path, public_key, BINARY))


def deserialize_public_key(cc, pk_b64: str):
    """
    Deserialize public key from base64 string.
    """
    return _deserialize_from_base64(pk_b64, lambda path: DeserializePublicKey(path, BINARY))


def serialize_eval_mult_key(cc, eval_mult_key) -> str:
    """
    Serialize evaluation multiplication key object to base64 string.
    """
    # Use Serialize to get binary data directly
    binary_data = Serialize(eval_mult_key, BINARY)
    if not binary_data:
        raise RuntimeError("Failed to serialize eval mult key")
    
    # Encode to base64 for transmission
    return base64.b64encode(binary_data).decode('utf-8')


def deserialize_eval_mult_key_object(cc, key_b64: str):
    """
    Deserialize evaluation multiplication key from base64 string and return the object.
    Does NOT insert into context - returns the key object for MultiAddEvalMultKeys.
    """
    # Decode base64 to binary data
    data = base64.b64decode(key_b64)
    
    # DeserializeEvalKeyString returns the key object directly
    eval_mult_key = DeserializeEvalKeyString(data, BINARY)
    if eval_mult_key is None:
        raise RuntimeError("Failed to deserialize eval mult key")
    
    return eval_mult_key


def deserialize_eval_mult_key(cc, key_b64: str):
    """
    Deserialize evaluation multiplication key from base64 string and insert into context.
    Legacy function - kept for compatibility.
    """
    data = base64.b64decode(key_b64)
    
    with tempfile.NamedTemporaryFile(delete=False, suffix='.bin') as f:
        f.write(data)
        temp_path = f.name
    
    try:
        # DeserializeEvalMultKey automatically inserts into the context
        if not cc.DeserializeEvalMultKey(temp_path, BINARY):
            raise RuntimeError("Failed to deserialize eval mult key")
        return True
    finally:
        if os.path.exists(temp_path):
            os.remove(temp_path)


def serialize_ciphertext(cc, ciphertext) -> str:
    """
    Serialize ciphertext to base64 string.
    """
    return _serialize_to_base64(ciphertext, lambda path: SerializeToFile(path, ciphertext, BINARY))


def deserialize_ciphertext(cc, ct_b64: str):
    """
    Deserialize ciphertext from base64 string.
    """
    return _deserialize_from_base64(ct_b64, lambda path: DeserializeCiphertext(path, BINARY))


# ============================================================================
# Threshold Decryption
# ============================================================================

def partial_decrypt_lead(cc, ciphertext, secret_key):
    """
    Lead party's partial decryption.

    Args:
        cc: CryptoContext
        ciphertext: Encrypted data
        secret_key: Lead party's secret key

    Returns:
        Partial ciphertext (decryption share)
    """
    result = cc.MultipartyDecryptLead([ciphertext], secret_key)
    return result[0]


def partial_decrypt_main(cc, ciphertext, secret_key):
    """
    Non-lead party's partial decryption.

    Args:
        cc: CryptoContext
        ciphertext: Encrypted data
        secret_key: Party's secret key

    Returns:
        Partial ciphertext (decryption share)
    """
    result = cc.MultipartyDecryptMain([ciphertext], secret_key)
    return result[0]


def fusion_decrypt(cc, partial_ciphertexts):
    """
    Combine partial decryptions to get final plaintext.

    Args:
        cc: CryptoContext
        partial_ciphertexts: List of partial decryption results from all parties

    Returns:
        Decrypted plaintext
    """
    return cc.MultipartyDecryptFusion(partial_ciphertexts)


# ============================================================================
# Vector Operations (Game Actions)
# ============================================================================

def create_zero_vector(size: int, cc, public_key):
    """
    Create an encrypted zero vector for dummy traffic (Anti-Traffic-Analysis).

    This is CRITICAL for security: All players must send encrypted data
    even when they have no action, to prevent network analysis attacks.

    Args:
        size: Vector dimension (number of players)
        cc: CryptoContext
        public_key: Joint public key for encryption

    Returns:
        Encrypted zero vector
    """
    plaintext = cc.MakePackedPlaintext([0] * size)
    return cc.Encrypt(public_key, plaintext)


def create_random_dummy_vector(size: int, cc, public_key):
    """
    Create an encrypted ZERO vector for blind protocol.
    
    When a player doesn't have an action for a specific vector slot,
    they submit a zero vector to maintain blind protocol.
    
    Args:
        size: Vector dimension (number of players)
        cc: CryptoContext
        public_key: Joint public key for encryption
        
    Returns:
        Encrypted zero vector
    """
    # Return zero vector (player has no action for this slot)
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
    if 0 <= target_index < size:
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
