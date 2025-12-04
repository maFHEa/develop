"""
Human Host & Player - Game Engine with Homomorphic Encryption
Acts as both the Game Server (Engine) and a Human Player
"""
import asyncio
import random
import sys
from typing import List, Dict, Optional, Tuple
import httpx
import tenseal as ts

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
    dot_product_encrypted
)

from config import GAME_CONFIG, NETWORK_CONFIG


# ============================================================================
# Game State
# ============================================================================

class Player:
    """Represents a player in the game"""
    def __init__(self, index: int, role: str, is_human: bool, address: Optional[str] = None):
        self.index = index
        self.role = role
        self.is_human = is_human
        self.address = address
        self.alive = True
        self.name = f"Human (You)" if is_human else f"AI Agent {index}"


class GameEngine:
    """Main game engine with homomorphic encryption"""
    
    def __init__(self):
        self.context: Optional[ts.Context] = None
        self.players: List[Player] = []
        self.num_players = 0
        self.human_player_index = 0
        self.phase = "setup"  # setup, night, day, vote, end
        self.day_number = 0
        self.game_log: List[str] = []
        self.last_killed: List[int] = []
        self.last_voted_out: Optional[int] = None
        self.chat_message_id_counter = 0
        
    def setup_game(self, num_ai_agents: int, ai_addresses: List[str]):
        """
        Initialize the game with players and roles.
        
        Args:
            num_ai_agents: Number of AI agents
            ai_addresses: List of AI agent URLs
        """
        self.num_players = num_ai_agents + 1  # +1 for human
        
        # Create cryptographic context
        print("[Engine] Creating homomorphic encryption context...")
        self.context = create_tenseal_context()
        
        # Distribute roles
        role_dist = GAME_CONFIG["role_distribution"][self.num_players]
        roles = []
        for role, count in role_dist.items():
            roles.extend([role] * count)
        
        random.shuffle(roles)
        
        # Assign human player (always index 0)
        self.human_player_index = 0
        human_role = roles[0]
        self.players.append(Player(0, human_role, is_human=True))
        
        # Assign AI agents
        for i in range(num_ai_agents):
            player_index = i + 1
            self.players.append(Player(
                player_index,
                roles[player_index],
                is_human=False,
                address=ai_addresses[i]
            ))
        
        print(f"[Engine] Game initialized with {self.num_players} players")
        print(f"[Engine] Your role: {human_role.upper()}")
        self.log_message(f"Game started with {self.num_players} players")
        
    async def initialize_agents(self):
        """Send initialization data to all AI agents"""
        public_context = serialize_context_public(self.context)
        
        async with httpx.AsyncClient(timeout=NETWORK_CONFIG["connection_timeout"]) as client:
            tasks = []
            for player in self.players:
                if not player.is_human:
                    tasks.append(self.init_single_agent(client, player, public_context))
            
            results = await asyncio.gather(*tasks, return_exceptions=True)
            
            for i, result in enumerate(results):
                if isinstance(result, Exception):
                    print(f"[Engine] Failed to initialize agent {i+1}: {result}")
                    
    async def init_single_agent(self, client: httpx.AsyncClient, player: Player, public_context: str):
        """Initialize a single AI agent"""
        try:
            response = await client.post(
                f"{player.address}/init",
                json={
                    "public_context": public_context,
                    "role": player.role,
                    "player_index": player.index,
                    "num_players": self.num_players
                }
            )
            response.raise_for_status()
            print(f"[Engine] Initialized {player.name}")
        except Exception as e:
            print(f"[Engine] Error initializing {player.name}: {e}")
            raise
    
    def log_message(self, message: str):
        """Add message to game log"""
        self.game_log.append(message)
        
    def get_survivors(self) -> List[int]:
        """Get list of alive player indices"""
        return [p.index for p in self.players if p.alive]
    
    def get_dead_players(self) -> List[int]:
        """Get list of dead player indices"""
        return [p.index for p in self.players if not p.alive]
    
    def check_win_condition(self) -> Optional[str]:
        """
        Check if any team has won.
        
        Returns:
            "mafia" if mafia wins, "citizens" if citizens win, None if game continues
        """
        alive_mafia = sum(1 for p in self.players if p.alive and p.role == "mafia")
        alive_citizens = sum(1 for p in self.players if p.alive and p.role != "mafia")
        
        if alive_mafia == 0:
            return "citizens"
        elif alive_mafia >= alive_citizens:
            return "mafia"
        else:
            return None
    
    async def broadcast_update(self, phase: str, message: str):
        """Send game state update to all AI agents"""
        survivors = self.get_survivors()
        dead = self.get_dead_players()
        
        async with httpx.AsyncClient(timeout=NETWORK_CONFIG["connection_timeout"]) as client:
            tasks = []
            for player in self.players:
                if not player.is_human:
                    tasks.append(self.update_single_agent(
                        client, player, phase, message, survivors, dead
                    ))
            
            await asyncio.gather(*tasks, return_exceptions=True)
    
    async def update_single_agent(
        self,
        client: httpx.AsyncClient,
        player: Player,
        phase: str,
        message: str,
        survivors: List[int],
        dead: List[int]
    ):
        """Update a single AI agent"""
        try:
            await client.post(
                f"{player.address}/update",
                json={
                    "phase": phase,
                    "message": message,
                    "survivors": survivors,
                    "dead_players": dead
                }
            )
        except Exception as e:
            print(f"[Engine] Error updating {player.name}: {e}")
    
    async def broadcast_chat_message(self, sender_index: int, message: str):
        """
        Broadcast a chat message to all AI agents.
        
        Args:
            sender_index: Index of the player sending the message
            message: The chat message content
        """
        msg_id = self.chat_message_id_counter
        self.chat_message_id_counter += 1
        
        chat_data = {
            "msg_id": msg_id,
            "player_index": sender_index,
            "phase": self.phase,
            "message": message,
            "turn": self.day_number
        }
        
        async with httpx.AsyncClient(timeout=NETWORK_CONFIG["connection_timeout"]) as client:
            tasks = []
            for player in self.players:
                if not player.is_human:
                    tasks.append(self.send_chat_to_agent(client, player, chat_data))
            
            await asyncio.gather(*tasks, return_exceptions=True)
    
    async def send_chat_to_agent(
        self,
        client: httpx.AsyncClient,
        player: Player,
        chat_data: Dict
    ):
        """Send a chat message to a single AI agent"""
        try:
            await client.post(
                f"{player.address}/broadcast_chat",
                json=chat_data
            )
        except Exception as e:
            print(f"[Engine] Error sending chat to {player.name}: {e}")
    
    async def collect_encrypted_actions(self, phase: str, message: str) -> List[str]:
        """
        Collect encrypted actions from all players (AI and human).
        
        This implements the Uniform Action Protocol - EVERY player sends data.
        Also handles chat messages from AI agents.
        
        Returns:
            List of base64-encoded encrypted vectors
        """
        survivors = self.get_survivors()
        dead = self.get_dead_players()
        encrypted_actions = [None] * self.num_players
        
        # Collect from AI agents
        async with httpx.AsyncClient(timeout=NETWORK_CONFIG["action_request_timeout"]) as client:
            tasks = []
            for player in self.players:
                if not player.is_human:
                    tasks.append(self.request_agent_action(
                        client, player, phase, message, survivors, dead
                    ))
            
            results = await asyncio.gather(*tasks, return_exceptions=True)
            
            for player, result in zip([p for p in self.players if not p.is_human], results):
                if not isinstance(result, Exception):
                    encrypted_action, chat_messages = result
                    encrypted_actions[player.index] = encrypted_action
                    
                    # Broadcast any chat messages from this agent
                    for msg in chat_messages:
                        print(f"[{player.name}] {msg}")
                        await self.broadcast_chat_message(player.index, msg)
                else:
                    # Agent failed - use zero vector
                    print(f"[Engine] {player.name} failed to respond, using zero vector")
                    zero_vec = create_zero_vector(self.num_players, self.context)
                    encrypted_actions[player.index] = serialize_encrypted_vector(zero_vec)
        
        # Get human action
        human_player = self.players[self.human_player_index]
        if human_player.alive and phase in ["night", "vote"]:
            human_action = await self.get_human_action(phase, survivors)
            encrypted_actions[self.human_player_index] = human_action
        else:
            # Human dead or no action - zero vector
            zero_vec = create_zero_vector(self.num_players, self.context)
            encrypted_actions[self.human_player_index] = serialize_encrypted_vector(zero_vec)
        
        # Ensure all slots filled with zero vectors if missing
        for i in range(self.num_players):
            if encrypted_actions[i] is None:
                zero_vec = create_zero_vector(self.num_players, self.context)
                encrypted_actions[i] = serialize_encrypted_vector(zero_vec)
        
        return encrypted_actions
    
    async def request_agent_action(
        self,
        client: httpx.AsyncClient,
        player: Player,
        phase: str,
        message: str,
        survivors: List[int],
        dead: List[int]
    ) -> Tuple[str, List[str]]:
        """Request action from a single AI agent
        
        Returns:
            Tuple of (encrypted_action, chat_messages)
        """
        try:
            response = await client.post(
                f"{player.address}/request_action",
                json={
                    "phase": phase,
                    "message": message,
                    "survivors": survivors,
                    "dead_players": dead
                }
            )
            response.raise_for_status()
            data = response.json()
            return data["encrypted_action"], data.get("chat_messages", [])
        except Exception as e:
            print(f"[Engine] Error requesting action from {player.name}: {e}")
            raise
    
    async def get_human_action(self, phase: str, survivors: List[int]) -> str:
        """Get encrypted action from human player"""
        human = self.players[self.human_player_index]
        
        print(f"\n{'='*60}")
        print(f"YOUR TURN - {phase.upper()} PHASE")
        print(f"Your Role: {human.role.upper()}")
        print(f"Survivors: {survivors}")
        print(f"{'='*60}")
        
        # Check if human can act
        can_act = False
        if phase == "night" and human.role in ["mafia", "doctor", "police"]:
            can_act = True
        elif phase == "vote":
            can_act = True
        
        if not can_act:
            print("[You] You have no action this phase (sending encrypted dummy data)")
            zero_vec = create_zero_vector(self.num_players, self.context)
            return serialize_encrypted_vector(zero_vec)
        
        # Get target from user
        valid_targets = [i for i in survivors if i != self.human_player_index]
        
        action_name = "target" if phase == "night" else "vote for"
        
        while True:
            try:
                print(f"\nValid targets: {valid_targets}")
                target_input = input(f"Enter player index to {action_name} (or -1 to skip): ")
                target = int(target_input)
                
                if target == -1:
                    # Abstain - send zero vector
                    zero_vec = create_zero_vector(self.num_players, self.context)
                    return serialize_encrypted_vector(zero_vec)
                
                if target in valid_targets:
                    # Valid target - encrypt one-hot vector
                    encrypted_vec = create_one_hot_vector(
                        self.num_players,
                        target,
                        self.context
                    )
                    print(f"[You] Action encrypted and submitted")
                    return serialize_encrypted_vector(encrypted_vec)
                else:
                    print(f"Invalid target. Choose from {valid_targets}")
                    
            except ValueError:
                print("Please enter a valid number")
            except KeyboardInterrupt:
                print("\nGame interrupted by user")
                sys.exit(0)
    
    async def execute_night_phase(self):
        """Execute night phase with homomorphic encryption"""
        self.day_number += 1
        self.phase = "night"
        
        print(f"\n{'#'*60}")
        print(f"NIGHT {self.day_number}")
        print(f"{'#'*60}")
        
        message = f"Night {self.day_number} has begun. Mafia chooses a target, Doctor can save someone, Police can investigate."
        self.log_message(message)
        
        await self.broadcast_update("night", message)
        
        # Collect encrypted actions
        print("[Engine] Collecting encrypted actions from all players...")
        encrypted_actions = await self.collect_encrypted_actions("night", message)
        
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
        
        for player in self.players:
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
        killed_vector_enc = compute_killed_vector(total_attacks, total_heals, self.context)
        
        # Decrypt ONLY the aggregated result
        print("[Engine] Decrypting aggregated result (no individual actions revealed)...")
        killed_vector = decrypt_vector(killed_vector_enc)
        
        # Update player states
        self.last_killed = []
        for i, killed in enumerate(killed_vector):
            if killed > 0 and self.players[i].alive:
                self.players[i].alive = False
                self.last_killed.append(i)
        
        # Handle Police investigation (separate private result)
        await self.handle_police_investigation(vectors)
        
        # Announce results
        await self.announce_night_results()
    
    async def handle_police_investigation(self, vectors: List[ts.BFVVector]):
        """Handle police investigation privately"""
        police_players = [p for p in self.players if p.alive and p.role == "police"]
        
        if not police_players:
            return
        
        for police in police_players:
            # Get police query vector
            query_vector = vectors[police.index]
            
            # Create role vector (1 for mafia, 0 for others)
            role_vector_plain = [1 if p.role == "mafia" else 0 for p in self.players]
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
            else:
                # Send to AI agent (not implemented in this version for simplicity)
                pass
    
    async def announce_night_results(self):
        """Announce what happened during the night"""
        print(f"\n{'='*60}")
        print("NIGHT RESULTS")
        print(f"{'='*60}")
        
        if self.last_killed:
            for victim_index in self.last_killed:
                victim = self.players[victim_index]
                message = f"{victim.name} (Player {victim_index}) was killed during the night!"
                print(f"💀 {message}")
                self.log_message(message)
        else:
            message = "No one was killed during the night."
            print(f"✓ {message}")
            self.log_message(message)
        
        await self.broadcast_update("day", f"Night {self.day_number} ended. {len(self.last_killed)} players killed.")
    
    async def execute_vote_phase(self):
        """Execute voting phase"""
        self.phase = "vote"
        
        print(f"\n{'='*60}")
        print(f"VOTE PHASE - Day {self.day_number}")
        print(f"{'='*60}")
        
        survivors = self.get_survivors()
        message = f"Day {self.day_number} vote: Eliminate a suspected Mafia member."
        self.log_message(message)
        
        await self.broadcast_update("vote", message)
        
        # Collect votes
        print("[Engine] Collecting encrypted votes...")
        encrypted_votes = await self.collect_encrypted_actions("vote", message)
        
        # Deserialize and aggregate
        vote_vectors = [
            deserialize_encrypted_vector(enc, self.context)
            for enc in encrypted_votes
        ]
        
        total_votes_enc = aggregate_encrypted_vectors(vote_vectors)
        vote_counts = decrypt_vector(total_votes_enc)
        
        # Find player with most votes
        max_votes = max(vote_counts)
        if max_votes > 0:
            eliminated = vote_counts.index(max_votes)
            self.players[eliminated].alive = False
            self.last_voted_out = eliminated
            
            print(f"\n{'='*60}")
            print(f"VOTE RESULTS")
            print(f"{'='*60}")
            for i, count in enumerate(vote_counts):
                if count > 0:
                    print(f"Player {i} ({self.players[i].name}): {count} votes")
            
            message = f"{self.players[eliminated].name} (Player {eliminated}) was voted out!"
            print(f"\n💀 {message}")
            self.log_message(message)
        else:
            message = "No one was eliminated (no votes cast)."
            print(f"\n✓ {message}")
            self.log_message(message)
            self.last_voted_out = None
        
        await self.broadcast_update("day", "Vote phase ended.")
    
    async def run_game_loop(self):
        """Main game loop"""
        print("\n[Engine] Starting game loop...")
        
        while True:
            # Night phase
            await self.execute_night_phase()
            
            # Check win condition
            winner = self.check_win_condition()
            if winner:
                await self.end_game(winner)
                break
            
            # Day discussion phase with chat
            await self.execute_day_phase()
            
            # Vote phase
            await self.execute_vote_phase()
            
            # Check win condition
            winner = self.check_win_condition()
            if winner:
                await self.end_game(winner)
                break
    
    async def execute_day_phase(self):
        """Execute day phase with chat discussion"""
        self.phase = "day"
        
        print(f"\n{'='*60}")
        print(f"DAY {self.day_number} - DISCUSSION PHASE")
        print(f"{'='*60}")
        print("Players can discuss and share information.")
        print("Commands:")
        print("  - Type a message to send to all players")
        print("  - Type 'proceed' or press Enter to move to voting")
        print(f"{'='*60}\n")
        
        # Broadcast day phase start to agents
        await self.broadcast_update("day", f"Day {self.day_number} discussion has begun.")
        
        # Chat loop
        while True:
            try:
                user_input = input("[You] ").strip()
                
                if user_input.lower() in ['proceed', '']:
                    break
                
                if user_input:
                    # Human sends message
                    print(f"[You] Broadcasting: {user_input}")
                    await self.broadcast_chat_message(self.human_player_index, user_input)
                    
                    # Give AI agents time to potentially respond
                    await asyncio.sleep(1)
                    
            except KeyboardInterrupt:
                print("\n[Game] Interrupted by user")
                raise
    
    async def end_game(self, winner: str):
        """End the game and reveal roles"""
        self.phase = "end"
        
        print(f"\n{'#'*60}")
        print(f"GAME OVER - {winner.upper()} WIN!")
        print(f"{'#'*60}\n")
        
        print("FINAL ROLES:")
        for player in self.players:
            status = "ALIVE" if player.alive else "DEAD"
            print(f"  Player {player.index} ({player.name}): {player.role.upper()} - {status}")
        
        self.log_message(f"Game ended: {winner} win!")
        
        await self.broadcast_update("end", f"Game over! {winner} team wins!")


