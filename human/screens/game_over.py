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
from typing import List


class GameOverScreen(Screen):
    """Game over screen showing final results"""
    
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
        width: 80;
        height: auto;
        background: $panel;
        border: solid $primary;
        padding: 2;
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
        margin: 1 auto;
    }
    """
    
    BINDINGS = [
        Binding("enter", "exit_game", "Exit"),
        Binding("escape", "exit_game", "Exit"),
    ]
    
    def __init__(self, winner: str, players: List):
        super().__init__()
        self.winner = winner
        self.players = players
    
    def compose(self) -> ComposeResult:
        yield Header()
        
        with Container(id="game_over_container"):
            with Vertical(id="result_panel"):
                yield Label(id="winner_title")
                yield Static(id="roles_table")
                yield Button("Exit Game", id="exit_button", variant="primary")
        
        yield Footer()
    
    def on_mount(self) -> None:
        """Initialize game over screen"""
        # Winner announcement
        winner_label = self.query_one("#winner_title", Label)
        if self.winner == "citizens":
            winner_label.update("🎉 CITIZENS WIN! 🎉")
            winner_label.styles.color = "green"
        else:
            winner_label.update("👿 MAFIA WINS! 👿")
            winner_label.styles.color = "red"
        
        # Create roles table
        table = Table(title="Final Roles", show_header=True, header_style="bold cyan")
        table.add_column("Player", style="cyan", no_wrap=True)
        table.add_column("Name", style="white")
        table.add_column("Role", style="yellow")
        table.add_column("Status", style="dim")
        
        for player in self.players:
            status = "✓ ALIVE" if player.alive else "💀 DEAD"
            status_style = "green" if player.alive else "red"
            
            table.add_row(
                f"Player {player.index}",
                player.name,
                player.role.upper(),
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
