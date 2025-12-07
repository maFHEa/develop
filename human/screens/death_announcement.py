"""
Death Announcement Screen - 사망자 발표 페이즈 (간소화 버전)
"""
from textual.app import ComposeResult
from textual.widgets import Header, Footer, Static
from textual.containers import Container, Vertical, Center
from textual.binding import Binding
from textual.screen import Screen
from typing import List, Optional
import asyncio

from .components import PlayerStatusBar


class DeathAnnouncementScreen(Screen):
    """사망자 발표 스크린 (간소화)"""

    CSS = """
    DeathAnnouncementScreen {
        background: $surface;
    }

    #player_bar {
        dock: top;
    }

    #announcement_container {
        width: 100%;
        height: 1fr;
        align: center middle;
    }

    #main_content {
        width: 100%;
        height: auto;
        align: center middle;
        content-align: center middle;
    }

    .phase_title {
        width: 100%;
        text-align: center;
        text-style: bold;
        color: $warning;
        margin-bottom: 1;
    }

    .result_text {
        width: 100%;
        text-align: center;
        margin: 1 0;
    }

    .victim_text {
        width: 100%;
        text-align: center;
        color: $error;
        text-style: bold;
    }

    .no_death {
        width: 100%;
        text-align: center;
        color: $success;
        text-style: bold;
    }

    .investigation_text {
        width: 100%;
        text-align: center;
        margin: 1 0;
    }

    .investigation_mafia {
        color: $error;
        text-style: bold;
    }

    .investigation_safe {
        color: $success;
        text-style: bold;
    }

    #continue_hint {
        width: 100%;
        text-align: center;
        color: $text-muted;
        margin-top: 2;
    }

    .vote_result_line {
        width: 100%;
        text-align: center;
    }
    """

    BINDINGS = [
        Binding("enter", "continue", "Continue"),
        Binding("space", "continue", "Continue"),
        Binding("escape", "app.quit", "Quit"),
    ]

    def __init__(
        self,
        phase_type: str,  # "night" or "vote"
        day_number: int,
        victims: List[int],
        players: List[dict],
        human_index: int = 0,
        human_role: str = "citizen",
        auto_continue_seconds: int = 5,
        victim_roles: dict = None,
        **kwargs
    ):
        super().__init__(**kwargs)
        self.phase_type = phase_type
        self.day_number = day_number
        self.victims = victims
        self.players = players
        self.human_index = human_index
        self.human_role = human_role
        self.auto_continue_seconds = auto_continue_seconds
        self.victim_roles = victim_roles or {}
        self.should_continue = False
        self.continue_event = asyncio.Event()

    def _get_player_name(self, idx: int) -> str:
        player_info = next(
            (p for p in self.players if p["index"] == idx),
            {"index": idx, "name": f"P{idx}"}
        )
        return player_info["name"]

    def _get_role_text(self, role: str) -> str:
        if not role:
            return ""
        role_map = {
            "mafia": "마피아",
            "doctor": "의사",
            "police": "경찰",
            "citizen": "시민"
        }
        return role_map.get(role, role)

    def compose(self) -> ComposeResult:
        yield Header()
        yield Footer()

        if self.phase_type == "night":
            title = f"🌅 Dawn of Day {self.day_number}"
        else:
            title = f"⚖️ Day {self.day_number} - Judgement"

        yield PlayerStatusBar(
            players=self.players,
            human_index=self.human_index,
            human_role=self.human_role,
            show_human_role=True,
            title=title,
            id="player_bar"
        )

        with Container(id="announcement_container"):
            with Vertical(id="main_content"):
                if self.phase_type == "night":
                    yield Static("🌅 밤이 끝났습니다", classes="phase_title")
                else:
                    yield Static("⚖️ 투표 종료", classes="phase_title")

                # 사망자 표시
                if self.victims:
                    for victim_idx in self.victims:
                        name = self._get_player_name(victim_idx)
                        role = self.victim_roles.get(victim_idx)
                        role_text = f" ({self._get_role_text(role)})" if role else ""

                        if self.phase_type == "night":
                            yield Static(f"💀 {name}{role_text} 살해됨", classes="victim_text")
                        else:
                            yield Static(f"💀 {name}{role_text} 처형됨", classes="victim_text")
                else:
                    if self.phase_type == "night":
                        yield Static("✨ 희생자 없음", classes="no_death")
                    else:
                        yield Static("🤝 처형된 사람 없음", classes="no_death")

                yield Static("[Enter] 계속...", id="continue_hint")

    async def on_mount(self) -> None:
        asyncio.create_task(self._auto_continue_timer())

    async def _auto_continue_timer(self) -> None:
        try:
            hint = self.query_one("#continue_hint", Static)

            for remaining in range(self.auto_continue_seconds, 0, -1):
                if self.should_continue:
                    return
                hint.update(f"{remaining}초 후 자동 진행...")
                await asyncio.sleep(1)

            if not self.should_continue:
                self.action_continue()
        except Exception:
            pass

    def action_continue(self) -> None:
        self.should_continue = True
        self.continue_event.set()


