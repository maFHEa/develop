"""
Game Over Screen
"""
from textual.app import ComposeResult
from textual.widgets import Header, Footer, Label, Static, Button
from textual.containers import Container, Vertical
from textual.binding import Binding
from textual.screen import Screen
from rich.text import Text
from rich.table import Table
from typing import List, Optional


# 역할 아이콘 및 한글 이름
ROLE_DISPLAY = {
    "mafia": ("🔪", "마피아"),
    "doctor": ("💉", "의사"),
    "police": ("🔍", "경찰"),
    "citizen": ("👤", "시민"),
}


class GameOverScreen(Screen):
    """Game over screen showing final results with all roles revealed"""

    CSS = """
    GameOverScreen {
        background: $surface;
    }

    #game_over_container {
        width: 100%;
        height: 100%;
        align: center middle;
    }

    #result_panel {
        width: 90;
        height: auto;
        background: $panel;
        border: solid $primary;
        padding: 2;
        align-horizontal: center;
    }

    #winner_title {
        text-align: center;
        text-style: bold;
        margin-bottom: 2;
        height: auto;
    }

    #roles_table {
        width: 100%;
        height: auto;
        margin-bottom: 2;
    }

    #exit_button {
        width: 20;
        margin-top: 2;
    }
    """

    BINDINGS = [
        Binding("enter", "exit_game", "Exit"),
        Binding("escape", "exit_game", "Exit"),
    ]

    def __init__(self, winner: str, players: List, roles: Optional[List[str]] = None, human_index: int = 0):
        super().__init__()
        self.winner = winner
        self.players = players
        self.roles = roles or []  # DKG 복호화된 모든 역할
        self.human_index = human_index

    def compose(self) -> ComposeResult:
        yield Header()
        yield Footer()

        with Container(id="game_over_container"):
            with Vertical(id="result_panel"):
                yield Label(id="winner_title")
                yield Static(id="roles_table")
                yield Button("게임 종료", id="exit_button", variant="primary")

    def on_mount(self) -> None:
        """Initialize game over screen"""
        # Winner announcement
        winner_label = self.query_one("#winner_title", Label)
        if self.winner == "citizens":
            winner_label.update("🎉 시민 승리! 🎉")
            winner_label.styles.color = "green"
        else:
            winner_label.update("👿 마피아 승리! 👿")
            winner_label.styles.color = "red"

        # Create roles table with revealed roles
        table = Table(title="🎭 최종 결과 - 모든 역할 공개", show_header=True, header_style="bold cyan")
        table.add_column("플레이어", style="cyan", no_wrap=True)
        table.add_column("이름", style="white")
        table.add_column("역할", style="bold")
        table.add_column("상태", style="dim")

        for i, player in enumerate(self.players):
            # 역할 정보
            role = self.roles[i] if i < len(self.roles) else "unknown"
            role_icon, role_name = ROLE_DISPLAY.get(role.lower(), ("❓", role))

            # 마피아는 빨간색, 시민팀은 파란색
            if role.lower() == "mafia":
                role_display = f"[bold red]{role_icon} {role_name}[/bold red]"
            else:
                role_display = f"[bold blue]{role_icon} {role_name}[/bold blue]"

            # 상태
            status = "😊 생존" if player.alive else "💀 사망"
            status_style = "green" if player.alive else "red"

            # 플레이어 이름 (나 표시)
            player_name = f"플레이어 {player.index}"
            if player.index == self.human_index:
                player_name += " (나)"

            table.add_row(
                player_name,
                player.name,
                role_display,
                f"[{status_style}]{status}[/{status_style}]"
            )

        roles_static = self.query_one("#roles_table", Static)
        roles_static.update(table)
        
        # Focus exit button
        self.query_one("#exit_button", Button).focus()
    
    def on_button_pressed(self, event: Button.Pressed) -> None:
        """Handle button press"""
        if event.button.id == "exit_button":
            self.action_exit_game()
    
    def action_exit_game(self) -> None:
        """Exit the game"""
        self.app.exit()
