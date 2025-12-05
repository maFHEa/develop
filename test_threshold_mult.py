#!/usr/bin/env python3
"""
Threshold FHE Multiplication Test
Based on OpenFHE official example: threshold-fhe.py (BFVrns section)

Tests the exact same structure as the game:
- 5 parties perform DKG
- Each submits encrypted attack/heal vectors
- Aggregate and compute: Killed = Attack * (1 - Heal)
- Threshold decrypt final result

Goal: Verify that multiplication works in threshold setting
"""

from openfhe import *
from math import log2


def test_threshold_multiplication():
    """
    Test threshold FHE multiplication following official OpenFHE example.
    Simulates game night phase: 5 players, attacks and heals aggregated.
    """
    print("\n" + "="*70)
    print(" THRESHOLD FHE MULTIPLICATION TEST (5 parties)")
    print("="*70)
    
    num_players = 5
    batchSize = 8  # Must be power of 2 for BFV
    
    # ========================================================================
    # Step 1: Setup - Same as official example
    # ========================================================================
    print("\n[1] Setting up BFVrns context...")
    parameters = CCParamsBFVRNS()
    parameters.SetPlaintextModulus(65537)
    parameters.SetBatchSize(batchSize)
    parameters.SetMultiplicativeDepth(2)  # Need depth for multiplication
    parameters.SetMultipartyMode(NOISE_FLOODING_MULTIPARTY)
    
    cc = GenCryptoContext(parameters)
    cc.Enable(PKE)
    cc.Enable(KEYSWITCH)
    cc.Enable(LEVELEDSHE)
    cc.Enable(ADVANCEDSHE)
    cc.Enable(MULTIPARTY)
    
    print(f"   Plaintext modulus: {cc.GetPlaintextModulus()}")
    print(f"   Ring dimension: {cc.GetCyclotomicOrder()/2}")
    print(f"   log2(q): {log2(cc.GetModulus()):.1f}")
    
    # ========================================================================
    # Step 2: DKG - Generate joint public key (Round 1)
    # ========================================================================
    print("\n[2] Distributed Key Generation...")
    print("   Round 1: Party A generates lead key")
    kp1 = cc.KeyGen()
    
    print("   Round 1: Party B joins")
    kp2 = cc.MultipartyKeyGen(kp1.publicKey)
    
    print("   Round 1: Parties C, D, E join")
    kp3 = cc.MultipartyKeyGen(kp2.publicKey)
    kp4 = cc.MultipartyKeyGen(kp3.publicKey)
    kp5 = cc.MultipartyKeyGen(kp4.publicKey)
    
    joint_public_key = kp5.publicKey
    print(f"   ✓ Joint public key established (5-of-5 threshold)")
    
    # ========================================================================
    # Step 3: Evaluation Key Generation (3-round protocol)
    # ========================================================================
    print("\n[3] Generating evaluation multiplication keys...")
    
    # Round 2: Each party generates KeySwitch key
    print("   Round 2: Generating KeySwitch keys...")
    evalMultKey = cc.KeySwitchGen(kp1.secretKey, kp1.secretKey)
    evalMultKey2 = cc.MultiKeySwitchGen(kp2.secretKey, kp2.secretKey, evalMultKey)
    evalMultKey3 = cc.MultiKeySwitchGen(kp3.secretKey, kp3.secretKey, evalMultKey)
    evalMultKey4 = cc.MultiKeySwitchGen(kp4.secretKey, kp4.secretKey, evalMultKey)
    evalMultKey5 = cc.MultiKeySwitchGen(kp5.secretKey, kp5.secretKey, evalMultKey)
    
    # Combine KeySwitch keys
    print("   Round 2: Combining KeySwitch keys...")
    evalMultAB = cc.MultiAddEvalKeys(evalMultKey, evalMultKey2, kp2.publicKey.GetKeyTag())
    evalMultABC = cc.MultiAddEvalKeys(evalMultAB, evalMultKey3, kp3.publicKey.GetKeyTag())
    evalMultABCD = cc.MultiAddEvalKeys(evalMultABC, evalMultKey4, kp4.publicKey.GetKeyTag())
    evalMultABCDE = cc.MultiAddEvalKeys(evalMultABCD, evalMultKey5, kp5.publicKey.GetKeyTag())
    
    # Round 3: Each party generates MultiMult key
    print("   Round 3: Generating MultiMult keys...")
    evalMultAABCDE = cc.MultiMultEvalKey(kp1.secretKey, evalMultABCDE, kp5.publicKey.GetKeyTag())
    evalMultBABCDE = cc.MultiMultEvalKey(kp2.secretKey, evalMultABCDE, kp5.publicKey.GetKeyTag())
    evalMultCABCDE = cc.MultiMultEvalKey(kp3.secretKey, evalMultABCDE, kp5.publicKey.GetKeyTag())
    evalMultDABCDE = cc.MultiMultEvalKey(kp4.secretKey, evalMultABCDE, kp5.publicKey.GetKeyTag())
    evalMultEABCDE = cc.MultiMultEvalKey(kp5.secretKey, evalMultABCDE, kp5.publicKey.GetKeyTag())
    
    # Combine MultiMult keys
    print("   Round 3: Combining MultiMult keys...")
    evalMultAB_final = cc.MultiAddEvalMultKeys(evalMultAABCDE, evalMultBABCDE, evalMultAABCDE.GetKeyTag())
    evalMultABC_final = cc.MultiAddEvalMultKeys(evalMultAB_final, evalMultCABCDE, evalMultAB_final.GetKeyTag())
    evalMultABCD_final = cc.MultiAddEvalMultKeys(evalMultABC_final, evalMultDABCDE, evalMultABC_final.GetKeyTag())
    evalMultFinal = cc.MultiAddEvalMultKeys(evalMultABCD_final, evalMultEABCDE, evalMultABCD_final.GetKeyTag())
    
    # Insert final mult key into context
    cc.InsertEvalMultKey([evalMultFinal])
    print("   ✓ Evaluation multiplication key installed")
    
    # ========================================================================
    # Step 4: Simulate Game Night Phase
    # ========================================================================
    print("\n[4] Simulating night phase...")
    print("   Scenario: Player 2 (mafia) attacks Player 1")
    print("            Player 3 (doctor) heals Player 1")
    
    # Each player submits attack and heal vectors
    # Player 0 (human - citizen): [0,0,0,0,0], [0,0,0,0,0]
    attack_0 = [0, 0, 0, 0, 0]
    heal_0 = [0, 0, 0, 0, 0]
    
    # Player 1 (AI - citizen): [0,0,0,0,0], [0,0,0,0,0]
    attack_1 = [0, 0, 0, 0, 0]
    heal_1 = [0, 0, 0, 0, 0]
    
    # Player 2 (AI - mafia): [0,1,0,0,0], [0,0,0,0,0] - attacks player 1
    attack_2 = [0, 1, 0, 0, 0]
    heal_2 = [0, 0, 0, 0, 0]
    
    # Player 3 (AI - doctor): [0,0,0,0,0], [0,1,0,0,0] - heals player 1
    attack_3 = [0, 0, 0, 0, 0]
    heal_3 = [0, 1, 0, 0, 0]
    
    # Player 4 (AI - citizen): [0,0,0,0,0], [0,0,0,0,0]
    attack_4 = [0, 0, 0, 0, 0]
    heal_4 = [0, 0, 0, 0, 0]
    
    # Encrypt all vectors with joint public key
    print("   Encrypting action vectors...")
    ct_attack_0 = cc.Encrypt(joint_public_key, cc.MakePackedPlaintext(attack_0))
    ct_heal_0 = cc.Encrypt(joint_public_key, cc.MakePackedPlaintext(heal_0))
    
    ct_attack_1 = cc.Encrypt(joint_public_key, cc.MakePackedPlaintext(attack_1))
    ct_heal_1 = cc.Encrypt(joint_public_key, cc.MakePackedPlaintext(heal_1))
    
    ct_attack_2 = cc.Encrypt(joint_public_key, cc.MakePackedPlaintext(attack_2))
    ct_heal_2 = cc.Encrypt(joint_public_key, cc.MakePackedPlaintext(heal_2))
    
    ct_attack_3 = cc.Encrypt(joint_public_key, cc.MakePackedPlaintext(attack_3))
    ct_heal_3 = cc.Encrypt(joint_public_key, cc.MakePackedPlaintext(heal_3))
    
    ct_attack_4 = cc.Encrypt(joint_public_key, cc.MakePackedPlaintext(attack_4))
    ct_heal_4 = cc.Encrypt(joint_public_key, cc.MakePackedPlaintext(heal_4))
    
    # ========================================================================
    # Step 5: Aggregate (Homomorphic Addition)
    # ========================================================================
    print("\n[5] Aggregating encrypted vectors...")
    total_attacks = cc.EvalAdd(ct_attack_0, ct_attack_1)
    total_attacks = cc.EvalAdd(total_attacks, ct_attack_2)
    total_attacks = cc.EvalAdd(total_attacks, ct_attack_3)
    total_attacks = cc.EvalAdd(total_attacks, ct_attack_4)
    
    total_heals = cc.EvalAdd(ct_heal_0, ct_heal_1)
    total_heals = cc.EvalAdd(total_heals, ct_heal_2)
    total_heals = cc.EvalAdd(total_heals, ct_heal_3)
    total_heals = cc.EvalAdd(total_heals, ct_heal_4)
    
    print("   ✓ Aggregation complete")
    
    # ========================================================================
    # Step 6: Compute Killed = Attack * (1 - Heal)
    # ========================================================================
    print("\n[6] Computing kill vector: Killed = Attack * (1 - Heal)")
    
    # Step 6a: Compute (1 - Heal)
    ones_plaintext = cc.MakePackedPlaintext([1, 1, 1, 1, 1, 0, 0, 0])
    neg_heal = cc.EvalNegate(total_heals)
    one_minus_heal = cc.EvalAdd(neg_heal, ones_plaintext)
    print("   ✓ Computed (1 - Heal)")
    
    # Step 6b: Multiply Attack * (1 - Heal) - THIS IS THE CRITICAL TEST
    print("   ⚠ Attempting EvalMult (this is where we were failing)...")
    killed_encrypted = cc.EvalMult(total_attacks, one_minus_heal)
    print("   ✓ EvalMult succeeded!")
    
    # ========================================================================
    # Step 7: Threshold Decryption
    # ========================================================================
    print("\n[7] Threshold decryption of result...")
    
    partial1 = cc.MultipartyDecryptLead([killed_encrypted], kp1.secretKey)
    partial2 = cc.MultipartyDecryptMain([killed_encrypted], kp2.secretKey)
    partial3 = cc.MultipartyDecryptMain([killed_encrypted], kp3.secretKey)
    partial4 = cc.MultipartyDecryptMain([killed_encrypted], kp4.secretKey)
    partial5 = cc.MultipartyDecryptMain([killed_encrypted], kp5.secretKey)
    
    partial_vec = [partial1[0], partial2[0], partial3[0], partial4[0], partial5[0]]
    result_plaintext = cc.MultipartyDecryptFusion(partial_vec)
    result_plaintext.SetLength(batchSize)
    
    # ========================================================================
    # Step 8: Verify Result
    # ========================================================================
    print("\n[8] RESULTS:")
    print("="*70)
    
    result_vec = result_plaintext.GetPackedValue()
    print(f"   Killed vector: {result_vec[:5]}")  # Only show first 5 slots
    print(f"   Expected:      [0, 0, 0, 0, 0]  (player 1 was saved by doctor)")
    
    expected = [0, 0, 0, 0, 0]
    if result_vec[:5] == expected:
        print("\n   ✅ SUCCESS! Multiplication works correctly in threshold FHE!")
        print("   Player 1 was attacked but healed → survived")
        return True
    else:
        print(f"\n   ❌ FAILED! Got {result_vec}, expected {expected}")
        return False


