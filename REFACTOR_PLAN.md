# TUI 리팩토링 계획: 상단 플레이어 상태바

## 목표
모든 화면(Night, Vote, Chat) 상단에 플레이어 N명을 가로로 배열하여 게임 상태를 한눈에 파악할 수 있도록 개선

## 새로 추가할 파일

### `screens/components.py` - 공통 UI 컴포넌트

```python
"""
Shared UI Components for Mafia Game TUI
"""
from textual.app import ComposeResult
from textual.widget import Widget
from textual.widgets import Static
from textual.containers import Horizontal
from rich.text import Text
from typing import List, Optional


class PlayerCard(Static):
    """Single player card widget"""

    DEFAULT_CSS = """
    PlayerCard {
        width: auto;
        height: 5;
        min-width: 12;
        padding: 0 1;
        margin: 0 1;
        border: solid $primary;
        content-align: center middle;
    }

    PlayerCard.alive {
        border: solid $success;
        background: $surface;
    }

    PlayerCard.dead {
        border: solid $error;
        background: $surface-darken-2;
        color: $text-muted;
    }

    PlayerCard.human {
        border: double $warning;
    }

    PlayerCard.selected {
        border: solid $warning;
        background: $warning 20%;
    }
    """

    def __init__(
        self,
        player_index: int,
        player_name: str,
        is_alive: bool = True,
        is_human: bool = False,
        role: Optional[str] = None,
        show_role: bool = False,
        **kwargs
    ):
        super().__init__(**kwargs)
        self.player_index = player_index
        self.player_name = player_name
        self.is_alive = is_alive
        self.is_human = is_human
        self.role = role
        self.show_role = show_role
        self._update_classes()

    def _update_classes(self):
        """Update CSS classes based on state"""
        self.remove_class("alive", "dead", "human")
        if self.is_alive:
            self.add_class("alive")
        else:
            self.add_class("dead")
        if self.is_human:
            self.add_class("human")

    def compose(self) -> ComposeResult:
        return []

    def on_mount(self) -> None:
        self._render_card()

    def _render_card(self) -> None:
        """Render the card content"""
        lines = []

        # Status icon
        if self.is_alive:
            status = "🟢"
        else:
            status = "💀"

        # Player info
        if self.is_human:
            name_line = f"{status} P{self.player_index} (You)"
        else:
            name_line = f"{status} P{self.player_index}"

        lines.append(name_line)
        lines.append(self.player_name[:10])

        # Role (if shown)
        if self.show_role and self.role:
            role_icons = {
                "mafia": "🔪",
                "doctor": "💉",
                "police": "🔍",
                "citizen": "👤"
            }
            icon = role_icons.get(self.role.lower(), "❓")
            lines.append(f"{icon} {self.role.upper()}")

        self.update("\n".join(lines))

    def set_selected(self, selected: bool) -> None:
        """Set selection state"""
        if selected:
            self.add_class("selected")
        else:
            self.remove_class("selected")

    def set_alive(self, alive: bool) -> None:
        """Update alive status"""
        self.is_alive = alive
        self._update_classes()
        self._render_card()


class PlayerStatusBar(Widget):
    """Horizontal bar showing all players' status"""

    DEFAULT_CSS = """
    PlayerStatusBar {
        width: 100%;
        height: auto;
        min-height: 7;
        background: $surface-darken-1;
        padding: 1;
    }

    PlayerStatusBar > Horizontal {
        width: 100%;
        height: auto;
        align: center middle;
    }

    PlayerStatusBar .title {
        width: 100%;
        text-align: center;
        text-style: bold;
        color: $text;
        margin-bottom: 1;
    }
    """

    def __init__(
        self,
        players: List[dict],
        human_index: int = 0,
        human_role: Optional[str] = None,
        show_human_role: bool = True,
        title: Optional[str] = None,
        **kwargs
    ):
        """
        Initialize PlayerStatusBar

        Args:
            players: List of player dicts with keys: index, name, alive
            human_index: Index of human player
            human_role: Role of human player (shown only for human)
            show_human_role: Whether to show human's role
            title: Optional title above player cards
        """
        super().__init__(**kwargs)
        self.players = players
        self.human_index = human_index
        self.human_role = human_role
        self.show_human_role = show_human_role
        self.title = title
        self.player_cards: List[PlayerCard] = []

    def compose(self) -> ComposeResult:
        if self.title:
            yield Static(self.title, classes="title")

        with Horizontal():
            for p in self.players:
                is_human = p.get("index", -1) == self.human_index
                show_role = is_human and self.show_human_role
                role = self.human_role if is_human else None

                card = PlayerCard(
                    player_index=p.get("index", 0),
                    player_name=p.get("name", f"Player {p.get('index', 0)}"),
                    is_alive=p.get("alive", True),
                    is_human=is_human,
                    role=role,
                    show_role=show_role,
                    id=f"player_card_{p.get('index', 0)}"
                )
                self.player_cards.append(card)
                yield card

    def update_player(self, index: int, alive: Optional[bool] = None, selected: Optional[bool] = None) -> None:
        """Update a player's status"""
        for card in self.player_cards:
            if card.player_index == index:
                if alive is not None:
                    card.set_alive(alive)
                if selected is not None:
                    card.set_selected(selected)
                break

    def clear_selections(self) -> None:
        """Clear all selections"""
        for card in self.player_cards:
            card.set_selected(False)

    def get_player_card(self, index: int) -> Optional[PlayerCard]:
        """Get a player card by index"""
        for card in self.player_cards:
            if card.player_index == index:
                return card
        return None
```

