"""
Game Phases - Night, Day, and Vote phase implementations
Handles game flow and phase-specific logic
"""
import sys
from typing import List, Optional

sys.path.append('../agent')
from security import (
    deserialize_ciphertext,
    aggregate_encrypted_vectors,
    compute_killed_vector,
    multiply_encrypted_vectors
)


class GamePhases:
    """Manages game phases (night, day, vote)"""
    
    def __init__(self, crypto_ops, logger=None):
        self.crypto_ops = crypto_ops
        self.day_number = 0
        self.last_killed: List[int] = []
        self.last_voted_out: Optional[int] = None
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
        if self.logger:
            self.logger.log("\nDEBUG: Individual player vectors (before aggregation)")
            for i, attack_ct in enumerate(attacks_enc):
                attack_plain = await self.crypto_ops.threshold_decrypt_vector(attack_ct, players)
                self.logger.log(f"  Player {i} attack: {attack_plain}")
            for i, heal_ct in enumerate(heals_enc):
                heal_plain = await self.crypto_ops.threshold_decrypt_vector(heal_ct, players)
                self.logger.log(f"  Player {i} heal: {heal_plain}")

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
        Police investigation using encrypted role vectors.
        
        BLIND: Server aggregates all investigate_vectors to find which player was investigated.
        Then computes dot product with each player's encrypted_role_vector.
        Result > 0 means investigated player is mafia.
        
        Note: Currently cannot work without encrypted_role_vector
        """
        # TODO: Implement with encrypted role vectors
        # For now, skip investigation as we don't have encrypted_role_vector
        if human_role == "police":
            print(f"\n[POLICE INVESTIGATION]")
            print(f"Result: Investigation not implemented in blind mode yet")
            print(f"[This feature requires encrypted role vectors]")

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
