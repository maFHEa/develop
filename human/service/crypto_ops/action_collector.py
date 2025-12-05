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
        get_human_action_callback
    ) -> Tuple[List[str], List[str], List[str]]:
        """
        Collect encrypted actions from all players.
        
        BLIND PROTOCOL: Every player sends 3 vectors regardless of role.
        
        Returns:
            (attack_vectors, heal_vectors, investigate_vectors)
        """
        # Initialize vectors
        attack_vectors = [None] * self.num_players
        heal_vectors = [None] * self.num_players
        investigate_vectors = [None] * self.num_players
        
        # Collect from AI agents
        agent_results = await self.network.collect_agent_actions(
            players, phase, message, survivors, dead_players
        )
        
        for player, result in agent_results:
            if not isinstance(result, Exception):
                attack_vec, heal_vec, investigate_vec, chat_messages = result
                attack_vectors[player.index] = attack_vec
                heal_vectors[player.index] = heal_vec
                investigate_vectors[player.index] = investigate_vec
            else:
                print(f"[ActionCollector] {player.name} failed, using zero vectors")
                zero_str = self.vector_factory.create_zero_vector_str()
                attack_vectors[player.index] = zero_str
                heal_vectors[player.index] = zero_str
                investigate_vectors[player.index] = zero_str
        
        # Get human action
        human_player = players[human_player_index]
        if human_player.alive and phase in ["night", "vote"]:
            human_attack, human_heal, human_investigate = await get_human_action_callback(
                phase, survivors, human_role
            )
            attack_vectors[human_player_index] = human_attack
            heal_vectors[human_player_index] = human_heal
            investigate_vectors[human_player_index] = human_investigate
        else:
            zero_str = self.vector_factory.create_zero_vector_str()
            attack_vectors[human_player_index] = zero_str
            heal_vectors[human_player_index] = zero_str
            investigate_vectors[human_player_index] = zero_str
        
        # Fill missing with zero vectors
        zero_str = self.vector_factory.create_zero_vector_str()
        for i in range(self.num_players):
            if attack_vectors[i] is None:
                attack_vectors[i] = zero_str
            if heal_vectors[i] is None:
                heal_vectors[i] = zero_str
            if investigate_vectors[i] is None:
                investigate_vectors[i] = zero_str
        
        return attack_vectors, heal_vectors, investigate_vectors
