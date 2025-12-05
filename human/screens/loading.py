"""
Loading Screen for Game Initialization
"""
from textual.app import ComposeResult
from textual.widgets import Header, Footer, Label, RichLog, LoadingIndicator
from textual.containers import Container
from textual.screen import Screen
from rich.text import Text


class LoadingScreen(Screen):
    """Loading screen during game initialization"""
    
    CSS = """
    LoadingScreen {
        background: $surface;
    }
    
    #loading_container {
        width: 100%;
        height: 100%;
        background: $surface;
        padding: 2;
    }
    
    .loading_title {
        text-align: center;
        text-style: bold;
        color: $accent;
        margin-bottom: 1;
    }
    
    #status_log {
        height: 1fr;
        margin: 1 0;
    }
    """
    
    def compose(self) -> ComposeResult:
        yield Header()
        
        with Container(id="loading_container"):
            yield Label("🎮 게임 초기화 중...", classes="loading_title")
            yield LoadingIndicator()
            yield RichLog(id="status_log", highlight=True, markup=True, auto_scroll=True)
        
        yield Footer()
    
    def add_status(self, message: str, style: str = "white"):
        """Add a status message"""
        log = self.query_one("#status_log", RichLog)
        log.write(Text(message, style=style))
