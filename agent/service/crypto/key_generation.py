from openfhe import *

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