---

## 수정할 파일들

### 1. `screens/__init__.py` 수정

```python
# 기존 import에 추가
from .components import PlayerStatusBar, PlayerCard
```

---

### 2. `screens/night.py` 수정

**변경 사항:**
- `PlayerStatusBar` 추가
- 생성자에 `players` 파라미터 추가

```python
"""
Night Phase Screen
"""
from textual.app import ComposeResult
from textual.widgets import Header, Footer, Label, RichLog, Input, Button
from textual.containers import Container, Horizontal, Vertical
from textual.binding import Binding
from textual.screen import Screen
from textual import on
from rich.text import Text
from typing import Optional, List
import asyncio

from .components import PlayerStatusBar


class NightScreen(Screen):
    """Night phase screen - shows what's happening"""

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

    def __init__(
        self,
        day_number: int,
        is_human_alive: bool,
        human_role: str,
        survivors: list,
        players: List[dict],  # 새로 추가: [{"index": 0, "name": "Player0", "alive": True}, ...]
        human_index: int = 0
    ):
        super().__init__()
        self.day_number = day_number
        self.is_human_alive = is_human_alive
        self.human_role = human_role
        self.survivors = survivors
        self.players = players
        self.human_index = human_index
        self.can_proceed = False
        self.selected_target: Optional[int] = None
        self.action_submitted = False
        self.dismiss_event = asyncio.Event()
        self.human_player_index = human_index

    def compose(self) -> ComposeResult:
        yield Header()

        # 상단 플레이어 상태바
        yield PlayerStatusBar(
            players=self.players,
            human_index=self.human_index,
            human_role=self.human_role,
            show_human_role=True,
            title=f"🌙 Night {self.day_number}",
            id="player_bar"
        )

        with Container(id="night_container"):
            yield RichLog(id="night_log", highlight=True, markup=True, auto_scroll=True)

            # Action input (only for active roles)
            if self.is_human_alive and self.human_role in ["mafia", "doctor", "police"]:
                with Horizontal(id="action_container"):
                    yield Label("Target player index:", classes="action_label")
                    yield Input(placeholder="0, 1, 2, ...", id="target_input")
                    yield Button("Submit", id="submit_action", variant="primary")

        yield Footer()

    # ... 나머지 메서드는 동일 ...
```