# ============================================================================
# Main Entry Point
# ============================================================================

async def spawn_agents_from_lobbies(lobby_addresses: List[str], openai_api_key: str) -> List[str]:
    """
    Spawn AI agents from lobby servers.
    
    Args:
        lobby_addresses: List of lobby server URLs
        openai_api_key: OpenAI API key for agents
        
    Returns:
        List of spawned agent addresses
    """
    print(f"[Setup] Spawning {len(lobby_addresses)} AI agents from lobbies...")
    
    agent_addresses = []
    
    async with httpx.AsyncClient(timeout=30) as client:
        for i, lobby_url in enumerate(lobby_addresses, 1):
            try:
                print(f"[Setup] Requesting Agent spawn from {lobby_url}...")
                response = await client.post(
                    f"{lobby_url}/spawn_agent",
                    json={
                        "openai_api_key": openai_api_key,
                        "game_session_id": f"game_{i}"
                    }
                )
                response.raise_for_status()
                data = response.json()
                
                agent_address = data["address"]
                print(f"[Setup] Agent #{i} spawned at {agent_address}, waiting for startup...")
                
                # Wait for agent to be fully ready (with retries)
                ready = False
                for attempt in range(10):
                    await asyncio.sleep(1)
                    if await check_agent_health(agent_address):
                        ready = True
                        break
                    print(f"[Setup] Agent #{i} not ready yet, retrying ({attempt+1}/10)...")
                
                if not ready:
                    raise Exception(f"Agent at {agent_address} failed to start after 10 seconds")
                
                agent_addresses.append(agent_address)
                print(f"[Setup] ✓ Agent #{i} ready at {agent_address}")
                
            except Exception as e:
                print(f"[Setup] ✗ Failed to spawn agent from {lobby_url}: {e}")
                raise
    
    return agent_addresses