class NightResultScreen(DeathAnnouncementScreen):
    """야간 결과 발표 스크린"""

    def __init__(
        self,
        day_number: int,
        killed_players: List[int],
        players: List[dict],
        human_index: int = 0,
        human_role: str = "citizen",
        victim_roles: dict = None,
        investigation_result: dict = None,
        **kwargs
    ):
        super().__init__(
            phase_type="night",
            day_number=day_number,
            victims=killed_players,
            players=players,
            human_index=human_index,
            human_role=human_role,
            victim_roles=victim_roles,
            **kwargs
        )
        self.investigation_result = investigation_result

    def compose(self) -> ComposeResult:
        yield Header()
        yield Footer()

        title = f"🌅 Dawn of Day {self.day_number}"

        yield PlayerStatusBar(
            players=self.players,
            human_index=self.human_index,
            human_role=self.human_role,
            show_human_role=True,
            title=title,
            id="player_bar"
        )

        with Container(id="announcement_container"):
            with Vertical(id="main_content"):
                yield Static("🌅 밤이 끝났습니다", classes="phase_title")

                # 경찰 조사 결과 (human이 경찰인 경우)
                if self.investigation_result and self.human_role == "police":
                    target_idx = self.investigation_result.get("target")
                    is_mafia = self.investigation_result.get("is_mafia", False)
                    target_name = self._get_player_name(target_idx)

                    if is_mafia:
                        yield Static(
                            f"🔍 조사결과: P{target_idx} {target_name} = 🔪 마피아!",
                            classes="investigation_text investigation_mafia"
                        )
                    else:
                        yield Static(
                            f"🔍 조사결과: P{target_idx} {target_name} = ✅ 마피아 아님",
                            classes="investigation_text investigation_safe"
                        )

                # 사망자 표시
                if self.victims:
                    for victim_idx in self.victims:
                        name = self._get_player_name(victim_idx)
                        role = self.victim_roles.get(victim_idx)
                        role_text = f" ({self._get_role_text(role)})" if role else ""
                        yield Static(f"💀 {name}{role_text} 살해됨", classes="victim_text")
                else:
                    yield Static("✨ 희생자 없음", classes="no_death")

                yield Static("[Enter] 계속...", id="continue_hint")


class VoteResultScreen(DeathAnnouncementScreen):
    """투표 결과 발표 스크린"""

    def __init__(
        self,
        day_number: int,
        voted_out_player: Optional[int],
        players: List[dict],
        vote_counts: Optional[List[int]] = None,
        human_index: int = 0,
        human_role: str = "citizen",
        victim_roles: dict = None,
        **kwargs
    ):
        victims = [voted_out_player] if voted_out_player is not None else []
        super().__init__(
            phase_type="vote",
            day_number=day_number,
            victims=victims,
            players=players,
            human_index=human_index,
            human_role=human_role,
            victim_roles=victim_roles,
            **kwargs
        )
        self.vote_counts = vote_counts

    def compose(self) -> ComposeResult:
        yield Header()
        yield Footer()

        title = f"⚖️ Day {self.day_number} - Judgement"

        yield PlayerStatusBar(
            players=self.players,
            human_index=self.human_index,
            human_role=self.human_role,
            show_human_role=True,
            title=title,
            id="player_bar"
        )

        with Container(id="announcement_container"):
            with Vertical(id="main_content"):
                yield Static("⚖️ 투표 종료", classes="phase_title")

                # 처형자 표시
                if self.victims:
                    for victim_idx in self.victims:
                        name = self._get_player_name(victim_idx)
                        role = self.victim_roles.get(victim_idx)
                        role_text = f" ({self._get_role_text(role)})" if role else ""
                        yield Static(f"💀 {name}{role_text} 처형됨", classes="victim_text")
                else:
                    yield Static("🤝 처형된 사람 없음", classes="no_death")

                yield Static("[Enter] 계속...", id="continue_hint")