---

### 3. `screens/vote.py` 수정

```python
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

from .components import PlayerStatusBar


class VoteScreen(Screen):
    """Voting phase screen"""

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

    def __init__(
        self,
        day_number: int,
        is_alive: bool,
        survivors: List[int],
        player_names: List[str],
        players: List[dict],  # 새로 추가
        human_index: int = 0,
        human_role: str = "citizen"
    ):
        super().__init__()
        self.day_number = day_number
        self.is_alive = is_alive
        self.survivors = survivors
        self.player_names = player_names
        self.players = players
        self.human_index = human_index
        self.human_role = human_role
        self.selected_target: Optional[int] = None
        self.vote_submitted = False
        self.dismiss_event = asyncio.Event()

    def compose(self) -> ComposeResult:
        yield Header()

        # 상단 플레이어 상태바
        yield PlayerStatusBar(
            players=self.players,
            human_index=self.human_index,
            human_role=self.human_role,
            show_human_role=True,
            title=f"🗳️ Day {self.day_number} - Vote",
            id="player_bar"
        )

        # Main vote panel
        with Container(id="vote_container"):
            with Vertical(id="vote_panel"):
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

    # ... 나머지 메서드는 동일 ...
```

---

### 4. `screens/chat.py` 수정

```python
"""
Chat Screen for Discussion Phase
"""
from textual.app import ComposeResult
from textual.widgets import Header, Footer, Label, RichLog, Input
from textual.containers import Container, Horizontal
from textual.binding import Binding
from textual.screen import Screen
from rich.text import Text
from typing import Optional, List
import asyncio
import httpx

from .components import PlayerStatusBar


class ChatScreen(Screen):
    """Chat discussion phase screen"""

    CSS = """
    ChatScreen {
        background: $surface;
    }

    #player_bar {
        dock: top;
    }

    #chat_display {
        height: 1fr;
        background: $surface-darken-1;
        margin: 1;
    }

    #input_container {
        dock: bottom;
        height: 3;
        background: $surface;
        padding: 0 1;
    }

    #chat_input {
        width: 1fr;
    }
    """

    BINDINGS = [
        Binding("ctrl+d", "proceed", "Proceed to Voting"),
        Binding("escape", "app.quit", "Quit"),
    ]

    def __init__(self, game_engine, duration_seconds=120):
        super().__init__()
        self.game_engine = game_engine
        self.should_proceed = False
        self.message_check_task: Optional[asyncio.Task] = None
        self.duration_seconds = duration_seconds
        self.start_time: Optional[float] = None

    def _get_players_data(self) -> List[dict]:
        """game_engine에서 플레이어 데이터 추출"""
        return [
            {
                "index": p.index,
                "name": p.name,
                "alive": p.alive
            }
            for p in self.game_engine.players
        ]

    def compose(self) -> ComposeResult:
        yield Header()

        # 상단 플레이어 상태바
        yield PlayerStatusBar(
            players=self._get_players_data(),
            human_index=self.game_engine.human_player_index,
            human_role=self.game_engine.human_role,
            show_human_role=True,
            title=f"💬 Day {self.game_engine.game_phases.day_number} - Discussion",
            id="player_bar"
        )

        # Chat display
        yield RichLog(id="chat_display", highlight=True, markup=True, auto_scroll=True)

        # Input
        with Horizontal(id="input_container"):
            yield Input(placeholder="Type your message... (Ctrl+D to proceed)", id="chat_input")

        yield Footer()

    # ... 나머지 메서드는 동일 ...
```

---

### 5. `app.py` 수정 - 스크린 생성 시 players 전달

