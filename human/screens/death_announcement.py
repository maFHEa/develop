"""
Death Announcement Screen - 사망자 발표 페이즈
"""
from textual.app import ComposeResult
from textual.widgets import Header, Footer, Static
from textual.containers import Container, Vertical, Center
from textual.binding import Binding
from textual.screen import Screen
from typing import List, Optional
import asyncio

from .components import PlayerStatusBar


class VictimCard(Static):
    """사망자 카드 - 드라마틱한 연출"""

    DEFAULT_CSS = """
    VictimCard {
        width: 45;
        height: 5;
        background: $surface-darken-2;
        border: heavy $error;
        text-align: center;
        margin: 0 1;
        padding: 1;
    }

    VictimCard.fade-in {
        opacity: 0;
    }

    VictimCard.visible {
        opacity: 1;
    }
    """

    def __init__(self, player_index: int, player_name: str, cause: str = "killed", role: str = None, **kwargs):
        super().__init__(**kwargs)
        self.player_index = player_index
        self.player_name = player_name
        self.cause = cause  # "killed" (야간) or "voted_out" (투표)
        self.role = role  # 공개된 역할

    def on_mount(self) -> None:
        if self.cause == "killed":
            icon = "🔪"
            title = "살해됨"
        else:  # voted_out
            icon = "🗳️"
            title = "처형됨"

        # 역할 표시
        role_display = ""
        if self.role:
            role_icon = {"mafia": "🔪", "doctor": "💉", "police": "🔍", "citizen": "👤"}.get(self.role, "❓")
            role_name = {"mafia": "마피아", "doctor": "의사", "police": "경찰", "citizen": "시민"}.get(self.role, self.role)
            role_display = f" | {role_icon} {role_name}"

        content = f"{icon} {title} {icon}\n💀 P{self.player_index} {self.player_name}{role_display}"
        self.update(content)


