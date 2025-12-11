"""
Crypto Operations Coordinator - Facade for all crypto operations
"""
import asyncio
import httpx
import sys
import os
from typing import List, Tuple

# Add agent directory to path
agent_path = os.path.join(os.path.dirname(__file__), '..', '..', '..', 'agent')
if os.path.abspath(agent_path) not in sys.path:
    sys.path.append(os.path.abspath(agent_path))

from service.crypto.roles import NUM_ROLE_TYPES
from service.crypto.serialization import serialize_ciphertext, deserialize_ciphertext
from service.crypto.threshold_decryption import fusion_decrypt, partial_decrypt_lead
from service.crypto.vector_operations import homomorphic_dot_product

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
        get_human_action_callback,
        cached_results: dict = None
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
            get_human_action_callback,
            cached_results
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
        
        For police role: Execute investigation with parallel threshold decryption.

        Delegates to VectorFactory for vector creation.
        """
        # Execute police investigation if applicable
        if role == "police" and phase == "night" and target >= 0:
            await self._execute_police_investigation(target, players)
        
        return self.vector_factory.create_human_action_vectors(target, role, phase)

    def create_human_action_vectors(
        self,
        target: int,
        role: str,
        phase: str
    ) -> Tuple[str, str, str]:
        """
        Create 3 encrypted vectors for human player action (sync version).

        Delegates to VectorFactory.
        """
        return self.vector_factory.create_human_action_vectors(
            target, role, phase
        )
    
    async def _execute_police_investigation(self, target_index: int, players):
        """
        Execute police investigation using parallel threshold decryption.
        
        Process:
        1. Get target's encrypted role vector
        2. Create mafia check vector [0,1,0,0] (마피아는 인덱스 1)
        3. Compute homomorphic dot product (암호문 곱)
        4. Collect partial decryptions from all players in parallel
        5. Fusion decrypt to get final result
        6. Store result in last_investigation_result
        """
        print(f"[Human] 🔍 Police investigating Player {target_index} via parallel decrypt...")
        
        # Get target's encrypted role
        if not self.all_encrypted_roles or target_index >= len(self.all_encrypted_roles):
            print(f"[Human] ❌ No encrypted roles available for investigation")
            return
        
        target_role_enc_b64 = self.all_encrypted_roles[target_index]
        target_role_enc = deserialize_ciphertext(self.cc, target_role_enc_b64)
        
        # Compute mafia check: role_vector · Enc([0,1,0,0])
        mafia_plain = [0, 1, 0, 0]  # 마피아는 인덱스 1
        mafia_check_enc = self.cc.Encrypt(
            self.joint_public_key, 
            self.cc.MakePackedPlaintext(mafia_plain)
        )
        
        # Homomorphic dot product (암호문 곱)
        investigate_result_enc = homomorphic_dot_product(self.cc, target_role_enc, mafia_check_enc)
        investigate_result_b64 = serialize_ciphertext(self.cc, investigate_result_enc)
        
        # My partial decryption (Human은 Lead)
        my_partial = partial_decrypt_lead(self.cc, investigate_result_enc, self.keypair.secretKey)
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
                print(f"[Human] Failed to get partial from player {player_idx}: {e}")
                return None
        
        # Collect all partials in parallel
        tasks = []
        for i, player in enumerate(players):
            if not player.is_human and player.address:
                tasks.append(collect_partial(i, player.address))
        
        if tasks:
            partial_results = await asyncio.gather(*tasks)
            for partial_b64 in partial_results:
                if partial_b64:
                    partial = deserialize_ciphertext(self.cc, partial_b64)
                    all_partials.append(partial)
        
        # Fusion decrypt
        final_result = fusion_decrypt(self.cc, all_partials)
        decrypted_vector = final_result.GetPackedValue()
        
        # Check if mafia
        is_mafia = sum(decrypted_vector[:NUM_ROLE_TYPES]) >= 1
        
        # Store results
        self.last_investigation_target = target_index
        self.last_investigation_result = is_mafia
        
        result_text = "🎭 MAFIA" if is_mafia else "✅ NOT MAFIA"
        print(f"[Human] ✅ Investigation complete: Player {target_index} is {result_text}")
        print(f"[Human] DEBUG - Decrypted vector (first 4): {decrypted_vector[:4]}")
        print(f"[Human] DEBUG - Sum: {sum(decrypted_vector[:NUM_ROLE_TYPES])}")
