"""
Role Reveal Screen - 게임 시작 시 역할 고지
"""
from textual.app import ComposeResult
from textual.widgets import Header, Footer, Static
from textual.containers import Container, Vertical
from textual.binding import Binding
from textual.screen import Screen
from typing import List
import asyncio

from .components import PlayerStatusBar


class RoleRevealScreen(Screen):
    """역할 고지 스크린"""

    CSS = """
    RoleRevealScreen {
        background: $surface;
    }

    #player_bar {
        dock: top;
    }

    #reveal_container {
        width: 100%;
        height: 1fr;
        align: center middle;
    }

    #reveal_content {
        width: 100%;
        height: auto;
        align: center middle;
        content-align: center middle;
    }

    .reveal_title {
        width: 100%;
        text-align: center;
        text-style: bold;
        color: $warning;
        margin-bottom: 2;
    }

    .role_icon {
        width: 100%;
        text-align: center;
        margin: 1 0;
    }

    .role_name {
        width: 100%;
        text-align: center;
        text-style: bold;
        margin: 1 0;
    }

    .role_description {
        width: 100%;
        text-align: center;
        color: $text-muted;
        margin: 1 0;
    }

    .role_mafia {
        color: $error;
    }

    .role_doctor {
        color: $success;
    }

    .role_police {
        color: $primary;
    }

    .role_citizen {
        color: $text;
    }

    #continue_hint {
        width: 100%;
        text-align: center;
        color: $text-muted;
        margin-top: 3;
    }
    """

    BINDINGS = [
        Binding("enter", "continue", "Continue"),
        Binding("space", "continue", "Continue"),
        Binding("escape", "app.quit", "Quit"),
    ]

    ROLE_INFO = {
        "mafia": {
            "icon": "🔪",
            "name": "마피아",
            "description": "밤에 시민을 살해하세요. 정체를 숨기고 살아남으세요.",
            "class": "role_mafia"
        },
        "doctor": {
            "icon": "💉",
            "name": "의사",
            "description": "밤에 한 명을 치료하여 마피아의 공격으로부터 보호하세요.",
            "class": "role_doctor"
        },
        "police": {
            "icon": "🔍",
            "name": "경찰",
            "description": "밤에 한 명을 조사하여 마피아인지 확인하세요.",
            "class": "role_police"
        },
        "citizen": {
            "icon": "👤",
            "name": "시민",
            "description": "토론과 투표로 마피아를 찾아 처형하세요.",
            "class": "role_citizen"
        }
    }

    def __init__(
        self,
        role: str,
        players: List[dict],
        human_index: int = 0,
        auto_continue_seconds: int = 5,
        **kwargs
    ):
        super().__init__(**kwargs)
        self.role = role.lower()
        self.players = players
        self.human_index = human_index
        self.auto_continue_seconds = auto_continue_seconds
        self.should_continue = False
        self.continue_event = asyncio.Event()

    def compose(self) -> ComposeResult:
        yield Header()
        yield Footer()

        yield PlayerStatusBar(
            players=self.players,
            human_index=self.human_index,
            human_role=self.role,
            show_human_role=True,
            title="🎭 역할 배정",
            id="player_bar"
        )

        role_info = self.ROLE_INFO.get(self.role, self.ROLE_INFO["citizen"])

        with Container(id="reveal_container"):
            with Vertical(id="reveal_content"):
                yield Static("당신의 역할은...", classes="reveal_title")
                yield Static(role_info["icon"], classes=f"role_icon {role_info['class']}")
                yield Static(role_info["name"], classes=f"role_name {role_info['class']}")
                yield Static(role_info["description"], classes="role_description")
                yield Static("[Enter] 게임 시작...", id="continue_hint")

    async def on_mount(self) -> None:
        asyncio.create_task(self._auto_continue_timer())

    async def _auto_continue_timer(self) -> None:
        try:
            hint = self.query_one("#continue_hint", Static)

            for remaining in range(self.auto_continue_seconds, 0, -1):
                if self.should_continue:
                    return
                hint.update(f"{remaining}초 후 게임 시작...")
                await asyncio.sleep(1)

            if not self.should_continue:
                self.action_continue()
        except Exception:
            pass

    def action_continue(self) -> None:
        self.should_continue = True
        self.continue_event.set()
