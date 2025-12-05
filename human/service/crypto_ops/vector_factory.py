"""
Vector Factory - Creates encrypted vectors for game actions
"""
import sys
import os
from typing import Tuple

# Add agent directory to path for security imports
agent_path = os.path.join(os.path.dirname(__file__), '..', '..', '..', 'agent')
if os.path.abspath(agent_path) not in sys.path:
    sys.path.append(os.path.abspath(agent_path))

from service.crypto.vector_operations import create_zero_vector, create_one_hot_vector
from service.crypto.serialization import serialize_ciphertext


class VectorFactory:
    """Creates and serializes encrypted vectors"""
    
    def __init__(self, cc, joint_public_key, num_players: int):
        self.cc = cc
        self.joint_public_key = joint_public_key
        self.num_players = num_players
        self.all_encrypted_roles = []  # Will be updated later
    
    def create_zero_vector_str(self) -> str:
        """Create serialized zero vector"""
        zero_vec = create_zero_vector(
            self.num_players, self.cc, self.joint_public_key
        )
        return serialize_ciphertext(self.cc, zero_vec)
    
    def create_one_hot_vector_str(self, target_index: int) -> str:
        """Create serialized one-hot vector"""
        one_hot = create_one_hot_vector(
            self.num_players, target_index, self.cc, self.joint_public_key
        )
        return serialize_ciphertext(self.cc, one_hot)
    
    def create_human_action_vectors(
        self,
        target: int,
        role: str,
        phase: str
    ) -> Tuple[str, str, str]:
        """
        Create 3 encrypted vectors for human player action.
        
        BLIND PROTOCOL: Only role-appropriate vector contains real data.
        
        Returns:
            (attack_vector, heal_vector, investigate_vector)
        """
        # Determine action type
        action_type = self._get_action_type(role, phase)
        
        # Generate real vector
        if target == -1 or action_type is None:
            real_str = self.create_zero_vector_str()
        elif action_type == "investigate":
            # Police: Compute investigation result (role · mafia_check)
            import sys
            import os
            agent_path = os.path.join(os.path.dirname(__file__), '..', '..', '..', 'agent')
            if os.path.abspath(agent_path) not in sys.path:
                sys.path.append(os.path.abspath(agent_path))
            from service.crypto.serialization import deserialize_ciphertext
            from service.crypto.vector_operations import homomorphic_dot_product
            
            # Get target's encrypted role vector
            target_role_enc_b64 = self.all_encrypted_roles[target]
            target_role_enc = deserialize_ciphertext(self.cc, target_role_enc_b64)
            
            # Mafia check vector
            mafia_check_vector = [0, 1, 0, 0]
            
            # Compute dot product
            result_enc = homomorphic_dot_product(
                self.cc,
                target_role_enc,
                mafia_check_vector
            )
            
            # Serialize
            from service.crypto.serialization import serialize_ciphertext
            real_str = serialize_ciphertext(self.cc, result_enc)
        else:
            real_str = self.create_one_hot_vector_str(target)
        
        # Create dummy vectors
        dummy1_str = self.create_zero_vector_str()
        dummy2_str = self.create_zero_vector_str()
        
        # Assign based on role
        if action_type == "attack":
            return real_str, dummy1_str, dummy2_str
        elif action_type == "heal":
            return dummy1_str, real_str, dummy2_str
        elif action_type == "investigate":
            return dummy1_str, dummy2_str, real_str
        else:
            return dummy1_str, dummy2_str, dummy1_str  # All dummies
    
    def _get_action_type(self, role: str, phase: str) -> str:
        """Determine action type based on role and phase"""
        if phase == "night":
            if role == "mafia":
                return "attack"
            elif role == "doctor":
                return "heal"
            elif role == "police":
                return "investigate"
        elif phase == "vote":
            return "attack"  # Use attack vector slot for voting
        return None
