"""
Setup Screen for Game Configuration
"""
from textual.app import ComposeResult
from textual.widgets import Header, Footer, Label, RichLog, Input, Button
from textual.containers import ScrollableContainer, Horizontal
from textual.binding import Binding
from textual.screen import Screen
from textual import on
from rich.text import Text
from typing import List


class SetupScreen(Screen):
    """Initial game setup screen"""
    
    CSS = """
    SetupScreen {
        background: $surface;
    }
    
    #setup_container {
        width: 100%;
        height: 100%;
        background: $surface;
        padding: 2;
    }
    
    .setup_title {
        text-align: center;
        text-style: bold;
        color: $accent;
        margin-bottom: 1;
    }
    
    .input_row {
        height: auto;
        margin: 1 0;
    }
    
    .label {
        width: 30;
        content-align: left middle;
    }
    
    .input_field {
        width: 1fr;
    }
    
    #lobby_list {
        height: 1fr;
        margin: 1 0;
    }
    
    .button_row {
        height: auto;
        align: center middle;
        margin-top: 1;
    }
    
    Button {
        margin: 0 1;
    }
    """
    
    BINDINGS = [
        Binding("escape", "quit", "Quit"),
    ]
    
    def __init__(self):
        super().__init__()
        self.lobby_addresses: List[str] = []
        self.config_loaded = False
        self.setup_complete = False
    
    def compose(self) -> ComposeResult:
        yield Header()
        
        with ScrollableContainer(id="setup_container"):
            yield Label("🎮 마피아 게임 - 설정", classes="setup_title")
            yield Label("")

            # Number of AI agents
            with Horizontal(classes="input_row"):
                yield Label("AI 에이전트 수:", classes="label")
                yield Input(placeholder="3-9 에이전트", id="num_agents", classes="input_field")

            # API Key
            with Horizontal(classes="input_row"):
                yield Label("OpenAI API Key:", classes="label")
                yield Input(placeholder="sk-...", password=True, id="api_key", classes="input_field")

            yield Label("")
            yield Label("로비 주소 (한 줄에 하나씩):", classes="label")
            
            # Lobby address input
            with Horizontal(classes="input_row"):
                yield Input(placeholder="http://localhost:8000", id="lobby_input", classes="input_field")
                yield Button("Add", id="add_lobby", variant="primary")
            
            # Lobby list
            yield RichLog(id="lobby_list", highlight=False, markup=True)
            
            # Action buttons
            with Horizontal(classes="button_row"):
                yield Button("설정 파일에서 불러오기", id="load_config", variant="default")
                yield Button("게임 시작", id="start_game", variant="success")
                yield Button("종료", id="quit_btn", variant="error")
        
        yield Footer()
    
    async def on_mount(self) -> None:
        """Initialize with defaults"""
        # Try to load API key from environment
        from config import _load_openai_api_key
        api_key = _load_openai_api_key()
        if api_key:
            self.query_one("#api_key", Input).value = api_key
        
        self._update_lobby_display()
    
    @on(Button.Pressed, "#add_lobby")
    async def add_lobby(self) -> None:
        """Add a lobby address"""
        lobby_input = self.query_one("#lobby_input", Input)
        address = lobby_input.value.strip()
        
        if not address:
            return
        
        if not address.startswith("http://") and not address.startswith("https://"):
            address = f"http://{address}"
        
        self.lobby_addresses.append(address)
        lobby_input.value = ""
        self._update_lobby_display()
    
    @on(Button.Pressed, "#load_config")
    async def load_from_config(self) -> None:
        """Load lobby addresses from config"""
        from config import NETWORK_CONFIG
        
        if not NETWORK_CONFIG.get("use_config_lobbies", False):
            self._show_error("설정 파일의 'use_config_lobbies'가 False입니다")
            return

        configured = NETWORK_CONFIG.get("lobby_addresses", [])
        if not configured:
            self._show_error("설정 파일에 로비 주소가 없습니다")
            return
        
        self.lobby_addresses = configured.copy()
        self.config_loaded = True
        self._update_lobby_display()
    
    @on(Button.Pressed, "#start_game")
    async def start_game(self) -> None:
        """Validate and start the game"""
        from config import GAME_CONFIG
        
        # Validate inputs
        api_key = self.query_one("#api_key", Input).value.strip()
        if not api_key:
            self._show_error("API Key가 필요합니다")
            return

        num_agents = len(self.lobby_addresses)
        total_players = num_agents + 1

        if total_players < GAME_CONFIG["min_players"] or total_players > GAME_CONFIG["max_players"]:
            self._show_error(f"{GAME_CONFIG['min_players']-1}~{GAME_CONFIG['max_players']-1}명의 에이전트가 필요합니다")
            return
        
        # Pass data to main app
        self.app.api_key = api_key
        self.app.lobby_addresses = self.lobby_addresses.copy()
        self.setup_complete = True
    
    @on(Button.Pressed, "#quit_btn")
    async def quit_game(self) -> None:
        """Quit the application"""
        self.app.exit()
    
    def _update_lobby_display(self) -> None:
        """Update the lobby list display"""
        log = self.query_one("#lobby_list", RichLog)
        log.clear()
        
        if not self.lobby_addresses:
            log.write(Text("추가된 로비가 없습니다", style="dim"))
        else:
            for i, addr in enumerate(self.lobby_addresses, 1):
                log.write(Text(f"{i}. {addr}", style="green"))

            total = len(self.lobby_addresses) + 1
            log.write(Text(f"\n총 플레이어 수: {total}", style="bold cyan"))
    
    def _show_error(self, message: str) -> None:
        """Display an error message"""
        log = self.query_one("#lobby_list", RichLog)
        log.write(Text(f"❌ {message}", style="bold red"))
