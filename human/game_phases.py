"""
Game Phases - Night, Day, and Vote phase implementations
Handles game flow and phase-specific logic
"""
import sys
from typing import List, Optional

sys.path.append('../agent')

from service.crypto.serialization import deserialize_ciphertext, serialize_ciphertext
from service.crypto.vector_operations import (
    aggregate_encrypted_vectors,
    compute_killed_vector,
    multiply_encrypted_vectors,
    homomorphic_dot_product,
)
from service.crypto.roles import NUM_ROLE_TYPES


class GamePhases:
    """Manages game phases (night, day, vote)"""
    
    def __init__(self, crypto_ops, logger=None):
        self.crypto_ops = crypto_ops
        self.day_number = 0
        self.last_killed: List[int] = []
        self.last_voted_out: Optional[int] = None
        self.last_vote_counts: Optional[List[int]] = None
        self.logger = logger
    
    async def execute_night_phase(
        self,
        players,
        human_player_index: int,
        human_role: str,
        get_survivors_func,
        get_dead_func,
        get_human_action_callback,
        broadcast_callback,
        log_callback
    ):
        """Execute night phase with blind protocol"""
        self.day_number += 1
        
        print(f"\n{'#'*60}")
        print(f"NIGHT {self.day_number}")
        print(f"{'#'*60}")

        message = f"Night {self.day_number} has begun."
        log_callback(message)
        await broadcast_callback("night", message)

        survivors = get_survivors_func()
        dead = get_dead_func()

        print("[Engine] Collecting encrypted actions (3 vectors per player)...")
        attack_vectors, heal_vectors, investigate_vectors = await self.crypto_ops.collect_encrypted_actions(
            players, human_player_index, human_role, "night", message, survivors, dead, get_human_action_callback
        )

        print("[Engine] Deserializing attack vectors...")
        attacks_enc = [deserialize_ciphertext(self.crypto_ops.cc, enc) for enc in attack_vectors]
        
        print("[Engine] Deserializing heal vectors...")
        heals_enc = [deserialize_ciphertext(self.crypto_ops.cc, enc) for enc in heal_vectors]
        
        print("[Engine] Deserializing investigate vectors...")
        investigations_enc = [deserialize_ciphertext(self.crypto_ops.cc, enc) for enc in investigate_vectors]
        
        # Debug: Decrypt individual vectors to verify one-hot property
        # DEBUG: Optionally decrypt individual vectors for logging (VERY EXPENSIVE)
        # Commented out to improve performance - threshold decrypt is slow
        # if self.logger:
        #     self.logger.log("\nDEBUG: Individual player vectors (before aggregation)")
        #     for i, attack_ct in enumerate(attacks_enc):
        #         attack_plain = await self.crypto_ops.threshold_decrypt_vector(attack_ct, players)
        #         self.logger.log(f"  Player {i} attack: {attack_plain}")
        #     for i, heal_ct in enumerate(heals_enc):
        #         heal_plain = await self.crypto_ops.threshold_decrypt_vector(heal_ct, players)
        #         self.logger.log(f"  Player {i} heal: {heal_plain}")

        print("[Engine] Aggregating all attack vectors (blind protocol)...")
        total_attacks = aggregate_encrypted_vectors(self.crypto_ops.cc, attacks_enc)
        
        print("[Engine] Aggregating all heal vectors (blind protocol)...")
        total_heals = aggregate_encrypted_vectors(self.crypto_ops.cc, heals_enc)

        print("[Engine] Computing kill results homomorphically (no decryption)...")
        killed_vector_enc = compute_killed_vector(
            self.crypto_ops.cc, 
            total_attacks, 
            total_heals, 
            len(players), 
            self.crypto_ops.joint_public_key
        )

        print("[Engine] Threshold decrypting ONLY the final killed vector...")
        killed_vector = await self.crypto_ops.threshold_decrypt_vector(killed_vector_enc, players)
        
        # Log decrypted results to file
        if self.logger:
            self.logger.log_night_results(
                self.day_number, 
                killed_vector, 
                [i for i, k in enumerate(killed_vector) if k > 0 and players[i].alive],
                self.crypto_ops.num_players
            )

        self.last_killed = []
        for i, killed in enumerate(killed_vector):
            if killed > 0 and players[i].alive:
                players[i].alive = False
                self.last_killed.append(i)

        await self._handle_police_investigation(investigations_enc, players, human_player_index, human_role)
        self._announce_night_results(players, log_callback)

    async def _handle_police_investigation(self, investigations_enc, players, human_player_index, human_role):
        """
        Police investigation using parallel decryption (ONLY POLICE SEES RESULT).
        
        Protocol (Network Obfuscation):
        1. ALL players send investigation packets automatically:
           - Police: role_vector[target] · mafia_check → encrypted result
           - Others: Enc(0) with random delay (agent 코드에서 자동 실행)
        2. Server aggregates all encrypted results
        3. Police agent already performed parallel decrypt client-side
        
        Security:
        - Network traffic looks identical for all players
        - Only police sees final result (already decrypted on their side)
        - Server doesn't know who the police is or what the result is
        """
        print("[Engine] Police investigation: Server aggregating encrypted packets (blind protocol)...")
        
        # Just aggregate - police already did parallel decrypt on their side
        # This is just to maintain the blind protocol
        total_result_enc = aggregate_encrypted_vectors(self.crypto_ops.cc, investigations_enc)
        
        # Note: We don't decrypt here. Police already did it client-side.
        print("[Engine] Investigation complete (police already has result)")


    def _announce_night_results(self, players, log_callback):
        """Announce night phase results"""
        print(f"\n{'='*60}")
        print("NIGHT RESULTS")
        print(f"{'='*60}")

        if self.last_killed:
            for victim_index in self.last_killed:
                victim = players[victim_index]
                message = f"{victim.name} was killed!"
                print(f"💀 {message}")
                log_callback(message)
        else:
            print("✓ No one was killed")
            log_callback("No one was killed during the night.")

        print(f"{'='*60}\n")

    async def execute_vote_phase(
        self,
        players,
        human_player_index: int,
        human_role: str,
        get_survivors_func,
        get_dead_func,
        get_human_action_callback,
        broadcast_callback,
        log_callback
    ):
        """Execute voting phase"""
        print(f"\n{'='*60}")
        print(f"VOTE PHASE - Day {self.day_number}")
        print(f"{'='*60}")

        survivors = get_survivors_func()
        dead = get_dead_func()
        message = f"Day {self.day_number} vote: Eliminate a suspected Mafia member."
        log_callback(message)

        await broadcast_callback("vote", message)

        print("[Engine] Collecting encrypted votes (3 vectors per player)...")
        attack_vectors, heal_vectors, investigate_vectors = await self.crypto_ops.collect_encrypted_actions(
            players, human_player_index, human_role, "vote", message, survivors, dead, get_human_action_callback
        )

        # For voting, we use attack_vector slot
        vote_vectors = [deserialize_ciphertext(self.crypto_ops.cc, enc) for enc in attack_vectors]
        total_votes_enc = aggregate_encrypted_vectors(self.crypto_ops.cc, vote_vectors)

        print("[Engine] Threshold decrypting vote results...")
        vote_counts = await self.crypto_ops.threshold_decrypt_vector(total_votes_enc, players)

        # Store vote counts for UI display
        self.last_vote_counts = vote_counts

        # Log decrypted vote results to file
        max_votes = max(vote_counts)
        voted_out = vote_counts.index(max_votes) if max_votes > 0 else None
        
        if self.logger:
            self.logger.log_vote_results(
                self.day_number,
                vote_counts,
                voted_out,
                self.crypto_ops.num_players
            )

        if max_votes > 0:
            eliminated = vote_counts.index(max_votes)
            players[eliminated].alive = False
            self.last_voted_out = eliminated

            print(f"\n{'='*60}")
            print("VOTE RESULTS")
            print(f"{'='*60}")
            for i, count in enumerate(vote_counts):
                if count > 0:
                    print(f"Player {i} ({players[i].name}): {count} votes")

            message = f"{players[eliminated].name} was voted out!"
            print(f"\n💀 {message}")
            log_callback(message)
        else:
            print("\n✓ No one was eliminated (no votes cast).")
            self.last_voted_out = None

        await broadcast_callback("day", "Vote phase ended.")

    async def execute_day_phase(self, broadcast_callback):
        """Execute day phase (discussion)"""
        print(f"\n{'='*60}")
        print(f"DAY {self.day_number} - DISCUSSION PHASE")
        print(f"{'='*60}")
        print("Type a message to send to all players")
        print("Type 'proceed' or press Enter to move to voting")
        print(f"{'='*60}\n")

        await broadcast_callback("day", f"Day {self.day_number} discussion phase.")
