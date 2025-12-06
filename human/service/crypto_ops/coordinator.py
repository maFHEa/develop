"""
Crypto Operations Coordinator - Facade for all crypto operations
"""
from typing import List, Tuple

from .vector_factory import VectorFactory
from .action_collector import ActionCollector
from .decryption_service import ThresholdDecryptionService


class CryptoOperations:
    """
    Coordinator for all cryptographic operations.

    Facade pattern - delegates to specialized services.
    """

    def __init__(self, cc, keypair, joint_public_key, num_players: int):
        self.cc = cc
        self.keypair = keypair
        self.joint_public_key = joint_public_key
        self.num_players = num_players
        self.human_encrypted_role = None  # Store human's encrypted role for investigation
        self.all_encrypted_roles: List[str] = []  # Store all players' encrypted roles

        # Police investigation result (for human player)
        self.last_investigation_target: int = None
        self.last_investigation_result: bool = None  # True if mafia, False if not

        # Initialize services
        self.vector_factory = VectorFactory(cc, joint_public_key, num_players)
        self.action_collector = ActionCollector(self.vector_factory)
        self.decryption_service = ThresholdDecryptionService(cc, keypair, num_players)
    
    def update_encrypted_roles(self, all_encrypted_roles: List[str]):
        """Update the encrypted roles after they are assigned"""
        self.all_encrypted_roles = all_encrypted_roles
        self.vector_factory.all_encrypted_roles = all_encrypted_roles
    
    async def collect_encrypted_actions(
        self,
        players,
        human_player_index: int,
        human_role: str,
        phase: str,
        message: str,
        survivors: List[int],
        dead_players: List[int],
        get_human_action_callback
    ) -> Tuple[List[str], List[str], List[str]]:
        """
        Collect encrypted actions from all players.
        
        Delegates to ActionCollector.
        """
        return await self.action_collector.collect_all_actions(
            players,
            human_player_index,
            human_role,
            phase,
            message,
            survivors,
            dead_players,
            get_human_action_callback
        )
    
    async def threshold_decrypt_vector(self, encrypted_vector, players) -> List[int]:
        """
        Perform threshold decryption on an aggregated vector.
        
        Delegates to ThresholdDecryptionService.
        """
        return await self.decryption_service.decrypt_vector(
            encrypted_vector, players
        )
    
    async def create_human_action_vectors_async(
        self,
        target: int,
        role: str,
        phase: str,
        players
    ) -> Tuple[str, str, str]:
        """
        Create 3 encrypted vectors for human player action.
        For police, also performs threshold decryption to get investigation result.

        Delegates to VectorFactory for vector creation, handles decryption here.
        """
        vectors = self.vector_factory.create_human_action_vectors(target, role, phase)

        # If human is police and investigating, decrypt the result
        if role == "police" and phase == "night" and target >= 0:
            self.last_investigation_target = target
            # The investigate_vector (vectors[2]) contains the encrypted result
            # Perform threshold decryption
            investigate_enc_b64 = vectors[2]
            try:
                result = await self.decryption_service.parallel_decrypt(
                    investigate_enc_b64,
                    0,  # human is player 0
                    players
                )
                # Result is a vector, first element is 1 if mafia, 0 if not
                is_mafia = result[0] == 1 if result else False
                self.last_investigation_result = is_mafia
                print(f"[Police] Investigation result for Player {target}: {'MAFIA' if is_mafia else 'NOT MAFIA'}")
            except Exception as e:
                print(f"[Police] Failed to decrypt investigation result: {e}")
                self.last_investigation_result = None

        return vectors

    def create_human_action_vectors(
        self,
        target: int,
        role: str,
        phase: str
    ) -> Tuple[str, str, str]:
        """
        Create 3 encrypted vectors for human player action (sync version).
        Note: For police investigation with decryption, use create_human_action_vectors_async.

        Delegates to VectorFactory.
        """
        return self.vector_factory.create_human_action_vectors(
            target, role, phase
        )
