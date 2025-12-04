"""
Vote Screen for Elimination Phase
"""
from textual.app import ComposeResult
from textual.widgets import Header, Footer, Label, RichLog, Button, OptionList
from textual.widgets.option_list import Option
from textual.containers import Container, Vertical, Horizontal
from textual.binding import Binding
from textual.screen import Screen
from rich.text import Text
from typing import Optional, List
import asyncio


class VoteScreen(Screen):
    """Voting phase screen"""
    
    CSS = """
    VoteScreen {
        background: $surface;
    }
    
    #game_info {
        dock: top;
        height: 3;
        background: $primary;
        content-align: center middle;
    }
    
    #vote_container {
        width: 100%;
        height: 100%;
        align: center middle;
    }
    
    #vote_panel {
        width: 80;
        height: auto;
        background: $panel;
        border: solid $primary;
        padding: 2;
    }
    
    #vote_title {
        text-align: center;
        color: $warning;
        text-style: bold;
        margin-bottom: 1;
    }
    
    #vote_instructions {
        text-align: center;
        color: $text-muted;
        margin-bottom: 2;
    }
    
    #player_list {
        height: 15;
        margin-bottom: 1;
        border: solid $accent;
    }
    
    #button_container {
        width: 100%;
        height: auto;
        align: center middle;
    }
    
    .vote_button {
        margin: 0 1;
    }
    
    #message_log {
        height: 8;
        background: $surface-darken-1;
        margin-top: 1;
    }
    """
    
    BINDINGS = [
        Binding("escape", "app.quit", "Quit"),
    ]
    
    def __init__(self, day_number: int, is_alive: bool, survivors: List[int], player_names: List[str]):
        super().__init__()
        self.day_number = day_number
        self.is_alive = is_alive
        self.survivors = survivors
        self.player_names = player_names
        self.selected_target: Optional[int] = None
        self.vote_submitted = False
        self.dismiss_event = asyncio.Event()
    
    def compose(self) -> ComposeResult:
        yield Header()
        
        # Game info bar
        with Container(id="game_info"):
            yield Label(id="info_label")
        
        # Main vote panel
        with Container(id="vote_container"):
            with Vertical(id="vote_panel"):
                yield Label("🗳️  VOTING PHASE", id="vote_title")
                
                if self.is_alive:
                    yield Label("Select a player to eliminate:", id="vote_instructions")
                    yield OptionList(id="player_list")
                    
                    with Horizontal(id="button_container"):
                        yield Button("Submit Vote", id="submit_btn", variant="primary", classes="vote_button")
                        yield Button("Abstain", id="abstain_btn", variant="default", classes="vote_button")
                else:
                    yield Label("You are dead and cannot vote.", id="vote_instructions")
                
                yield RichLog(id="message_log", highlight=True, markup=True)
        
        yield Footer()
    
    async def on_mount(self) -> None:
        """Initialize vote screen"""
        # Update game info
        alive_count = len(self.survivors)
        info = self.query_one("#info_label", Label)
        info.update(f"Day {self.day_number} | VOTING | Alive: {alive_count}")
        
        # Add message
        log = self.query_one("#message_log", RichLog)
        log.write(Text("=" * 60, style="bold yellow"))
        log.write(Text(f"DAY {self.day_number} - VOTING", style="bold cyan"))
        log.write(Text("=" * 60, style="bold yellow"))
        
        if self.is_alive:
            # Populate player list
            player_list = self.query_one("#player_list", OptionList)
            for survivor_idx in self.survivors:
                player_list.add_option(Option(
                    f"Player {survivor_idx}: {self.player_names[survivor_idx]}",
                    id=str(survivor_idx)
                ))
            
            log.write(Text("Select a player to eliminate from the list above.", style="dim"))
        else:
            log.write(Text("You cannot participate in voting.", style="red"))
            # Auto-submit for dead player
            self.selected_target = -1
            self.vote_submitted = True
    
    def on_option_list_option_selected(self, event: OptionList.OptionSelected) -> None:
        """Handle player selection"""
        try:
            self.selected_target = int(event.option.id)
            log = self.query_one("#message_log", RichLog)
            log.write(Text(f"Selected: {event.option.prompt}", style="cyan"))
        except Exception as e:
            self.add_message(f"Error selecting player: {e}", "red")
    
    def on_button_pressed(self, event: Button.Pressed) -> None:
        """Handle button clicks"""
        if event.button.id == "submit_btn":
            if self.selected_target is not None:
                self.vote_submitted = True
                self.add_message(f"✓ Vote submitted for Player {self.selected_target}", "green")
                self.add_message("Waiting for other players to vote...", "dim")
                # Disable buttons
                self.query_one("#submit_btn", Button).disabled = True
                self.query_one("#abstain_btn", Button).disabled = True
            else:
                self.add_message("⚠️ Please select a player first", "yellow")
        
        elif event.button.id == "abstain_btn":
            self.selected_target = -1  # Abstain
            self.vote_submitted = True
            self.add_message("✓ Abstained from voting", "yellow")
            self.add_message("Waiting for other players to vote...", "dim")
            # Disable buttons
            self.query_one("#submit_btn", Button).disabled = True
            self.query_one("#abstain_btn", Button).disabled = True
    
    def add_message(self, message: str, style: str = "white") -> None:
        """Add a message to the log"""
        log = self.query_one("#message_log", RichLog)
        log.write(Text(message, style=style))
