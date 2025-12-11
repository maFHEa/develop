"""
Shared UI Components for Mafia Game TUI
"""
from textual.app import ComposeResult
from textual.widget import Widget
from textual.widgets import Static
from textual.containers import Horizontal
from textual.message import Message
from rich.text import Text
from typing import List, Optional


# 플레이어별 고유 색상 (터미널에서 잘 보이는 색상들)
PLAYER_COLORS = [
    "#00BFFF",  # P0: Deep Sky Blue
    "#FF6B6B",  # P1: Coral Red
    "#98D8AA",  # P2: Mint Green
    "#DDA0DD",  # P3: Plum
    "#F4D03F",  # P4: Golden Yellow
    "#87CEEB",  # P5: Sky Blue
    "#FF8C00",  # P6: Dark Orange
    "#00CED1",  # P7: Dark Turquoise
]


def get_player_color(player_index: int) -> str:
    """플레이어 인덱스에 따른 고유 색상 반환"""
    return PLAYER_COLORS[player_index % len(PLAYER_COLORS)]


def get_player_style(player_index: int) -> str:
    """플레이어 인덱스에 따른 rich 스타일 문자열 반환"""
    return get_player_color(player_index)


class PlayerCard(Static):
    """Single player card widget - clickable for target selection"""

    class Selected(Message):
        """Message sent when a player card is clicked"""
        def __init__(self, player_index: int, player_name: str) -> None:
            self.player_index = player_index
            self.player_name = player_name
            super().__init__()

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
        border: heavy $warning;
        background: $warning 30%;
    }

    PlayerCard.selectable:hover {
        border: solid $warning;
        background: $warning 10%;
    }

    PlayerCard.disabled {
        opacity: 0.5;
    }

    /* 플레이어별 고유 색상 */
    PlayerCard.player-0 { border: solid #00BFFF; }
    PlayerCard.player-1 { border: solid #FF6B6B; }
    PlayerCard.player-2 { border: solid #98D8AA; }
    PlayerCard.player-3 { border: solid #DDA0DD; }
    PlayerCard.player-4 { border: solid #F4D03F; }
    PlayerCard.player-5 { border: solid #87CEEB; }
    PlayerCard.player-6 { border: solid #FF8C00; }
    PlayerCard.player-7 { border: solid #00CED1; }

    PlayerCard.selectable.player-0 { border: dashed #00BFFF; }
    PlayerCard.selectable.player-1 { border: dashed #FF6B6B; }
    PlayerCard.selectable.player-2 { border: dashed #98D8AA; }
    PlayerCard.selectable.player-3 { border: dashed #DDA0DD; }
    PlayerCard.selectable.player-4 { border: dashed #F4D03F; }
    PlayerCard.selectable.player-5 { border: dashed #87CEEB; }
    PlayerCard.selectable.player-6 { border: dashed #FF8C00; }
    PlayerCard.selectable.player-7 { border: dashed #00CED1; }
    """

    def __init__(
        self,
        player_index: int,
        player_name: str,
        is_alive: bool = True,
        is_human: bool = False,
        role: Optional[str] = None,
        show_role: bool = False,
        selectable: bool = False,
        **kwargs
    ):
        super().__init__(**kwargs)
        self.player_index = player_index
        self.player_name = player_name
        self.is_alive = is_alive
        self.is_human = is_human
        self.role = role
        self.show_role = show_role
        self.selectable = selectable
        self._is_selected = False
        self._update_classes()

    def _update_classes(self):
        """Update CSS classes based on state"""
        # 기존 상태 클래스 제거
        self.remove_class("alive", "dead", "human", "selectable", "disabled")
        # 기존 플레이어 색상 클래스 제거
        for i in range(8):
            self.remove_class(f"player-{i}")

        # 플레이어별 고유 색상 클래스 추가
        self.add_class(f"player-{self.player_index % 8}")

        if self.is_alive:
            self.add_class("alive")
        else:
            self.add_class("dead")
        if self.is_human:
            self.add_class("human")
        if self.selectable and self.is_alive:
            self.add_class("selectable")

    def compose(self) -> ComposeResult:
        return []

    def on_mount(self) -> None:
        self._render_card()

    def _render_card(self) -> None:
        """Render the card content"""
        # Player info - 죽었을 때만 해골 표시
        # 사람은 "나"만 표시, 역할은 상단 타이틀에서 별도 표시
        if self.is_human:
            name_line = "💀 나" if not self.is_alive else "나"
        else:
            name_line = f"💀 P{self.player_index}" if not self.is_alive else f"P{self.player_index}"

        self.update(name_line)

    def on_click(self) -> None:
        """Handle click events"""
        if self.selectable and self.is_alive and not self.has_class("disabled"):
            self.post_message(self.Selected(self.player_index, self.player_name))

    def set_selected(self, selected: bool) -> None:
        """Set selection state"""
        self._is_selected = selected
        if selected:
            self.add_class("selected")
        else:
            self.remove_class("selected")

    def set_selectable(self, selectable: bool) -> None:
        """Set whether this card can be selected"""
        self.selectable = selectable
        self._update_classes()

    def set_disabled(self, disabled: bool) -> None:
        """Disable the card (for submitted state)"""
        if disabled:
            self.add_class("disabled")
            self.selectable = False
        else:
            self.remove_class("disabled")

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
        selectable: bool = False,
        exclude_self: bool = False,
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
            selectable: Whether player cards can be clicked to select
            exclude_self: Whether to exclude human player from selection
        """
        super().__init__(**kwargs)
        self.players = players
        self.human_index = human_index
        self.human_role = human_role
        self.show_human_role = show_human_role
        self.title = title
        self.selectable = selectable
        self.exclude_self = exclude_self
        self.player_cards: List[PlayerCard] = []

    def _get_role_display(self) -> str:
        """역할을 한글로 표시"""
        if not self.human_role:
            return ""
        role_names = {
            "mafia": "마피아",
            "doctor": "의사",
            "police": "경찰",
            "citizen": "시민"
        }
        role_icons = {
            "mafia": "🔪",
            "doctor": "💉",
            "police": "🔍",
            "citizen": "👤"
        }
        role_name = role_names.get(self.human_role.lower(), self.human_role)
        icon = role_icons.get(self.human_role.lower(), "")
        return f" | {icon} {role_name}"

    def compose(self) -> ComposeResult:
        if self.title:
            # 타이틀에 역할 표시 추가
            role_display = self._get_role_display() if self.show_human_role else ""
            yield Static(f"{self.title}{role_display}", classes="title")

        with Horizontal():
            for p in self.players:
                is_human = p.get("index", -1) == self.human_index
                show_role = is_human and self.show_human_role
                role = self.human_role if is_human else None

                # Determine if this card should be selectable
                card_selectable = self.selectable and p.get("alive", True)
                if self.exclude_self and is_human:
                    card_selectable = False

                card = PlayerCard(
                    player_index=p.get("index", 0),
                    player_name=p.get("name", f"Player {p.get('index', 0)}"),
                    is_alive=p.get("alive", True),
                    is_human=is_human,
                    role=role,
                    show_role=show_role,
                    selectable=card_selectable,
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

    def disable_all(self) -> None:
        """Disable all player cards"""
        for card in self.player_cards:
            card.set_disabled(True)

    def get_player_card(self, index: int) -> Optional[PlayerCard]:
        """Get a player card by index"""
        for card in self.player_cards:
            if card.player_index == index:
                return card
        return None
