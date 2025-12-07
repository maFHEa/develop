"""
Action Collector - Collects encrypted actions from all players
"""
from typing import List, Tuple

from .network_client import AgentNetworkClient
from .vector_factory import VectorFactory


class ActionCollector:
    """Collects encrypted actions from AI agents and human player"""
    
    def __init__(self, vector_factory: VectorFactory):
        self.vector_factory = vector_factory
        self.network = AgentNetworkClient()
        self.num_players = vector_factory.num_players
    
    async def collect_all_actions(
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
        
        BLIND PROTOCOL: Every player sends 3 vectors (vote/attack/heal).
        Note: Police investigation is handled client-side via parallel threshold decryption.
        
        Args:
            cached_results: Dict of {player_index: response_data} to reuse existing results
        
        Returns:
            (vote_vectors, attack_vectors, heal_vectors)
        """
        # Initialize vectors
        vote_vectors = [None] * self.num_players
        attack_vectors = [None] * self.num_players
        heal_vectors = [None] * self.num_players
        
        # Collect from AI agents (with cached results if available)
        agent_results = await self.network.collect_agent_actions(
            players, phase, message, survivors, dead_players, cached_results
        )
        
        for player, result in agent_results:
            if not isinstance(result, Exception):
                vote_vec, attack_vec, heal_vec, chat_messages = result
                vote_vectors[player.index] = vote_vec
                attack_vectors[player.index] = attack_vec
                heal_vectors[player.index] = heal_vec
            else:
                print(f"[ActionCollector] {player.name} failed, using zero vectors")
                zero_str = self.vector_factory.create_zero_vector_str()
                vote_vectors[player.index] = zero_str
                attack_vectors[player.index] = zero_str
                heal_vectors[player.index] = zero_str
        
        # Get human action
        human_player = players[human_player_index]
        if human_player.alive and phase in ["night", "vote"]:
            human_vote, human_attack, human_heal = await get_human_action_callback(
                phase, survivors, human_role
            )
            vote_vectors[human_player_index] = human_vote
            attack_vectors[human_player_index] = human_attack
            heal_vectors[human_player_index] = human_heal
        else:
            zero_str = self.vector_factory.create_zero_vector_str()
            vote_vectors[human_player_index] = zero_str
            attack_vectors[human_player_index] = zero_str
            heal_vectors[human_player_index] = zero_str
        
        # Fill missing with zero vectors
        zero_str = self.vector_factory.create_zero_vector_str()
        for i in range(self.num_players):
            if vote_vectors[i] is None:
                vote_vectors[i] = zero_str
            if attack_vectors[i] is None:
                attack_vectors[i] = zero_str
            if heal_vectors[i] is None:
                heal_vectors[i] = zero_str
        
        return vote_vectors, attack_vectors, heal_vectors