```python
# _run_game() 메서드 내에서 스크린 생성 시 players 데이터 전달

def _get_players_data(self):
    """플레이어 데이터를 dict 리스트로 변환"""
    return [
        {
            "index": p.index,
            "name": p.name,
            "alive": p.alive
        }
        for p in self.game_engine.players
    ]

# NightScreen 생성 시:
night_screen = NightScreen(
    self.game_engine.game_phases.day_number,
    human_player.alive,
    self.game_engine.human_role,
    survivors,
    players=self._get_players_data(),  # 추가
    human_index=self.game_engine.human_player_index  # 추가
)

# VoteScreen 생성 시:
vote_screen = VoteScreen(
    self.game_engine.game_phases.day_number,
    human_player.alive,
    survivors,
    player_names,
    players=self._get_players_data(),  # 추가
    human_index=self.game_engine.human_player_index,  # 추가
    human_role=self.game_engine.human_role  # 추가
)
```

---

## 예상 결과물 (TUI 미리보기)

```
┌──────────────────────────────────────────────────────────────────────────┐
│                        🌙 Night 1                                         │
├──────────────────────────────────────────────────────────────────────────┤
│  ╔════════════╗  ╔════════════╗  ╔════════════╗  ╔════════════╗          │
│  ║ 🟢 P0 (You)║  ║ 🟢 P1      ║  ║ 🟢 P2      ║  ║ 💀 P3      ║          │
│  ║ Human      ║  ║ Bot1       ║  ║ Bot2       ║  ║ Bot3       ║          │
│  ║ 🔪 MAFIA   ║  ╚════════════╝  ╚════════════╝  ╚════════════╝          │
│  ╚════════════╝                                                           │
├──────────────────────────────────────────────────────────────────────────┤
│ ════════════════════════════════════════════════════════════              │
│ NIGHT 1                                                                   │
│ ════════════════════════════════════════════════════════════              │
│                                                                           │
│ 🔪 You are MAFIA - choose your target to kill                             │
│                                                                           │
│ Enter the player index and click Submit                                   │
│                                                                           │
├──────────────────────────────────────────────────────────────────────────┤
│ Target player index: [________] [Submit]                                  │
└──────────────────────────────────────────────────────────────────────────┘
```

---

## 적용 순서

1. `screens/components.py` 생성
2. `screens/__init__.py` 수정 (import 추가)
3. `screens/night.py` 수정
4. `screens/vote.py` 수정
5. `screens/chat.py` 수정
6. `app.py` 수정 (스크린 생성자 호출부)

---

---

## 새로 추가할 스크린: `screens/death_announcement.py`

사망자 발표를 드라마틱하게 보여주는 전용 스크린

