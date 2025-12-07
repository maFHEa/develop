"""
Loading Screen for Game Initialization
"""
from textual.app import ComposeResult
from textual.widgets import Header, Footer, Static, LoadingIndicator
from textual.containers import Container, Vertical, Center
from textual.screen import Screen


class LoadingScreen(Screen):
    """Loading screen during game initialization"""

    CSS = """
    LoadingScreen {
        background: $surface;
    }

    #loading_container {
        width: 100%;
        height: 1fr;
        align: center middle;
    }

    #loading_content {
        width: 60;
        height: auto;
        align: center middle;
        content-align: center middle;
    }

    .loading_title {
        width: 100%;
        text-align: center;
        text-style: bold;
        color: $accent;
        margin-bottom: 1;
    }

    LoadingIndicator {
        width: 100%;
        height: 3;
        content-align: center middle;
    }

    #status_text {
        width: 100%;
        text-align: center;
        color: $text-muted;
        margin-top: 1;
    }
    """

    def compose(self) -> ComposeResult:
        yield Header()
        yield Footer()

        with Center(id="loading_container"):
            with Vertical(id="loading_content"):
                yield Static("🎮 게임 초기화", classes="loading_title")
                yield LoadingIndicator()
                yield Static("", id="status_text")

    def add_status(self, message: str, style: str = "white"):
        """Update status message (overwrites previous)"""
        try:
            status = self.query_one("#status_text", Static)
            status.update(message)
        except Exception:
            pass
