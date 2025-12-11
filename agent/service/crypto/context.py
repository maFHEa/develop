from openfhe import *


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