```python
"""
Death Announcement Screen - 사망자 발표 페이즈
"""
from textual.app import ComposeResult
from textual.widgets import Header, Footer, Static
from textual.containers import Container, Vertical, Center
from textual.binding import Binding
from textual.screen import Screen
from rich.text import Text
from rich.panel import Panel
from rich.align import Align
from typing import List, Optional
import asyncio

from .components import PlayerStatusBar


class VictimCard(Static):
    """사망자 카드 - 드라마틱한 연출"""

    DEFAULT_CSS = """
    VictimCard {
        width: 40;
        height: 12;
        background: $error 10%;
        border: heavy $error;
        content-align: center middle;
        margin: 1;
    }

    VictimCard.fade-in {
        opacity: 0;
    }

    VictimCard.visible {
        opacity: 1;
    }
    """

    def __init__(self, player_index: int, player_name: str, cause: str = "killed", **kwargs):
        super().__init__(**kwargs)
        self.player_index = player_index
        self.player_name = player_name
        self.cause = cause  # "killed" (야간) or "voted_out" (투표)

    def on_mount(self) -> None:
        if self.cause == "killed":
            icon = "🔪"
            title = "KILLED"
            color = "red"
        else:  # voted_out
            icon = "🗳️"
            title = "VOTED OUT"
            color = "yellow"

        content = f"""
{icon}  {title}  {icon}

━━━━━━━━━━━━━━━━━━━━

💀 Player {self.player_index}
{self.player_name}

━━━━━━━━━━━━━━━━━━━━
"""
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
        height: 1fr;
        align: center middle;
    }

    #main_panel {
        width: 60;
        height: auto;
        background: $surface-darken-1;
        border: double $primary;
        padding: 2;
    }

    .phase_title {
        width: 100%;
        text-align: center;
        text-style: bold;
        color: $warning;
        margin-bottom: 2;
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
        margin: 2 0;
    }

    .no_death {
        width: 100%;
        text-align: center;
        color: $success;
        text-style: bold;
        padding: 2;
    }

    #continue_hint {
        width: 100%;
        text-align: center;
        color: $text-muted;
        margin-top: 2;
    }

    /* 애니메이션 효과를 위한 스타일 */
    .dramatic-text {
        text-align: center;
        text-style: bold;
    }

    .sunrise {
        color: $warning;
    }

    .moonset {
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
        self.should_continue = False
        self.continue_event = asyncio.Event()

    def compose(self) -> ComposeResult:
        yield Header()

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
                    yield Static("🌅 The Night Has Ended", classes="phase_title sunrise")
                    yield Static("The village awakens to discover...", classes="subtitle")
                else:
                    yield Static("⚖️ The Vote Has Concluded", classes="phase_title")
                    yield Static("The village has decided...", classes="subtitle")

                # 사망자 표시
                with Center(id="victim_container"):
                    if self.victims:
                        for victim_idx in self.victims:
                            player_info = next(
                                (p for p in self.players if p["index"] == victim_idx),
                                {"index": victim_idx, "name": f"Player {victim_idx}"}
                            )
                            cause = "killed" if self.phase_type == "night" else "voted_out"
                            yield VictimCard(
                                player_index=victim_idx,
                                player_name=player_info["name"],
                                cause=cause,
                                id=f"victim_{victim_idx}"
                            )
                    else:
                        if self.phase_type == "night":
                            yield Static("✨ No one was killed tonight! ✨", classes="no_death")
                        else:
                            yield Static("🤝 No one was voted out.", classes="no_death")

                yield Static("Press [Enter] or [Space] to continue...", id="continue_hint")

        yield Footer()

    async def on_mount(self) -> None:
        """마운트 시 자동 진행 타이머 시작"""
        # 드라마틱 효과: 순차적으로 사망자 표시
        await self._dramatic_reveal()

        # 자동 진행 타이머
        asyncio.create_task(self._auto_continue_timer())

    async def _dramatic_reveal(self) -> None:
        """사망자를 드라마틱하게 순차 공개"""
        await asyncio.sleep(0.5)  # 초기 딜레이

        for i, victim_idx in enumerate(self.victims):
            try:
                victim_card = self.query_one(f"#victim_{victim_idx}", VictimCard)
                victim_card.add_class("visible")
                await asyncio.sleep(0.8)  # 각 사망자 사이 딜레이
            except Exception:
                pass

    async def _auto_continue_timer(self) -> None:
        """자동 진행 타이머"""
        hint = self.query_one("#continue_hint", Static)

        for remaining in range(self.auto_continue_seconds, 0, -1):
            if self.should_continue:
                return
            hint.update(f"Auto-continuing in {remaining}s... (Press Enter to skip)")
            await asyncio.sleep(1)

        if not self.should_continue:
            self.action_continue()

    def action_continue(self) -> None:
        """계속 진행"""
        self.should_continue = True
        self.continue_event.set()
        self.dismiss()


class NightResultScreen(DeathAnnouncementScreen):
    """야간 결과 발표 스크린 (별칭)"""

    def __init__(
        self,
        day_number: int,
        killed_players: List[int],
        players: List[dict],
        human_index: int = 0,
        human_role: str = "citizen",
        **kwargs
    ):
        super().__init__(
            phase_type="night",
            day_number=day_number,
            victims=killed_players,
            players=players,
            human_index=human_index,
            human_role=human_role,
            **kwargs
        )


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
            **kwargs
        )
        self.vote_counts = vote_counts

    def compose(self) -> ComposeResult:
        # 기본 compose 호출 전에 투표 결과 표시 추가
        yield Header()

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
                yield Static("⚖️ The Vote Has Concluded", classes="phase_title")

                # 투표 결과 표시 (있는 경우)
                if self.vote_counts:
                    yield Static("📊 Vote Results:", classes="subtitle")
                    yield VoteResultsPanel(
                        vote_counts=self.vote_counts,
                        players=self.players,
                        id="vote_results"
                    )

                yield Static("The village has decided...", classes="subtitle")

                # 사망자 표시
                with Center(id="victim_container"):
                    if self.victims:
                        for victim_idx in self.victims:
                            player_info = next(
                                (p for p in self.players if p["index"] == victim_idx),
                                {"index": victim_idx, "name": f"Player {victim_idx}"}
                            )
                            yield VictimCard(
                                player_index=victim_idx,
                                player_name=player_info["name"],
                                cause="voted_out",
                                id=f"victim_{victim_idx}"
                            )
                    else:
                        yield Static("🤝 No one was voted out.", classes="no_death")

                yield Static("Press [Enter] or [Space] to continue...", id="continue_hint")

        yield Footer()


class VoteResultsPanel(Static):
    """투표 결과 패널"""

    DEFAULT_CSS = """
    VoteResultsPanel {
        width: 100%;
        height: auto;
        padding: 1;
        margin: 1 0;
        background: $surface-darken-2;
        border: solid $accent;
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
            lines.append("   (투표 없음)")

        self.update("\n".join(lines))
```