async def check_agent_health(address: str) -> bool:
    """
    Check if an agent server is healthy and responding.
    
    Args:
        address: Agent server URL
        
    Returns:
        True if healthy, False otherwise
    """
    try:
        async with httpx.AsyncClient(timeout=5) as client:
            response = await client.get(f"{address}/health")
            response.raise_for_status()
            return True
    except Exception:
        return False


async def main():
    """Main entry point"""
    print("=" * 60)
    print("SECURE P2P MAFIA GAME")
    print("Homomorphic Encryption Edition")
    print("=" * 60)
    
    # Get OpenAI API Key
    openai_api_key = NETWORK_CONFIG.get("openai_api_key", "").strip()
    if not openai_api_key:
        openai_api_key = input("\nEnter your OpenAI API key: ").strip()
        if not openai_api_key:
            print("Error: OpenAI API key required")
            return
    
    # Get Lobby addresses and spawn agents
    print("\n" + "="*60)
    print("LOBBY & AGENT CONFIGURATION")
    print("="*60)
    
    lobby_addresses = []
    
    if NETWORK_CONFIG.get("use_config_lobbies", False):
        # Config에서 Lobby 주소들 가져오기
        configured_lobbies = NETWORK_CONFIG.get("lobby_addresses", [])
        
        if not configured_lobbies:
            print("⚠️  Config에 lobby_addresses가 설정되지 않았습니다.")
            print("config.py에서 NETWORK_CONFIG['lobby_addresses']를 설정하거나")
            print("NETWORK_CONFIG['use_config_lobbies'] = False로 변경하세요.\n")
            return
        
        num_agents = len(configured_lobbies)
        total_players = num_agents + 1  # +1 for human
        
        # 플레이어 수 검증
        if total_players < GAME_CONFIG['min_players'] or total_players > GAME_CONFIG['max_players']:
            print(f"⚠️  Config에 {num_agents}개 Lobby 설정됨 (총 {total_players}명)")
            print(f"게임 가능 인원: {GAME_CONFIG['min_players']}~{GAME_CONFIG['max_players']}명")
            print(f"Lobby는 {GAME_CONFIG['min_players']-1}~{GAME_CONFIG['max_players']-1}개 필요")
            return
        
        print(f"Config에서 {num_agents}개 Lobby 서버 주소를 가져왔습니다:")
        for i, addr in enumerate(configured_lobbies, 1):
            print(f"  {i}. {addr}")
        
        lobby_addresses = configured_lobbies
    
    else:
        # 수동으로 Lobby 주소 입력받기
        print("Lobby 서버 주소를 입력하세요 (한 줄에 하나씩).")
        print("각 Lobby가 Agent 1개씩 생성합니다.")
        print("예: http://localhost:8000")
        print("빈 줄 입력 시 완료.")
        print(f"최소 {GAME_CONFIG['min_players']-1}개, 최대 {GAME_CONFIG['max_players']-1}개")
        print("="*60 + "\n")
        
        while True:
            address = input(f"Lobby #{len(lobby_addresses)+1} 주소 (또는 Enter로 완료): ").strip()
            
            if not address:
                if len(lobby_addresses) >= GAME_CONFIG['min_players'] - 1:
                    break
                else:
                    print(f"최소 {GAME_CONFIG['min_players']-1}개 필요합니다")
                    continue
            
            # URL 형식 검증
            if not address.startswith("http://") and not address.startswith("https://"):
                address = f"http://{address}"
            
            lobby_addresses.append(address)
            print(f"[Setup] ✓ Lobby #{len(lobby_addresses)} 추가됨")
            
            if len(lobby_addresses) >= GAME_CONFIG['max_players'] - 1:
                print(f"최대 {GAME_CONFIG['max_players']-1}개 도달")
                break
    
    # Spawn agents from lobbies
    try:
        agent_addresses = await spawn_agents_from_lobbies(lobby_addresses, openai_api_key)
    except Exception as e:
        print(f"[Error] Failed to spawn agents: {e}")
        return
    
    num_agents = len(agent_addresses)
    print(f"\n[Setup] {num_agents}개 AI Agent 구성 완료")
    
    # Initialize engine
    engine = GameEngine()
    
    # Setup game
    engine.setup_game(num_agents, agent_addresses)
    
    # Initialize agents with crypto context and roles
    print("\n[Setup] Initializing agents with encrypted roles...")
    await engine.initialize_agents()
    
    print("\n[Setup] All players ready!")
    input("Press Enter to start the game...")
    
    # Run game
    try:
        await engine.run_game_loop()
    except KeyboardInterrupt:
        print("\n\n[Game] Interrupted by user")
    except Exception as e:
        print(f"\n[Error] Game error: {e}")
        import traceback
        traceback.print_exc()
    
    print("\nThank you for playing!")


if __name__ == "__main__":
    asyncio.run(main())
