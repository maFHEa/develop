"""
Main Application - Orchestrates Game Flow with TUI
"""
from textual.app import App
import asyncio
import os
import sys

# Import screens
from screens import LoadingScreen, NightScreen, SetupScreen, ChatScreen, VoteScreen, GameOverScreen

# Import game engine
from main import GameEngine, spawn_agents_from_lobbies, check_agent_health
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
        loading_screen.add_status("Creating game engine...", "yellow")
        await asyncio.sleep(0.3)
        self.game_engine = GameEngine()
        loading_screen.add_status("✓ Game engine created", "green")
        
        # Generate game ID
        import uuid
        game_id = str(uuid.uuid4())[:8]
        loading_screen.add_status(f"Game ID: {game_id}", "cyan")
        
        # Spawn agents from lobbies
        loading_screen.add_status(f"Spawning {len(self.lobby_addresses)} AI agents...", "yellow")
        await asyncio.sleep(0.3)
        try:
            agent_addresses = await spawn_agents_from_lobbies(
                self.lobby_addresses,
                self.api_key,
                game_id
            )
            loading_screen.add_status(f"✓ {len(agent_addresses)} agents spawned", "green")
        except Exception as e:
            loading_screen.add_status(f"✗ Failed to spawn agents: {e}", "red")
            await asyncio.sleep(3)
            self.exit()
            return
        
        # Setup game with DKG
        loading_screen.add_status("Running DKG protocol...", "yellow")
        await asyncio.sleep(0.3)
        await self.game_engine.setup_game(
            num_ai_agents=len(agent_addresses),
            ai_addresses=agent_addresses,
            game_id=game_id
        )
        loading_screen.add_status("✓ DKG and role assignment complete", "green")
        
        # Initialize agents
        loading_screen.add_status("Initializing agents with roles...", "yellow")
        await asyncio.sleep(0.3)
        await self.game_engine.initialize_agents()
        loading_screen.add_status("✓ All agents initialized", "green")
        
        await asyncio.sleep(1)
        self.pop_screen()

        # Start game loop
        await self._run_game()
    
    def safe_pop_screen(self) -> None:
        """Safely pop screen if there's more than one on the stack"""
        if len(self._screen_stack) > 1:
            self.pop_screen()

    async def _run_game(self) -> None:
        """Run the game loop with TUI"""
        try:
            # Game loop - integrate with existing GameEngine
            while True:
                # Night phase - use TUI
                human_player = self.game_engine.players[self.game_engine.human_player_index]
                survivors = self.game_engine.get_survivors()

                # Create and show night screen
                night_screen = NightScreen(
                    self.game_engine.day_number + 1,  # day_number increments in execute_night_phase
                    human_player.alive,
                    human_player.role,
                    survivors
                )

                # Push screen and wait for action submission
                self.push_screen(night_screen)

                # Wait for human to submit action if needed
                while not night_screen.action_submitted:
                    await asyncio.sleep(0.5)

                # Store human's target before executing night phase
                self.game_engine.human_night_target = night_screen.selected_target

                night_screen.add_message("⏳ Waiting for all players...", "yellow")

                # Execute night phase in background
                await self.game_engine.execute_night_phase()
                night_screen.add_message("✓ All actions collected", "green")
                await asyncio.sleep(1)

                # Show results
                if self.game_engine.last_killed:
                    for victim_index in self.game_engine.last_killed:
                        victim = self.game_engine.players[victim_index]
                        night_screen.add_message(f"💀 {victim.name} was killed!", "red")
                        await asyncio.sleep(0.5)
                else:
                    night_screen.add_message("✓ No one was killed", "green")
                    await asyncio.sleep(0.5)

                # Auto-proceed after showing results
                night_screen.add_message("\nProceeding to day phase...", "cyan")
                await asyncio.sleep(2)
                self.safe_pop_screen()
                
                winner = self.game_engine.check_win_condition()
                if winner:
                    # Show game over screen
                    game_over_screen = GameOverScreen(winner, self.game_engine.players)
                    self.push_screen(game_over_screen)
                    # Wait for user to exit (game over screen will call app.exit())
                    return
                
                # Day phase - use TUI
                self.game_engine.phase = "day"
                await self.game_engine.start_agent_chat_phase(duration_seconds=300)
                await self.game_engine.broadcast_update("day", f"Day {self.game_engine.day_number} discussion has begun.")
                
                # Show chat screen
                chat_screen = ChatScreen(self.game_engine)
                self.push_screen(chat_screen)
                
                # Wait for user to proceed or quit (Ctrl+D)
                while not chat_screen.should_proceed:
                    await asyncio.sleep(0.5)

                self.safe_pop_screen()
                
                await self.game_engine.stop_agent_chat_phase()
                
                # Vote phase - use TUI
                self.game_engine.phase = "vote"
                human_player = self.game_engine.players[self.game_engine.human_player_index]
                survivors = self.game_engine.get_survivors()
                player_names = [p.name for p in self.game_engine.players]
                
                # Create and show vote screen
                vote_screen = VoteScreen(
                    self.game_engine.day_number,
                    human_player.alive,
                    survivors,
                    player_names
                )
                
                self.push_screen(vote_screen)
                
                # Wait for vote submission
                while not vote_screen.vote_submitted:
                    await asyncio.sleep(0.5)
                
                # Store human's vote
                self.game_engine.human_vote_target = vote_screen.selected_target
                
                vote_screen.add_message("⏳ Collecting votes from all players...", "yellow")
                await asyncio.sleep(1)
                
                # Execute vote phase in background
                await self.game_engine.execute_vote_phase()
                
                vote_screen.add_message("✓ All votes collected", "green")
                await asyncio.sleep(1)
                
                # Show results
                if self.game_engine.last_voted_out is not None:
                    victim = self.game_engine.players[self.game_engine.last_voted_out]
                    vote_screen.add_message(f"💀 {victim.name} was voted out!", "red")
                else:
                    vote_screen.add_message("✓ No one was eliminated", "yellow")
                
                await asyncio.sleep(2)
                self.safe_pop_screen()
                
                winner = self.game_engine.check_win_condition()
                if winner:
                    # Show game over screen
                    game_over_screen = GameOverScreen(winner, self.game_engine.players)
                    self.push_screen(game_over_screen)
                    # Wait for user to exit (game over screen will call app.exit())
                    return
        
        except KeyboardInterrupt:
            pass
        finally:
            self.exit()


# ============================================================================
# Entry Point
# ============================================================================

async def run_game_tui():
    """Run the complete game with TUI"""
    app = MafiaGameApp()
    await app.run_async()


if __name__ == "__main__":
    asyncio.run(run_game_tui())
