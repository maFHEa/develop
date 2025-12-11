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