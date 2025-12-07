"""
Action Collector - Collects encrypted actions from all players
"""
import asyncio
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
        
        # 🔥 **AI 먼저 실행 (HTTP 요청 즉시 전송)** → 사람 행동 기다림 → 결과 수집
        print(f"[ActionCollector] Starting AI requests for {phase} phase...")
        
        # AI들에게 요청 보내기 (Task 생성 + 즉시 실행 보장)
        ai_task = asyncio.create_task(
            self.network.collect_agent_actions(
                players, phase, message, survivors, dead_players, cached_results
            )
        )
        
        # ⚡ 중요: asyncio.sleep(0)으로 이벤트 루프에 제어권을 넘겨서
        # ai_task가 실제로 시작되도록 보장
        await asyncio.sleep(0)
        print(f"[ActionCollector] AI requests sent, now waiting for human...")
        
        # 사람 행동 받기 (화면 표시 - 메인 흐름)
        human_player = players[human_player_index]
        if human_player.alive and phase in ["night", "vote"]:
            human_vote, human_attack, human_heal = await get_human_action_callback(
                phase, survivors, human_role
            )
        else:
            zero_str = self.vector_factory.create_zero_vector_str()
            human_vote, human_attack, human_heal = zero_str, zero_str, zero_str
        
        print(f"[ActionCollector] Human action received, collecting AI results...")
        
        # 사람 결과 저장
        vote_vectors[human_player_index] = human_vote
        attack_vectors[human_player_index] = human_attack
        heal_vectors[human_player_index] = human_heal
        
        # AI 결과 수집 (사람이 끝났으니 이제 AI들 기다림)
        agent_results = await ai_task
        
        # AI 결과 저장
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
