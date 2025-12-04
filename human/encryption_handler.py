"""
Encryption Handler Module - Homomorphic encryption operations
"""
from typing import List, Optional
import tenseal as ts
import sys

# Import from agent directory (security utilities)
sys.path.append('../agent')
from security import (
    create_tenseal_context,
    serialize_context_public,
    create_one_hot_vector,
    create_zero_vector,
    serialize_encrypted_vector,
    deserialize_encrypted_vector,
    aggregate_encrypted_vectors,
    compute_killed_vector,
    decrypt_vector,
    multiply_encrypted_vectors,
)

from models import Player


class EncryptionHandler:
    """Handles all homomorphic encryption operations"""
    
    def __init__(self):
        self.context: Optional[ts.Context] = None
        self.num_players = 0
    
    def initialize_context(self, num_players: int):
        """Create cryptographic context"""
        print("[Engine] Creating homomorphic encryption context...")
        self.context = create_tenseal_context()
        self.num_players = num_players
    
    def get_public_context(self) -> str:
        """Get serialized public context for agents"""
        return serialize_context_public(self.context)
    
    def create_action_vector(self, target: Optional[int], player_index: int, survivors: List[int], allow_self: bool = False) -> str:
        """
        Create encrypted action vector for a player.
        
        Args:
            target: Target player index (-1 or None for abstain)
            player_index: Acting player's index
            survivors: List of alive player indices
            allow_self: Whether player can target themselves (True for doctor self-heal)
            
        Returns:
            Serialized encrypted vector
        """
        if target is None or target == -1:
            # Abstain - send zero vector
            zero_vec = create_zero_vector(self.num_players, self.context)
            return serialize_encrypted_vector(zero_vec)
        
        # Check if target is valid
        if target in survivors:
            # Check self-targeting
            if target == player_index and not allow_self:
                # Can't target self (except doctor)
                zero_vec = create_zero_vector(self.num_players, self.context)
                return serialize_encrypted_vector(zero_vec)
            
            # Valid target - encrypt one-hot vector
            encrypted_vec = create_one_hot_vector(self.num_players, target, self.context)
            return serialize_encrypted_vector(encrypted_vec)
        else:
            # Invalid target - send zero vector
            zero_vec = create_zero_vector(self.num_players, self.context)
            return serialize_encrypted_vector(zero_vec)
    
    def process_night_actions(
        self, 
        encrypted_actions: List[str], 
        players: List[Player]
    ) -> tuple[List[float], List[float], List[float]]:
        """
        Process night phase actions with homomorphic encryption.
        
        Args:
            encrypted_actions: List of serialized encrypted vectors
            players: List of Player objects
            
        Returns:
            Tuple of (killed_vector, attack_vector, heal_vector)
        """
        # Deserialize encrypted vectors
        print("[Engine] Deserializing encrypted vectors...")
        vectors = [
            deserialize_encrypted_vector(enc, self.context)
            for enc in encrypted_actions
        ]
        
        # Separate Mafia attacks and Doctor heals
        print("[Engine] Computing blind aggregation (no individual decryption)...")
        mafia_vectors = []
        doctor_vectors = []
        
        for player in players:
            if player.alive:
                if player.role == "mafia":
                    mafia_vectors.append(vectors[player.index])
                elif player.role == "doctor":
                    doctor_vectors.append(vectors[player.index])
        
        # Aggregate attacks and heals
        if mafia_vectors:
            total_attacks = aggregate_encrypted_vectors(mafia_vectors)
        else:
            total_attacks = create_zero_vector(self.num_players, self.context)
        
        if doctor_vectors:
            total_heals = aggregate_encrypted_vectors(doctor_vectors)
        else:
            total_heals = create_zero_vector(self.num_players, self.context)
        
        # Compute killed vector: Attack * (1 - Heal)
        print("[Engine] Computing kill results homomorphically...")
        killed_vector_enc = compute_killed_vector(total_attacks, total_heals, self.context, self.num_players)
        
        # Decrypt ONLY the aggregated result
        print("[Engine] Decrypting aggregated result (no individual actions revealed)...")
        killed_vector = decrypt_vector(killed_vector_enc)
        
        # Debug: Show attack and heal vectors
        attack_plain = decrypt_vector(total_attacks)
        heal_plain = decrypt_vector(total_heals)
        print(f"[DEBUG] Attack vector: {attack_plain}")
        print(f"[DEBUG] Heal vector: {heal_plain}")
        print(f"[DEBUG] Kill result: {killed_vector}")
        
        return killed_vector, attack_plain, heal_plain
    
    def handle_police_investigation(
        self, 
        vectors: List[ts.BFVVector], 
        players: List[Player],
        police_target: Optional[int] = None
    ) -> Optional[bool]:
        """
        Handle police investigation privately.
        
        Args:
            vectors: List of encrypted action vectors
            players: List of Player objects
            police_target: Optional override for investigation target
            
        Returns:
            True if target is mafia, False if not, None if no investigation
        """
        police_players = [p for p in players if p.alive and p.role == "police"]
        
        if not police_players:
            return None
        
        for police in police_players:
            # Get police query vector
            query_vector = vectors[police.index]
            
            # Create role vector (1 for mafia, 0 for others)
            role_vector_plain = [1 if p.role == "mafia" else 0 for p in players]
            role_vector_enc = ts.bfv_vector(self.context, role_vector_plain)
            
            # Compute dot product: query · role
            result_enc = multiply_encrypted_vectors(query_vector, role_vector_enc)
            result = decrypt_vector(result_enc)
            
            # Sum to get scalar result
            is_mafia = sum(result) > 0
            
            # Send result to police
            if police.is_human:
                print(f"\n[POLICE INVESTIGATION]")
                print(f"Result: {'MAFIA' if is_mafia else 'NOT MAFIA'}")
                print(f"[This information is private to you]")
                return is_mafia
        
        return None
    
    def process_votes(self, encrypted_votes: List[str]) -> List[float]:
        """
        Process voting phase with homomorphic encryption.
        
        Args:
            encrypted_votes: List of serialized encrypted vote vectors
            
        Returns:
            Decrypted vote counts for each player
        """
        # Deserialize and aggregate
        vote_vectors = [
            deserialize_encrypted_vector(enc, self.context)
            for enc in encrypted_votes
        ]
        
        total_votes_enc = aggregate_encrypted_vectors(vote_vectors)
        vote_counts = decrypt_vector(total_votes_enc)
        
        return vote_counts
