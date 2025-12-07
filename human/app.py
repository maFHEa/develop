"""
Main Application - Orchestrates Game Flow with TUI
"""
from textual.app import App
import asyncio
import httpx
import os
import sys
from typing import List

# Import screens
from screens import (
    LoadingScreen, NightScreen, SetupScreen, ChatScreen, VoteScreen, GameOverScreen,
    NightResultScreen, VoteResultScreen, RoleRevealScreen
)

# Import game engine
from main import GameEngine
from network import spawn_agents_from_lobbies, check_agent_health, AgentCommunicator
from config import GAME_CONFIG, NETWORK_CONFIG


class MafiaGameApp(App):
    """Main Mafia Game TUI Application"""

    TITLE = "Mafia Game"
    SUB_TITLE = "Homomorphic Encryption Edition"

    def __init__(self):
        super().__init__()
        self.game_engine: GameEngine = None
        self.api_key: str = None
        self.lobby_addresses: list = []

    def _get_players_data(self) -> List[dict]:
        """플레이어 데이터를 dict 리스트로 변환"""
        return [
            {
                "index": p.index,
                "name": p.name,
                "alive": p.alive
            }
            for p in self.game_engine.players
        ]

    async def _get_victim_roles(self, victim_indices: List[int]) -> dict:
        """사망자들의 역할을 가져옴"""
        victim_roles = {}
        for idx in victim_indices:
            player = self.game_engine.players[idx]
            if player.is_human:
                # 휴먼 플레이어는 자신의 역할을 알고 있음
                victim_roles[idx] = self.game_engine.human_role
            else:
                # 에이전트에게 역할 요청
                role = await AgentCommunicator.get_agent_role(player)
                victim_roles[idx] = role
        return victim_roles

    async def _broadcast_death_roles(self, victim_roles: dict) -> None:
        """사망자 역할을 모든 에이전트에게 브로드캐스트"""
        if not victim_roles:
            return

        async with httpx.AsyncClient(timeout=5.0) as client:
            for player in self.game_engine.players:
                if not player.is_human:
                    try:
                        await client.post(
                            f"{player.address}/death_announcement",
                            json={"deaths": [
                                {"player_index": idx, "role": role}
                                for idx, role in victim_roles.items()
                            ]}
                        )
                    except Exception:
                        pass  # 실패해도 계속 진행

    async def on_mount(self) -> None:
        """Initialize application"""
        # Run game in background worker so UI remains responsive
        self.run_worker(self._start_game(), exclusive=True)

    async def _start_game(self) -> None:
        """Start the game flow"""
        # Check if we should use config
        use_config = NETWORK_CONFIG.get("use_config_lobbies", False)

        if use_config:
            # Auto-load from config
            from config import _load_openai_api_key
            self.api_key = _load_openai_api_key()
            self.lobby_addresses = NETWORK_CONFIG.get("lobby_addresses", [])

            if not self.api_key or not self.lobby_addresses:
                # Fall back to setup screen
                setup_screen = SetupScreen()
                self.push_screen(setup_screen)

                # Wait for setup completion
                timeout = 300
                elapsed = 0
                while not setup_screen.setup_complete and elapsed < timeout:
                    await asyncio.sleep(0.5)
                    elapsed += 0.5

                if not setup_screen.setup_complete:
                    self.exit()
                    return

                self.pop_screen()
        else:
            # Show setup screen
            setup_screen = SetupScreen()
            self.push_screen(setup_screen)

            # Wait for setup completion
            timeout = 300
            elapsed = 0
            while not setup_screen.setup_complete and elapsed < timeout:
                await asyncio.sleep(0.5)
                elapsed += 0.5

            if not setup_screen.setup_complete:
                self.exit()
                return

            self.pop_screen()

        # Set API key environment variable
        os.environ["OPENAI_API_KEY"] = self.api_key

        # Initialize game
        await self._initialize_game()

    async def _initialize_game(self) -> None:
        """Initialize game engine and agents"""
        loading_screen = LoadingScreen()
        self.push_screen(loading_screen)

        await asyncio.sleep(0.5)

        # Create game engine
        loading_screen.add_status("게임 엔진 생성 중...", "yellow")
        await asyncio.sleep(0.3)
        self.game_engine = GameEngine(http_port=9000)
        loading_screen.add_status("✓ 게임 엔진 생성 완료", "green")

        # Generate game ID
        import uuid
        game_id = str(uuid.uuid4())[:8]
        loading_screen.add_status(f"Game ID: {game_id}", "cyan")

        # Spawn agents from lobbies
        loading_screen.add_status(f"{len(self.lobby_addresses)}개의 AI 에이전트 생성 중...", "yellow")
        await asyncio.sleep(0.3)
        try:
            agent_addresses = await spawn_agents_from_lobbies(
                self.lobby_addresses,
                self.api_key,
                game_id
            )
            loading_screen.add_status(f"✓ {len(agent_addresses)}개 에이전트 생성 완료", "green")
        except Exception as e:
            loading_screen.add_status(f"✗ 에이전트 생성 실패: {e}", "red")
            await asyncio.sleep(3)
            self.exit()
            return

        # Setup game
        loading_screen.add_status("게임 설정 중...", "yellow")
        await asyncio.sleep(0.3)
        await self.game_engine.setup_game(
            num_ai_agents=len(agent_addresses),
            ai_addresses=agent_addresses,
            game_id=game_id
        )
        loading_screen.add_status("✓ 게임 설정 완료", "green")

        # Note: Agent initialization is now part of setup_game (blind role assignment)
        loading_screen.add_status("✓ 모든 에이전트 초기화 완료", "green")

        await asyncio.sleep(1)
        self.app.pop_screen()

        # Show role reveal screen
        role_reveal = RoleRevealScreen(
            role=self.game_engine.human_role or "citizen",
            players=self._get_players_data(),
            human_index=self.game_engine.human_player_index,
            auto_continue_seconds=7
        )
        self.push_screen(role_reveal)

        # Wait for role reveal to complete
        while not role_reveal.should_continue:
            await asyncio.sleep(0.3)
        self.pop_screen()

        # Start game loop
        await self._run_game()

    async def _run_game(self) -> None:
        """Run the game loop with TUI"""
        try:
            # Game loop - integrate with existing GameEngine
            while True:
                # ========== Night Phase ==========
                human_player = self.game_engine.players[self.game_engine.human_player_index]
                survivors = self.game_engine.get_survivors()

                # Create and show night screen
                night_screen = NightScreen(
                    self.game_engine.game_phases.day_number,
                    human_player.alive,
                    self.game_engine.human_role,
                    survivors,
                    players=self._get_players_data(),
                    human_index=self.game_engine.human_player_index
                )

                # Push screen and wait for action submission
                self.push_screen(night_screen)

                # Wait for human to submit action if needed
                while not night_screen.action_submitted:
                    await asyncio.sleep(0.5)

                # Pass TUI action to game engine
                if human_player.alive and night_screen.selected_target is not None:
                    self.game_engine.pending_human_action = night_screen.selected_target
                    self.game_engine.human_action_ready = True
                else:
                    self.game_engine.pending_human_action = -1  # Abstain
                    self.game_engine.human_action_ready = True

                night_screen.add_message("⏳ 모든 플레이어를 기다리는 중...", "yellow")

                # Execute night phase in background
                await self.game_engine.execute_night_phase()
                self.pop_screen()

                # ========== Night Result Screen ==========
                killed_players = self.game_engine.game_phases.last_killed or []

                # 플레이어 데이터 업데이트 (사망 반영)
                players_data = self._get_players_data()

                # 사망자 역할 가져오기 및 에이전트에게 브로드캐스트
                victim_roles = await self._get_victim_roles(killed_players)
                await self._broadcast_death_roles(victim_roles)

                # 경찰 조사 결과 가져오기 (human이 경찰인 경우)
                investigation_result = None
                if self.game_engine.human_role == "police" and self.game_engine.crypto_ops:
                    target = self.game_engine.crypto_ops.last_investigation_target
                    is_mafia = self.game_engine.crypto_ops.last_investigation_result
                    if target is not None and is_mafia is not None:
                        investigation_result = {"target": target, "is_mafia": is_mafia}
                    # 결과 초기화 (다음 밤을 위해)
                    self.game_engine.crypto_ops.last_investigation_target = None
                    self.game_engine.crypto_ops.last_investigation_result = None

                night_result_screen = NightResultScreen(
                    day_number=self.game_engine.game_phases.day_number,
                    killed_players=killed_players,
                    players=players_data,
                    human_index=self.game_engine.human_player_index,
                    human_role=self.game_engine.human_role,
                    victim_roles=victim_roles,
                    investigation_result=investigation_result,
                    auto_continue_seconds=5
                )

                self.push_screen(night_result_screen)

                # Wait for continue
                await night_result_screen.continue_event.wait()
                self.pop_screen()

                # Check win condition
                winner = await self.game_engine.check_win_condition()
                if winner:
                    # DKG threshold decryption으로 모든 역할 복호화
                    all_roles = await self.game_engine.decrypt_all_roles()

                    # Show game over screen with all roles revealed
                    game_over_screen = GameOverScreen(
                        winner,
                        self.game_engine.players,
                        roles=all_roles,
                        human_index=self.game_engine.human_player_index
                    )
                    self.push_screen(game_over_screen)
                    # Game over screen will call app.exit() when user presses exit
                    # Keep loop alive until app.exit() is called
                    while True:
                        await asyncio.sleep(1)

                # ========== Day Phase (Discussion) ==========
                self.game_engine.phase = "day"
                chat_duration = 120  # 2 minutes for chat

                # Start agent chat phase - request all agents to start chatting
                survivors = self.game_engine.get_survivors()
                dead = self.game_engine.get_dead_players()

                # Request agents to start chatting in background (long timeout for LLM)
                async def start_agent_chat():
                    import httpx
                    # 긴 timeout - Agent가 LLM 호출하고 chat 메시지 생성하는데 시간 필요
                    async with httpx.AsyncClient(timeout=120.0) as client:
                        tasks = []
                        for player in self.game_engine.players:
                            if not player.is_human and player.alive:
                                tasks.append(
                                    client.post(
                                        f"{player.address}/request_action",
                                        json={
                                            "phase": "chat",
                                            "message": f"Day {self.game_engine.game_phases.day_number} discussion has begun.",
                                            "survivors": survivors,
                                            "dead_players": dead,
                                            "remaining_time": chat_duration
                                        }
                                    )
                                )
                        if tasks:
                            await asyncio.gather(*tasks, return_exceptions=True)

                # Start agents chatting in background
                asyncio.create_task(start_agent_chat())

                await self.game_engine.broadcast_update("day", f"Day {self.game_engine.game_phases.day_number} discussion has begun.")

                # Show chat screen with timer
                chat_screen = ChatScreen(self.game_engine, duration_seconds=chat_duration)
                self.push_screen(chat_screen)

                # Wait for user to proceed or timeout
                while not chat_screen.should_proceed:
                    await asyncio.sleep(0.5)

                self.pop_screen()  # Remove ChatScreen

                # ========== Vote Phase ==========
                self.game_engine.phase = "vote"
                human_player = self.game_engine.players[self.game_engine.human_player_index]
                survivors = self.game_engine.get_survivors()
                dead = self.game_engine.get_dead_players()
                player_names = [p.name for p in self.game_engine.players]

                # Start agent voting in background (before showing vote screen)
                async def start_agent_voting():
                    async with httpx.AsyncClient(timeout=120.0) as client:
                        tasks = []
                        for player in self.game_engine.players:
                            if not player.is_human and player.alive:
                                tasks.append(
                                    client.post(
                                        f"{player.address}/request_action",
                                        json={
                                            "phase": "vote",
                                            "message": f"Day {self.game_engine.game_phases.day_number} vote phase.",
                                            "survivors": survivors,
                                            "dead_players": dead
                                        }
                                    )
                                )
                        if tasks:
                            await asyncio.gather(*tasks, return_exceptions=True)

                # Start agents voting in background immediately
                agent_vote_task = asyncio.create_task(start_agent_voting())

                # Create and show vote screen
                vote_screen = VoteScreen(
                    self.game_engine.game_phases.day_number,
                    human_player.alive,
                    survivors,
                    player_names,
                    players=self._get_players_data(),
                    human_index=self.game_engine.human_player_index,
                    human_role=self.game_engine.human_role
                )

                self.push_screen(vote_screen)

                # Wait for vote submission
                while not vote_screen.vote_submitted:
                    await asyncio.sleep(0.5)

                # Pass TUI vote to game engine
                if human_player.alive and vote_screen.selected_target is not None:
                    self.game_engine.pending_human_action = vote_screen.selected_target
                    self.game_engine.human_action_ready = True
                else:
                    self.game_engine.pending_human_action = -1  # Abstain
                    self.game_engine.human_action_ready = True

                vote_screen.add_message("⏳ 모든 플레이어의 투표를 수집하는 중...", "yellow")

                # Wait for agent voting to complete
                await agent_vote_task

                # Execute vote phase in background
                await self.game_engine.execute_vote_phase()
                self.pop_screen()

                # ========== Vote Result Screen ==========
                voted_out = self.game_engine.game_phases.last_voted_out
                vote_counts = getattr(self.game_engine.game_phases, 'last_vote_counts', None)

                # 플레이어 데이터 업데이트 (사망 반영)
                players_data = self._get_players_data()

                # 사망자 역할 가져오기 및 에이전트에게 브로드캐스트
                vote_victims = [voted_out] if voted_out is not None else []
                victim_roles = await self._get_victim_roles(vote_victims)
                await self._broadcast_death_roles(victim_roles)

                vote_result_screen = VoteResultScreen(
                    day_number=self.game_engine.game_phases.day_number,
                    voted_out_player=voted_out,
                    players=players_data,
                    vote_counts=vote_counts,
                    human_index=self.game_engine.human_player_index,
                    human_role=self.game_engine.human_role,
                    victim_roles=victim_roles,
                    auto_continue_seconds=5
                )

                self.push_screen(vote_result_screen)

                # Wait for continue
                await vote_result_screen.continue_event.wait()
                self.pop_screen()

                # Check win condition
                winner = await self.game_engine.check_win_condition()
                if winner:
                    # DKG threshold decryption으로 모든 역할 복호화
                    all_roles = await self.game_engine.decrypt_all_roles()

                    # Show game over screen with all roles revealed
                    game_over_screen = GameOverScreen(
                        winner,
                        self.game_engine.players,
                        roles=all_roles,
                        human_index=self.game_engine.human_player_index
                    )
                    self.push_screen(game_over_screen)
                    # Game over screen will call app.exit() when user presses exit
                    # Keep loop alive until app.exit() is called
                    while True:
                        await asyncio.sleep(1)

        except KeyboardInterrupt:
            pass
        except Exception as e:
            # Log any unexpected errors
            import traceback
            print(f"Error in game loop: {e}")
            traceback.print_exc()
        finally:
            # Only exit if not already exiting from game over screen
            pass  # App will exit from GameOverScreen.action_exit_game()


# ============================================================================
# Entry Point
# ============================================================================

async def run_game_tui():
    """Run the complete game with TUI"""
    app = MafiaGameApp()
    await app.run_async()


if __name__ == "__main__":
    asyncio.run(run_game_tui())