class DeathAnnouncementScreen(Screen):
    """사망자 발표 스크린"""

    CSS = """
    DeathAnnouncementScreen {
        background: $surface;
    }

    #player_bar {
        dock: top;
    }

    #announcement_container {
        width: 100%;
        height: 100%;
        align: center middle;
        padding: 1;
    }

    #main_panel {
        width: 60;
        height: auto;
        max-height: 80%;
        background: $surface-darken-1;
        border: double $primary;
        padding: 2;
        align: center middle;
    }

    .phase_title {
        width: 100%;
        text-align: center;
        text-style: bold;
        color: $warning;
        margin-bottom: 1;
    }

    .subtitle {
        width: 100%;
        text-align: center;
        color: $text-muted;
        margin-bottom: 1;
    }

    #victim_container {
        width: 100%;
        height: auto;
        align: center middle;
        margin: 1 0;
    }

    .no_death {
        width: 100%;
        text-align: center;
        color: $success;
        text-style: bold;
        padding: 1;
    }

    #continue_hint {
        width: 100%;
        text-align: center;
        color: $text-muted;
        margin-top: 1;
    }

    .phase_title.sunrise {
        color: $warning;
    }

    .phase_title.moonset {
        color: $primary;
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
        victims: List[int],  # 사망자 인덱스 리스트
        players: List[dict],  # 전체 플레이어 정보
        human_index: int = 0,
        human_role: str = "citizen",
        auto_continue_seconds: int = 5,  # 자동 진행 시간
        victim_roles: dict = None,  # {player_index: role} 사망자 역할 정보
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

    def compose(self) -> ComposeResult:
        yield Header()
        yield Footer()

        # 상단 플레이어 상태바 (사망자 반영된 상태)
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
            with Vertical(id="main_panel"):
                # 페이즈 타이틀
                if self.phase_type == "night":
                    yield Static("🌅 밤이 끝났습니다", classes="phase_title sunrise")
                    yield Static("마을이 깨어나 확인한 것은...", classes="subtitle")
                else:
                    yield Static("⚖️ 투표가 종료되었습니다", classes="phase_title")
                    yield Static("마을의 결정은...", classes="subtitle")

                # 사망자 표시
                with Center(id="victim_container"):
                    if self.victims:
                        for victim_idx in self.victims:
                            player_info = next(
                                (p for p in self.players if p["index"] == victim_idx),
                                {"index": victim_idx, "name": f"Player {victim_idx}"}
                            )
                            cause = "killed" if self.phase_type == "night" else "voted_out"
                            victim_role = self.victim_roles.get(victim_idx)
                            yield VictimCard(
                                player_index=victim_idx,
                                player_name=player_info["name"],
                                cause=cause,
                                role=victim_role,
                                id=f"victim_{victim_idx}"
                            )
                    else:
                        if self.phase_type == "night":
                            yield Static("✨ 오늘 밤 희생자가 없습니다! ✨", classes="no_death")
                        else:
                            yield Static("🤝 처형된 사람이 없습니다.", classes="no_death")

                yield Static("[Enter] 또는 [Space]를 눌러 계속...", id="continue_hint")

    async def on_mount(self) -> None:
        """마운트 시 자동 진행 타이머 시작"""
        # 드라마틱 효과: 순차적으로 사망자 표시
        await self._dramatic_reveal()

        # 자동 진행 타이머
        asyncio.create_task(self._auto_continue_timer())

    async def _dramatic_reveal(self) -> None:
        """사망자를 드라마틱하게 순차 공개"""
        await asyncio.sleep(0.5)  # 초기 딜레이

        for victim_idx in self.victims:
            try:
                victim_card = self.query_one(f"#victim_{victim_idx}", VictimCard)
                victim_card.add_class("visible")
                await asyncio.sleep(0.8)  # 각 사망자 사이 딜레이
            except Exception:
                pass

    async def _auto_continue_timer(self) -> None:
        """자동 진행 타이머"""
        try:
            hint = self.query_one("#continue_hint", Static)

            for remaining in range(self.auto_continue_seconds, 0, -1):
                if self.should_continue:
                    return
                hint.update(f"{remaining}초 후 자동 진행... (Enter로 건너뛰기)")
                await asyncio.sleep(1)

            if not self.should_continue:
                self.action_continue()
        except Exception:
            pass

    def action_continue(self) -> None:
        """계속 진행"""
        self.should_continue = True
        self.continue_event.set()
        # Note: dismiss()를 호출하지 않음 - app.py에서 pop_screen()으로 처리


class PoliceInvestigationCard(Static):
    """경찰 조사 결과 카드"""

    DEFAULT_CSS = """
    PoliceInvestigationCard {
        width: 45;
        height: auto;
        background: $primary 10%;
        border: heavy $primary;
        content-align: center middle;
        margin: 0 1 1 1;
        padding: 1;
    }

    PoliceInvestigationCard.mafia {
        background: $error 15%;
        border: heavy $error;
    }

    PoliceInvestigationCard.not-mafia {
        background: $success 15%;
        border: heavy $success;
    }
    """

    def __init__(self, target_index: int, target_name: str, is_mafia: bool, **kwargs):
        super().__init__(**kwargs)
        self.target_index = target_index
        self.target_name = target_name
        self.is_mafia = is_mafia

    def on_mount(self) -> None:
        if self.is_mafia:
            self.add_class("mafia")
            result_text = "🔪 마피아!"
        else:
            self.add_class("not-mafia")
            result_text = "✅ 마피아 아님"

        content = f"🔍 조사결과: P{self.target_index} {self.target_name}\n{result_text}"
        self.update(content)


class NightResultScreen(DeathAnnouncementScreen):
    """야간 결과 발표 스크린 (별칭)"""

    def __init__(
        self,
        day_number: int,
        killed_players: List[int],
        players: List[dict],
        human_index: int = 0,
        human_role: str = "citizen",
        victim_roles: dict = None,
        investigation_result: dict = None,  # {"target": int, "is_mafia": bool}
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
            with Vertical(id="main_panel"):
                yield Static("🌅 밤이 끝났습니다", classes="phase_title sunrise")

                # 경찰 조사 결과 표시 (human이 경찰이고 조사했을 경우)
                if self.investigation_result and self.human_role == "police":
                    target_idx = self.investigation_result.get("target")
                    is_mafia = self.investigation_result.get("is_mafia", False)
                    target_info = next(
                        (p for p in self.players if p["index"] == target_idx),
                        {"index": target_idx, "name": f"P{target_idx}"}
                    )
                    with Center():
                        yield PoliceInvestigationCard(
                            target_index=target_idx,
                            target_name=target_info["name"],
                            is_mafia=is_mafia,
                            id="investigation_result"
                        )

                yield Static("마을이 깨어나 확인한 것은...", classes="subtitle")

                # 사망자 표시
                with Center(id="victim_container"):
                    if self.victims:
                        for victim_idx in self.victims:
                            player_info = next(
                                (p for p in self.players if p["index"] == victim_idx),
                                {"index": victim_idx, "name": f"P{victim_idx}"}
                            )
                            victim_role = self.victim_roles.get(victim_idx)
                            yield VictimCard(
                                player_index=victim_idx,
                                player_name=player_info["name"],
                                cause="killed",
                                role=victim_role,
                                id=f"victim_{victim_idx}"
                            )
                    else:
                        yield Static("✨ 오늘 밤 희생자가 없습니다! ✨", classes="no_death")

                yield Static("[Enter] 또는 [Space]를 눌러 계속...", id="continue_hint")


class VoteResultsPanel(Static):
    """투표 결과 패널"""

    DEFAULT_CSS = """
    VoteResultsPanel {
        width: 45;
        height: auto;
        padding: 1;
        margin: 0 1 1 1;
        background: $surface-darken-2;
        border: heavy $accent;
        text-align: center;
    }
    """

    def __init__(self, vote_counts: List[int], players: List[dict], **kwargs):
        super().__init__(**kwargs)
        self.vote_counts = vote_counts
        self.players = players

    def on_mount(self) -> None:
        lines = []

        # 득표수 기준 정렬
        sorted_results = sorted(
            enumerate(self.vote_counts),
            key=lambda x: x[1],
            reverse=True
        )

        max_votes = max(self.vote_counts) if self.vote_counts else 0

        for player_idx, votes in sorted_results:
            if votes == 0:
                continue

            player_info = next(
                (p for p in self.players if p["index"] == player_idx),
                {"name": f"Player {player_idx}", "alive": True}
            )

            # 막대 그래프
            bar_length = int((votes / max(max_votes, 1)) * 20)
            bar = "█" * bar_length + "░" * (20 - bar_length)

            # 최다 득표자 표시
            marker = "👉 " if votes == max_votes else "   "

            lines.append(f"{marker}P{player_idx} {player_info['name'][:8]:8s} [{bar}] {votes}표")

        if not lines:
            lines.append("   (투표가 없습니다)")

        self.update("\n".join(lines))


class VoteResultScreen(DeathAnnouncementScreen):
    """투표 결과 발표 스크린 (별칭)"""

    def __init__(
        self,
        day_number: int,
        voted_out_player: Optional[int],
        players: List[dict],
        vote_counts: Optional[List[int]] = None,  # 각 플레이어별 득표수
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
            with Vertical(id="main_panel"):
                yield Static("⚖️ 투표가 종료되었습니다", classes="phase_title")

                # 투표 결과 표시 (있는 경우)
                if self.vote_counts:
                    with Center():
                        yield VoteResultsPanel(
                            vote_counts=self.vote_counts,
                            players=self.players,
                            id="vote_results"
                        )

                yield Static("마을의 결정은...", classes="subtitle")

                # 사망자 표시
                with Center(id="victim_container"):
                    if self.victims:
                        for victim_idx in self.victims:
                            player_info = next(
                                (p for p in self.players if p["index"] == victim_idx),
                                {"index": victim_idx, "name": f"P{victim_idx}"}
                            )
                            victim_role = self.victim_roles.get(victim_idx)
                            yield VictimCard(
                                player_index=victim_idx,
                                player_name=player_info["name"],
                                cause="voted_out",
                                role=victim_role,
                                id=f"victim_{victim_idx}"
                            )
                    else:
                        yield Static("🤝 처형된 사람이 없습니다.", classes="no_death")

                yield Static("[Enter] 또는 [Space]를 눌러 계속...", id="continue_hint")