---

## `screens/__init__.py` 수정 (업데이트)

```python
# 기존 import에 추가
from .components import PlayerStatusBar, PlayerCard
from .death_announcement import (
    DeathAnnouncementScreen,
    NightResultScreen,
    VoteResultScreen,
    VictimCard,
    VoteResultsPanel
)
```

---

## `app.py` 수정 - 사망자 발표 스크린 적용

```python
async def _run_game(self) -> None:
    """Run the game loop with TUI"""
    try:
        while True:
            # ========== Night Phase ==========
            human_player = self.game_engine.players[self.game_engine.human_player_index]
            survivors = self.game_engine.get_survivors()

            # Night action screen
            night_screen = NightScreen(
                self.game_engine.game_phases.day_number,
                human_player.alive,
                self.game_engine.human_role,
                survivors,
                players=self._get_players_data(),
                human_index=self.game_engine.human_player_index
            )

            self.push_screen(night_screen)

            # Wait for human action
            while not night_screen.action_submitted:
                await asyncio.sleep(0.5)

            # Set human action
            if human_player.alive and night_screen.selected_target is not None:
                self.game_engine.pending_human_action = night_screen.selected_target
                self.game_engine.human_action_ready = True
            else:
                self.game_engine.pending_human_action = -1
                self.game_engine.human_action_ready = True

            night_screen.add_message("⏳ Waiting for all players...", "yellow")

            # Execute night phase
            await self.game_engine.execute_night_phase()
            self.pop_screen()

            # ========== Night Result Screen (NEW!) ==========
            killed_players = self.game_engine.game_phases.last_killed or []

            # 플레이어 데이터 업데이트 (사망 반영)
            players_data = self._get_players_data()

            night_result_screen = NightResultScreen(
                day_number=self.game_engine.game_phases.day_number,
                killed_players=killed_players,
                players=players_data,
                human_index=self.game_engine.human_player_index,
                human_role=self.game_engine.human_role,
                auto_continue_seconds=5
            )

            self.push_screen(night_result_screen)

            # Wait for continue
            await night_result_screen.continue_event.wait()
            self.pop_screen()

            # Check win condition
            winner = await self.game_engine.check_win_condition()
            if winner:
                game_over_screen = GameOverScreen(winner, self.game_engine.players)
                self.push_screen(game_over_screen)
                while True:
                    await asyncio.sleep(1)

            # ========== Day Phase (Discussion) ==========
            # ... (기존 코드 동일) ...

            # ========== Vote Phase ==========
            self.game_engine.phase = "vote"
            human_player = self.game_engine.players[self.game_engine.human_player_index]
            survivors = self.game_engine.get_survivors()
            player_names = [p.name for p in self.game_engine.players]

            vote_screen = VoteScreen(
                self.game_engine.game_phases.day_number,
                human_player.alive,
                survivors,
                player_names,
                players=self._get_players_data(),
                human_index=self.game_engine.human_player_index,
                human_role=self.game_engine.human_role
            )

            self.push_screen(vote_screen)

            # Wait for vote
            while not vote_screen.vote_submitted:
                await asyncio.sleep(0.5)

            # Set human vote
            if human_player.alive and vote_screen.selected_target is not None:
                self.game_engine.pending_human_action = vote_screen.selected_target
                self.game_engine.human_action_ready = True
            else:
                self.game_engine.pending_human_action = -1
                self.game_engine.human_action_ready = True

            vote_screen.add_message("⏳ Collecting votes...", "yellow")

            # Execute vote phase
            await self.game_engine.execute_vote_phase()
            self.pop_screen()

            # ========== Vote Result Screen (NEW!) ==========
            voted_out = self.game_engine.game_phases.last_voted_out
            vote_counts = getattr(self.game_engine.game_phases, 'last_vote_counts', None)

            # 플레이어 데이터 업데이트 (사망 반영)
            players_data = self._get_players_data()

            vote_result_screen = VoteResultScreen(
                day_number=self.game_engine.game_phases.day_number,
                voted_out_player=voted_out,
                players=players_data,
                vote_counts=vote_counts,
                human_index=self.game_engine.human_player_index,
                human_role=self.game_engine.human_role,
                auto_continue_seconds=5
            )

            self.push_screen(vote_result_screen)

            # Wait for continue
            await vote_result_screen.continue_event.wait()
            self.pop_screen()

            # Check win condition
            winner = await self.game_engine.check_win_condition()
            if winner:
                game_over_screen = GameOverScreen(winner, self.game_engine.players)
                self.push_screen(game_over_screen)
                while True:
                    await asyncio.sleep(1)

    except KeyboardInterrupt:
        pass
    except Exception as e:
        import traceback
        print(f"Error in game loop: {e}")
        traceback.print_exc()
```

