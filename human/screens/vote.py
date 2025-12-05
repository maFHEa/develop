"""
Vote Screen for Elimination Phase
"""
from textual.app import ComposeResult
from textual.widgets import Header, Footer, Label, RichLog, Button
from textual.containers import Container, Vertical, Horizontal
from textual.binding import Binding
from textual.screen import Screen
from rich.text import Text
from typing import Optional, List
import asyncio

from .components import PlayerStatusBar, PlayerCard


class VoteScreen(Screen):
    """Voting phase screen - click player cards to vote"""

    CSS = """
    VoteScreen {
        background: $surface;
    }

    #player_bar {
        dock: top;
    }

    #vote_container {
        width: 100%;
        height: 1fr;
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

    #button_container {
        width: 100%;
        height: auto;
        align: center middle;
        margin-top: 1;
    }

    .vote_button {
        margin: 0 1;
    }

    #message_log {
        height: 10;
        background: $surface-darken-1;
        margin-top: 1;
    }
    """

    BINDINGS = [
        Binding("escape", "app.quit", "Quit"),
    ]

    def __init__(
        self,
        day_number: int,
        is_alive: bool,
        survivors: List[int],
        player_names: List[str],
        players: List[dict] = None,
        human_index: int = 0,
        human_role: str = "citizen"
    ):
        super().__init__()
        self.day_number = day_number
        self.is_alive = is_alive
        self.survivors = survivors
        self.player_names = player_names
        self.players = players or []
        self.human_index = human_index
        self.human_role = human_role
        self.selected_target: Optional[int] = None
        self.vote_submitted = False
        self.dismiss_event = asyncio.Event()

    def compose(self) -> ComposeResult:
        yield Header()

        # 클릭 가능한 플레이어 상태바
        if self.players:
            yield PlayerStatusBar(
                players=self.players,
                human_index=self.human_index,
                human_role=self.human_role,
                show_human_role=True,
                title=f"🗳️ Day {self.day_number} - Vote",
                selectable=self.is_alive,
                exclude_self=True,  # 자기 자신은 투표 불가
                id="player_bar"
            )

        # Main vote panel
        with Container(id="vote_container"):
            with Vertical(id="vote_panel"):
                yield Label("🗳️  투표 단계", id="vote_title")

                if self.is_alive:
                    yield Label("위의 플레이어 카드를 클릭하여 처형 대상을 투표하세요", id="vote_instructions")

                    with Horizontal(id="button_container"):
                        yield Button("투표 제출", id="submit_btn", variant="primary", classes="vote_button")
                        yield Button("기권", id="abstain_btn", variant="default", classes="vote_button")
                else:
                    yield Label("💀 사망하여 투표할 수 없습니다.", id="vote_instructions")

                yield RichLog(id="message_log", highlight=True, markup=True)

        yield Footer()

    async def on_mount(self) -> None:
        """Initialize vote screen"""
        log = self.query_one("#message_log", RichLog)

        if self.is_alive:
            log.write(Text("👆 위의 플레이어 카드를 클릭하여 투표 대상을 선택하세요", style="cyan"))
            log.write(Text("[투표 제출] 또는 [기권]을 클릭하세요", style="dim"))
        else:
            log.write(Text("💀 당신은 사망했습니다.", style="red"))
            log.write(Text("투표에 참여할 수 없습니다.", style="dim"))
            # Auto-submit for dead player
            self.selected_target = -1
            self.vote_submitted = True

    def on_player_card_selected(self, event: PlayerCard.Selected) -> None:
        """Handle player card click"""
        if self.vote_submitted:
            return

        # Clear previous selection
        player_bar = self.query_one("#player_bar", PlayerStatusBar)
        player_bar.clear_selections()

        # Set new selection
        self.selected_target = event.player_index
        player_bar.update_player(event.player_index, selected=True)


    def on_button_pressed(self, event: Button.Pressed) -> None:
        """Handle button clicks"""
        if event.button.id == "submit_btn":
            if self.selected_target is not None:
                self.vote_submitted = True
                self.add_message("⏳ 다른 플레이어의 투표를 기다리는 중...", "yellow")

                # Disable buttons and player selection
                self.query_one("#submit_btn", Button).disabled = True
                self.query_one("#abstain_btn", Button).disabled = True
                try:
                    player_bar = self.query_one("#player_bar", PlayerStatusBar)
                    player_bar.disable_all()
                except:
                    pass
            else:
                self.add_message("⚠️ 먼저 플레이어 카드를 클릭하세요", "yellow")

        elif event.button.id == "abstain_btn":
            self.selected_target = -1  # Abstain
            self.vote_submitted = True
            self.add_message("⏳ 다른 플레이어의 투표를 기다리는 중...", "yellow")

            # Disable buttons
            self.query_one("#submit_btn", Button).disabled = True
            self.query_one("#abstain_btn", Button).disabled = True
            try:
                player_bar = self.query_one("#player_bar", PlayerStatusBar)
                player_bar.disable_all()
            except:
                pass

    def add_message(self, message: str, style: str = "white") -> None:
        """Add a message to the log"""
        log = self.query_one("#message_log", RichLog)
        log.write(Text(message, style=style))
