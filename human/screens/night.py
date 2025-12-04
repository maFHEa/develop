"""
Night Phase Screen
"""
from textual.app import ComposeResult
from textual.widgets import Header, Footer, Label, RichLog, Input, Button
from textual.containers import Container, Horizontal
from textual.binding import Binding
from textual.screen import Screen
from textual import on
from rich.text import Text
from typing import Optional
import asyncio


class NightScreen(Screen):
    """Night phase screen - shows what's happening"""
    
    CSS = """
    NightScreen {
        background: $surface;
    }
    
    #night_container {
        width: 100%;
        height: 100%;
        background: $surface-darken-1;
        padding: 2;
    }
    
    .night_title {
        text-align: center;
        text-style: bold;
        color: $secondary;
        margin-bottom: 1;
    }
    
    #night_log {
        height: 1fr;
        margin: 1 0;
    }
    
    #action_container {
        height: auto;
        margin: 1 0;
    }
    
    .action_label {
        width: 30;
        content-align: left middle;
    }
    
    #target_input {
        width: 20;
    }
    
    .button_row {
        height: auto;
        align: center middle;
        margin-top: 1;
    }
    """
    
    BINDINGS = [
        Binding("escape", "app.quit", "Quit"),
    ]
    
    def __init__(self, day_number: int, is_human_alive: bool, human_role: str, survivors: list):
        super().__init__()
        self.day_number = day_number
        self.is_human_alive = is_human_alive
        self.human_role = human_role
        self.survivors = survivors
        self.can_proceed = False
        self.selected_target: Optional[int] = None
        self.action_submitted = False
        self.dismiss_event = asyncio.Event()
    
    def compose(self) -> ComposeResult:
        yield Header()
        
        with Container(id="night_container"):
            yield Label(f"🌙 Night {self.day_number}", classes="night_title")
            yield RichLog(id="night_log", highlight=True, markup=True, auto_scroll=True)
            
            # Action input (only for active roles)
            if self.is_human_alive and self.human_role in ["mafia", "doctor", "police"]:
                with Horizontal(id="action_container"):
                    yield Label("Target player index:", classes="action_label")
                    yield Input(placeholder="0, 1, 2, ...", id="target_input")
                    yield Button("Submit", id="submit_action", variant="primary")
        
        yield Footer()
    
    async def on_mount(self) -> None:
        """Initialize night screen"""
        log = self.query_one("#night_log", RichLog)
        
        log.write(Text("=" * 60, style="bold"))
        log.write(Text(f"NIGHT {self.day_number}", style="bold yellow"))
        log.write(Text("=" * 60, style="bold"))
        log.write("")
        
        survivors_str = ", ".join(str(i) for i in self.survivors)
        log.write(Text(f"Alive players: [{survivors_str}]", style="cyan"))
        log.write("")
        
        if self.is_human_alive:
            if self.human_role == "mafia":
                log.write(Text("🔪 You are MAFIA - choose your target to kill", style="red"))
            elif self.human_role == "doctor":
                log.write(Text("💉 You are DOCTOR - choose who to protect", style="green"))
            elif self.human_role == "police":
                log.write(Text("🔍 You are POLICE - choose who to investigate", style="cyan"))
            else:
                log.write(Text("😴 You are sleeping...", style="dim"))
                log.write(Text("Other players with special roles are acting", style="dim"))
                self.action_submitted = True
        else:
            log.write(Text("💀 You are dead", style="red"))
            log.write(Text("Watch as the night unfolds...", style="dim"))
            self.action_submitted = True
        
        if self.human_role in ["mafia", "doctor", "police"] and self.is_human_alive:
            log.write("")
            log.write(Text("Enter the player index and click Submit", style="yellow"))
    
    @on(Button.Pressed, "#submit_action")
    async def submit_action(self):
        """Submit night action"""
        if self.action_submitted:
            return
        
        try:
            target_input = self.query_one("#target_input", Input)
            target = int(target_input.value.strip())
            
            if target not in self.survivors:
                self.add_message(f"❌ Invalid target: {target} is not alive", "red")
                return
            
            self.selected_target = target
            self.action_submitted = True
            
            # Disable input
            target_input.disabled = True
            self.query_one("#submit_action", Button).disabled = True
            
            self.add_message(f"✓ Action submitted: Target = {target}", "green")
            self.add_message("Waiting for other players...", "yellow")
            
        except ValueError:
            self.add_message("❌ Please enter a valid number", "red")
    
    def add_message(self, message: str, style: str = "white"):
        """Add a message to the log"""
        log = self.query_one("#night_log", RichLog)
        log.write(Text(message, style=style))