---

## 예상 결과물 (TUI 미리보기)

### 야간 사망자 발표

```
┌──────────────────────────────────────────────────────────────────────────┐
│                        🌅 Dawn of Day 2                                   │
├──────────────────────────────────────────────────────────────────────────┤
│  ╔════════════╗  ╔════════════╗  ╔════════════╗  ╔════════════╗          │
│  ║ 🟢 P0 (You)║  ║ 🟢 P1      ║  ║ 💀 P2      ║  ║ 🟢 P3      ║          │
│  ║ Human      ║  ║ Bot1       ║  ║ Bot2       ║  ║ Bot3       ║          │
│  ║ 🔪 MAFIA   ║  ╚════════════╝  ╚════════════╝  ╚════════════╝          │
│  ╚════════════╝                                                           │
├──────────────────────────────────────────────────────────────────────────┤
│                                                                           │
│                    🌅 The Night Has Ended                                 │
│                                                                           │
│               The village awakens to discover...                          │
│                                                                           │
│              ╔══════════════════════════════════════╗                     │
│              ║                                      ║                     │
│              ║         🔪  KILLED  🔪               ║                     │
│              ║                                      ║                     │
│              ║      ━━━━━━━━━━━━━━━━━━━━            ║                     │
│              ║                                      ║                     │
│              ║          💀 Player 2                 ║                     │
│              ║             Bot2                     ║                     │
│              ║                                      ║                     │
│              ║      ━━━━━━━━━━━━━━━━━━━━            ║                     │
│              ║                                      ║                     │
│              ╚══════════════════════════════════════╝                     │
│                                                                           │
│              Auto-continuing in 3s... (Press Enter to skip)               │
│                                                                           │
└──────────────────────────────────────────────────────────────────────────┘
```