def test_without_heal():
    """
    Second test: Attack without heal (player should die)
    """
    print("\n" + "="*70)
    print(" TEST 2: Attack without heal")
    print("="*70)
    
    num_players = 5
    batchSize = 8  # Must be power of 2
    
    # Setup (same as before)
    parameters = CCParamsBFVRNS()
    parameters.SetPlaintextModulus(65537)
    parameters.SetBatchSize(batchSize)
    parameters.SetMultiplicativeDepth(2)
    parameters.SetMultipartyMode(NOISE_FLOODING_MULTIPARTY)
    
    cc = GenCryptoContext(parameters)
    cc.Enable(PKE)
    cc.Enable(KEYSWITCH)
    cc.Enable(LEVELEDSHE)
    cc.Enable(ADVANCEDSHE)
    cc.Enable(MULTIPARTY)
    
    # DKG
    kp1 = cc.KeyGen()
    kp2 = cc.MultipartyKeyGen(kp1.publicKey)
    kp3 = cc.MultipartyKeyGen(kp2.publicKey)
    kp4 = cc.MultipartyKeyGen(kp3.publicKey)
    kp5 = cc.MultipartyKeyGen(kp4.publicKey)
    
    # Mult keys (3-round protocol)
    evalMultKey = cc.KeySwitchGen(kp1.secretKey, kp1.secretKey)
    evalMultKey2 = cc.MultiKeySwitchGen(kp2.secretKey, kp2.secretKey, evalMultKey)
    evalMultKey3 = cc.MultiKeySwitchGen(kp3.secretKey, kp3.secretKey, evalMultKey)
    evalMultKey4 = cc.MultiKeySwitchGen(kp4.secretKey, kp4.secretKey, evalMultKey)
    evalMultKey5 = cc.MultiKeySwitchGen(kp5.secretKey, kp5.secretKey, evalMultKey)
    
    evalMultAB = cc.MultiAddEvalKeys(evalMultKey, evalMultKey2, kp2.publicKey.GetKeyTag())
    evalMultABC = cc.MultiAddEvalKeys(evalMultAB, evalMultKey3, kp3.publicKey.GetKeyTag())
    evalMultABCD = cc.MultiAddEvalKeys(evalMultABC, evalMultKey4, kp4.publicKey.GetKeyTag())
    evalMultABCDE = cc.MultiAddEvalKeys(evalMultABCD, evalMultKey5, kp5.publicKey.GetKeyTag())
    
    evalMultAABCDE = cc.MultiMultEvalKey(kp1.secretKey, evalMultABCDE, kp5.publicKey.GetKeyTag())
    evalMultBABCDE = cc.MultiMultEvalKey(kp2.secretKey, evalMultABCDE, kp5.publicKey.GetKeyTag())
    evalMultCABCDE = cc.MultiMultEvalKey(kp3.secretKey, evalMultABCDE, kp5.publicKey.GetKeyTag())
    evalMultDABCDE = cc.MultiMultEvalKey(kp4.secretKey, evalMultABCDE, kp5.publicKey.GetKeyTag())
    evalMultEABCDE = cc.MultiMultEvalKey(kp5.secretKey, evalMultABCDE, kp5.publicKey.GetKeyTag())
    
    evalMultAB_final = cc.MultiAddEvalMultKeys(evalMultAABCDE, evalMultBABCDE, evalMultAABCDE.GetKeyTag())
    evalMultABC_final = cc.MultiAddEvalMultKeys(evalMultAB_final, evalMultCABCDE, evalMultAB_final.GetKeyTag())
    evalMultABCD_final = cc.MultiAddEvalMultKeys(evalMultABC_final, evalMultDABCDE, evalMultABC_final.GetKeyTag())
    evalMultFinal = cc.MultiAddEvalMultKeys(evalMultABCD_final, evalMultEABCDE, evalMultABCD_final.GetKeyTag())
    
    cc.InsertEvalMultKey([evalMultFinal])
    
    # Test scenario: Player 2 attacks Player 1, NO heal
    print("   Scenario: Player 2 attacks Player 1, NO heal")
    
    attack_total = [0, 1, 0, 0, 0]  # Player 1 attacked
    heal_total = [0, 0, 0, 0, 0]     # No one healed
    
    ct_attack = cc.Encrypt(kp5.publicKey, cc.MakePackedPlaintext(attack_total))
    ct_heal = cc.Encrypt(kp5.publicKey, cc.MakePackedPlaintext(heal_total))
    
    # Compute Killed = Attack * (1 - Heal)
    ones = cc.MakePackedPlaintext([1, 1, 1, 1, 1, 0, 0, 0])
    one_minus_heal = cc.EvalAdd(cc.EvalNegate(ct_heal), ones)
    killed = cc.EvalMult(ct_attack, one_minus_heal)
    
    # Decrypt
    partial1 = cc.MultipartyDecryptLead([killed], kp1.secretKey)
    partial2 = cc.MultipartyDecryptMain([killed], kp2.secretKey)
    partial3 = cc.MultipartyDecryptMain([killed], kp3.secretKey)
    partial4 = cc.MultipartyDecryptMain([killed], kp4.secretKey)
    partial5 = cc.MultipartyDecryptMain([killed], kp5.secretKey)
    
    result = cc.MultipartyDecryptFusion([partial1[0], partial2[0], partial3[0], partial4[0], partial5[0]])
    result.SetLength(batchSize)
    
    result_vec = result.GetPackedValue()
    expected = [0, 1, 0, 0, 0]  # Player 1 killed
    
    print(f"   Killed vector: {result_vec[:5]}")  # Only show first 5
    print(f"   Expected:      {expected}  (player 1 dies)")
    
    if result_vec[:5] == expected:
        print("\n   ✅ SUCCESS! Player correctly killed")
        return True
    else:
        print(f"\n   ❌ FAILED!")
        return False


if __name__ == "__main__":
    print("\n" + "="*70)
    print(" THRESHOLD FHE MULTIPLICATION TEST SUITE")
    print(" Following OpenFHE official threshold-fhe.py example")
    print("="*70)
    
    test1_pass = test_threshold_multiplication()
    test2_pass = test_without_heal()
    
    print("\n" + "="*70)
    print(" FINAL RESULTS:")
    print("="*70)
    print(f"   Test 1 (Attack + Heal = Survive): {'✅ PASS' if test1_pass else '❌ FAIL'}")
    print(f"   Test 2 (Attack + No Heal = Die):  {'✅ PASS' if test2_pass else '❌ FAIL'}")
    
    if test1_pass and test2_pass:
        print("\n   🎉 ALL TESTS PASSED!")
        print("   Threshold multiplication is working correctly.")
        print("   The issue in the game must be with key generation/distribution.")
    else:
        print("\n   ⚠️  SOME TESTS FAILED")
        print("   Threshold multiplication protocol needs debugging.")
    
    print("="*70)
