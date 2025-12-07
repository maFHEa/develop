import logging
import httpx
import asyncio

from service.crypto.roles import NUM_ROLE_TYPES
from service.crypto.serialization import deserialize_ciphertext, serialize_ciphertext
from service.crypto.threshold_decryption import fusion_decrypt, partial_decrypt_main
from service.crypto.vector_operations import homomorphic_dot_product

# Configure logger for agent_service module
logger = logging.getLogger("agent_service")
logger.setLevel(logging.INFO)

async def _execute_police_investigation(state, target_index: int) -> str:
    """
    Execute police investigation using parallel threshold decryption.
    Returns investigation result immediately.
    """
    logger.info(f"🔍 Police investigating Player {target_index} via parallel decrypt...")
    
    # Get target's encrypted role
    target_role_enc_b64 = state.all_encrypted_roles[target_index]
    target_role_enc = deserialize_ciphertext(state.cc, target_role_enc_b64)
    
    # Compute mafia check: role_vector · [0,1,0,0]
    mafia_check_vector = [0, 1, 0, 0]
    investigate_result_enc = homomorphic_dot_product(state.cc, target_role_enc, mafia_check_vector)
    investigate_result_b64 = serialize_ciphertext(state.cc, investigate_result_enc)
    
    # Parallel decrypt: My partial + collect from all others
    my_partial = partial_decrypt_main(state.cc, investigate_result_enc, state.keypair.secretKey)
    all_partials = [my_partial]
    
    # Collect partials from all other players in parallel
    async def collect_partial(player_idx: int, address: str):
        if address is None:
            return None
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                response = await client.post(
                    f"{address}/investigate_parallel",
                    json={"ciphertext": investigate_result_b64}
                )
                response.raise_for_status()
                return response.json()["partial_result"]
        except Exception as e:
            logger.error(f"Failed to get partial from player {player_idx}: {e}")
            return None
    
    # Build player addresses
    player_addresses = []
    for i in range(state.num_players):
        if i == 0:
            player_addresses.append("http://localhost:9000")
        elif i == state.player_index:
            player_addresses.append(None)  # Skip self
        else:
            # Get from state or estimate
            if hasattr(state, 'player_addresses') and state.player_addresses:
                player_addresses.append(state.player_addresses[i])
            else:
                # Fallback: estimate based on port
                player_addresses.append(f"http://localhost:{8764 + i}")
    
    # Collect all partials in parallel
    tasks = []
    for i in range(state.num_players):
        if i != state.player_index and player_addresses[i]:
            tasks.append(collect_partial(i, player_addresses[i]))
    
    if tasks:
        partial_results = await asyncio.gather(*tasks)
        for partial_b64 in partial_results:
            if partial_b64:
                partial = deserialize_ciphertext(state.cc, partial_b64)
                all_partials.append(partial)
    
    # Fusion decrypt
    final_result = fusion_decrypt(state.cc, all_partials)
    decrypted_vector = final_result.GetPackedValue()
    
    # DEBUG: Log the decrypted vector
    logger.info(f"🔍 DEBUG - Decrypted vector (first 4): {decrypted_vector[:4]}")
    logger.info(f"🔍 DEBUG - Sum: {sum(decrypted_vector[:NUM_ROLE_TYPES])}")
    
    is_mafia = sum(decrypted_vector[:NUM_ROLE_TYPES]) >= 1
    
    # Record the result
    from suspicion import PoliceNoteManager
    if isinstance(state.suspicion_notes, PoliceNoteManager):
        state.suspicion_notes.add_investigation_result(
            target_index=target_index,
            is_mafia=is_mafia,
            current_turn=state.current_turn
        )
    
    state.pending_action_target = target_index
    state.action_submitted = True
    
    result_text = "🎭 MAFIA" if is_mafia else "✅ NOT MAFIA (Citizen/Doctor/Police)"
    logger.info(f"✅ Investigation complete: Player {target_index} is {result_text}")
    
    # Return clear message for AI
    return f"🔍 INVESTIGATION RESULT: Player {target_index} is {result_text}. This has been saved to your suspicion notes. Use this information strategically!"
