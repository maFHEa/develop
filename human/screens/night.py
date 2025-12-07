"""
Night Phase Screen
"""
from textual.app import ComposeResult
from textual.widgets import Header, Footer, Label, Button
from textual.containers import Container, Vertical, Horizontal
from textual.binding import Binding
from textual.screen import Screen
from typing import Optional, List
import asyncio

from .components import PlayerStatusBar, PlayerCard


class NightScreen(Screen):
    """Night phase screen - click player cards to select target"""

    CSS = """
    NightScreen {
        background: $surface;
    }

    #player_bar {
        dock: top;
    }

    #night_container {
        width: 100%;
        height: 1fr;
        align: center middle;
    }

    #night_content {
        width: 100%;
        height: auto;
        align: center middle;
        content-align: center middle;
    }

    #night_title {
        width: 100%;
        text-align: center;
        text-style: bold;
        color: $warning;
    }

    #night_instructions {
        width: 100%;
        text-align: center;
        color: $text-muted;
    }

    #button_container {
        width: 100%;
        height: auto;
        align: center middle;
        margin-top: 1;
    }

    .action_button {
        margin: 0 1;
    }

    #status_text {
        width: 100%;
        text-align: center;
        color: $warning;
        margin-top: 1;
    }
    """

    BINDINGS = [
        Binding("escape", "app.quit", "Quit"),
    ]

    def __init__(
        self,
        day_number: int,
        is_human_alive: bool,
        human_role: str,
        survivors: list,
        players: List[dict] = None,
        human_index: int = 0
    ):
        super().__init__()
        self.day_number = day_number
        self.is_human_alive = is_human_alive
        self.human_role = human_role
        self.survivors = survivors
        self.players = players or []
        self.human_index = human_index
        self.can_proceed = False
        self.selected_target: Optional[int] = None
        self.action_submitted = False
        self.dismiss_event = asyncio.Event()
        self.human_player_index = human_index

    def _get_role_icon(self) -> str:
        """역할에 따른 아이콘 반환"""
        if self.human_role == "mafia":
            return "🔪"
        elif self.human_role == "doctor":
            return "💉"
        elif self.human_role == "police":
            return "🔍"
        return "😴"

    def _get_role_action(self) -> str:
        """역할에 따른 행동 설명 반환"""
        if self.human_role == "mafia":
            return "위의 플레이어 카드를 클릭하여 살해 대상을 선택하세요"
        elif self.human_role == "doctor":
            return "위의 플레이어 카드를 클릭하여 보호할 대상을 선택하세요"
        elif self.human_role == "police":
            return "위의 플레이어 카드를 클릭하여 조사할 대상을 선택하세요"
        return "당신은 자고 있습니다..."

    def _should_exclude_self(self) -> bool:
        """자기 자신을 타겟에서 제외할지 결정"""
        # 마피아/경찰은 자기 자신 타겟 불가, 의사는 자신 보호 가능
        return self.human_role in ["mafia", "police"]

    def compose(self) -> ComposeResult:
        yield Header()
        yield Footer()

        # 클릭 가능한 플레이어 상태바
        can_select = self.is_human_alive and self.human_role in ["mafia", "doctor", "police"]

        if self.players:
            yield PlayerStatusBar(
                players=self.players,
                human_index=self.human_index,
                human_role=self.human_role,
                show_human_role=True,
                title=f"🌙 Night {self.day_number}",
                selectable=can_select,
                exclude_self=self._should_exclude_self(),
                id="player_bar"
            )

        with Container(id="night_container"):
            with Vertical(id="night_content"):
                icon = self._get_role_icon()
                role_names = {
                    "mafia": "마피아",
                    "doctor": "의사",
                    "police": "경찰",
                    "citizen": "시민"
                }
                role_display = role_names.get(self.human_role, "시민") if self.human_role else "시민"
                yield Label(f"{icon} {role_display} {icon}", id="night_title")

                if self.is_human_alive and self.human_role in ["mafia", "doctor", "police"]:
                    yield Label(self._get_role_action(), id="night_instructions")
                    with Horizontal(id="button_container"):
                        yield Button("확인", id="submit_btn", variant="primary", classes="action_button")
                        if self.human_role == "doctor":
                            yield Button("건너뛰기", id="skip_btn", variant="default", classes="action_button")
                    yield Label("", id="status_text")
                else:
                    if not self.is_human_alive:
                        yield Label("💀 사망하여 관전 중", id="night_instructions")
                    else:
                        yield Label("⏳ 기다리는 중...", id="night_instructions")

    async def on_mount(self) -> None:
        """Initialize night screen"""
        if not (self.is_human_alive and self.human_role in ["mafia", "doctor", "police"]):
            self.action_submitted = True

    def on_player_card_selected(self, event: PlayerCard.Selected) -> None:
        """Handle player card click"""
        if self.action_submitted:
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
                self.action_submitted = True
                self.add_message("⏳ 다른 플레이어를 기다리는 중...", "yellow")

                # Disable buttons and player selection
                self.query_one("#submit_btn", Button).disabled = True
                try:
                    self.query_one("#skip_btn", Button).disabled = True
                except:
                    pass
                try:
                    player_bar = self.query_one("#player_bar", PlayerStatusBar)
                    player_bar.disable_all()
                except:
                    pass
            else:
                self.add_message("⚠️ 먼저 플레이어 카드를 클릭하세요", "yellow")

        elif event.button.id == "skip_btn":
            self.selected_target = -1  # Skip action
            self.action_submitted = True
            self.add_message("⏳ 다른 플레이어를 기다리는 중...", "yellow")

            # Disable buttons
            self.query_one("#submit_btn", Button).disabled = True
            self.query_one("#skip_btn", Button).disabled = True
            try:
                player_bar = self.query_one("#player_bar", PlayerStatusBar)
                player_bar.disable_all()
            except:
                pass

    def add_message(self, message: str, style: str = "white"):
        """Update status text"""
        try:
            status = self.query_one("#status_text", Label)
            status.update(message)
        except Exception:
            pass