### 투표 결과 발표

```
┌──────────────────────────────────────────────────────────────────────────┐
│                        ⚖️ Day 2 - Judgement                               │
├──────────────────────────────────────────────────────────────────────────┤
│  ╔════════════╗  ╔════════════╗  ╔════════════╗  ╔════════════╗          │
│  ║ 🟢 P0 (You)║  ║ 💀 P1      ║  ║ 🟢 P2      ║  ║ 🟢 P3      ║          │
│  ║ Human      ║  ║ Bot1       ║  ║ Bot2       ║  ║ Bot3       ║          │
│  ║ 👤 CITIZEN ║  ╚════════════╝  ╚════════════╝  ╚════════════╝          │
│  ╚════════════╝                                                           │
├──────────────────────────────────────────────────────────────────────────┤
│                                                                           │
│                    ⚖️ The Vote Has Concluded                              │
│                                                                           │
│                       📊 Vote Results:                                    │
│              ┌────────────────────────────────────┐                       │
│              │ 👉 P1 Bot1     [████████████░░░░░░] 3표 │                  │
│              │    P3 Bot3     [████████░░░░░░░░░░] 2표 │                  │
│              │    P0 Human    [████░░░░░░░░░░░░░░] 1표 │                  │
│              └────────────────────────────────────┘                       │
│                                                                           │
│               The village has decided...                                  │
│                                                                           │
│              ╔══════════════════════════════════════╗                     │
│              ║                                      ║                     │
│              ║         🗳️  VOTED OUT  🗳️           ║                     │
│              ║                                      ║                     │
│              ║      ━━━━━━━━━━━━━━━━━━━━            ║                     │
│              ║                                      ║                     │
│              ║          💀 Player 1                 ║                     │
│              ║             Bot1                     ║                     │
│              ║                                      ║                     │
│              ║      ━━━━━━━━━━━━━━━━━━━━            ║                     │
│              ║                                      ║                     │
│              ╚══════════════════════════════════════╝                     │
│                                                                           │
│              Press [Enter] or [Space] to continue...                      │
│                                                                           │
└──────────────────────────────────────────────────────────────────────────┘
```

### 아무도 안 죽었을 때

```
┌──────────────────────────────────────────────────────────────────────────┐
│                                                                           │
│                    🌅 The Night Has Ended                                 │
│                                                                           │
│               The village awakens to discover...                          │
│                                                                           │
│                                                                           │
│                  ✨ No one was killed tonight! ✨                         │
│                                                                           │
│                                                                           │
│              Auto-continuing in 4s... (Press Enter to skip)               │
│                                                                           │
└──────────────────────────────────────────────────────────────────────────┘
```

---

## 추가 개선 아이디어

1. **클릭으로 타겟 선택**: PlayerCard 클릭 시 자동으로 타겟 입력
2. **실시간 업데이트**: 플레이어 사망 시 즉시 UI 반영
3. **투표 현황 표시**: 각 플레이어가 받은 투표 수 표시
4. **역할 힌트**: 경찰 조사 결과를 PlayerCard에 표시 (마피아 확정 등)
5. **사운드 효과**: 사망자 발표 시 효과음 (터미널 벨 등)
6. **역할 공개**: 사망자의 역할을 발표 시 함께 공개하는 옵션
