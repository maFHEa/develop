from openfhe import *
import base64
import tempfile
import os

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
    Uses direct binary serialization without temp files for efficiency.
    """
    binary_data = Serialize(eval_mult_key, BINARY)
    if not binary_data:
        raise RuntimeError("Failed to serialize eval mult key")
    return base64.b64encode(binary_data).decode('utf-8')


def deserialize_eval_mult_key_object(cc, key_b64: str):
    """
    Deserialize evaluation multiplication key from base64 string and return the object.
    Does NOT insert into context - returns the key object for MultiAddEvalMultKeys.
    """
    data = base64.b64decode(key_b64)
    eval_mult_key = DeserializeEvalKeyString(data, BINARY)
    if eval_mult_key is None:
        raise RuntimeError("Failed to deserialize eval mult key")
    return eval_mult_key


def deserialize_eval_mult_key(cc, key_b64: str):
    """
    Deserialize evaluation multiplication key and insert into context.
    This is a convenience wrapper around deserialize_eval_mult_key_object.
    """
    data = base64.b64decode(key_b64)
    with tempfile.NamedTemporaryFile(delete=False, suffix='.bin') as f:
        f.write(data)
        temp_path = f.name
    
    try:
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
