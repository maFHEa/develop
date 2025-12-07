"""
Chat Screen for Discussion Phase
"""
from textual.app import ComposeResult
from textual.widgets import Header, Footer, Static, Input
from textual.containers import Container, Horizontal, Vertical, VerticalScroll
from textual.binding import Binding
from textual.screen import Screen
from rich.text import Text
from typing import Optional, List
import asyncio
import httpx

from .components import PlayerStatusBar, get_player_color


class ChatScreen(Screen):
    """Chat discussion phase screen"""

    CSS = """
    ChatScreen {
        background: $surface;
    }

    #player_bar {
        dock: top;
    }

    #timer_bar {
        dock: top;
        height: 1;
        background: $primary;
        text-align: center;
        text-style: bold;
        margin-top: 1;
    }

    #chat_container {
        height: 1fr;
        margin: 0 1;
    }

    #chat_scroll {
        height: 1fr;
        background: $surface-darken-1;
        padding: 1;
    }

    #chat_content {
        width: 100%;
        height: auto;
    }

    .chat_message {
        width: 100%;
        margin-bottom: 1;
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
        yield Footer()

        # 상단 플레이어 상태바
        day_num = self.game_engine.game_phases.day_number if self.game_engine.game_phases else 0
        yield PlayerStatusBar(
            players=self._get_players_data(),
            human_index=self.game_engine.human_player_index,
            human_role=self.game_engine.human_role,
            show_human_role=True,
            title=f"💬 Day {day_num} - Discussion",
            id="player_bar"
        )

        # Timer bar
        yield Static(f"⏱️ 남은 시간: {self.duration_seconds}초", id="timer_bar")

        # Chat display (scrollable vertical container)
        with Container(id="chat_container"):
            with VerticalScroll(id="chat_scroll"):
                yield Vertical(id="chat_content")

        # Input
        with Horizontal(id="input_container"):
            yield Input(placeholder="메시지를 입력하세요... (Ctrl+D로 투표 진행)", id="chat_input")

    async def on_mount(self) -> None:
        """Initialize chat screen"""
        import time
        self.start_time = time.time()

        human_player = self.game_engine.players[self.game_engine.human_player_index]

        if not hasattr(self.game_engine, 'last_displayed_msg_id'):
            self.game_engine.last_displayed_msg_id = -1

        if not human_player.alive:
            chat_input = self.query_one("#chat_input", Input)
            chat_input.disabled = True
            chat_input.placeholder = "사망하여 메시지를 보낼 수 없습니다"

        self.query_one("#chat_input", Input).focus()
        self.message_check_task = asyncio.create_task(self._check_messages())

    def _add_chat_message(self, text: str) -> None:
        """Add a message to chat with word wrap"""
        try:
            chat_content = self.query_one("#chat_content", Vertical)
            chat_content.mount(Static(text, classes="chat_message"))
            # Auto scroll to bottom after layout refresh
            self.call_after_refresh(self._scroll_to_bottom)
        except Exception:
            pass

    def _scroll_to_bottom(self) -> None:
        """Scroll chat to bottom"""
        try:
            scroll = self.query_one("#chat_scroll", VerticalScroll)
            scroll.scroll_y = scroll.max_scroll_y
        except Exception:
            pass

    async def on_input_submitted(self, event: Input.Submitted) -> None:
        """Handle message submission"""
        message = event.value.strip()
        if not message:
            return

        human_player = self.game_engine.players[self.game_engine.human_player_index]
        if not human_player.alive:
            self._add_chat_message("[red]💀 사망하여 메시지를 보낼 수 없습니다[/]")
            event.input.value = ""
            return

        event.input.value = ""
        human_color = get_player_color(self.game_engine.human_player_index)

        try:
            await self.game_engine.broadcast_chat_message(
                self.game_engine.human_player_index,
                message
            )

            if self.game_engine.chat_history.messages:
                latest_msg = self.game_engine.chat_history.messages[-1]
                self.game_engine.last_displayed_msg_id = latest_msg.msg_id

            self._add_chat_message(f"[bold {human_color}]\\[나][/] {message} [green]✓[/]")
        except Exception as e:
            self._add_chat_message(f"[bold {human_color}]\\[나][/] {message} [red]✗[/]")

    async def _check_messages(self) -> None:
        """Background task to check for new messages"""
        while not self.should_proceed:
            try:
                import time
                if self.start_time:
                    elapsed = int(time.time() - self.start_time)
                    remaining = max(0, self.duration_seconds - elapsed)

                    # Update timer
                    try:
                        timer = self.query_one("#timer_bar", Static)
                        if remaining > 30:
                            timer.update(f"⏱️ 남은 시간: {remaining}초")
                        elif remaining > 10:
                            timer.update(f"[yellow]⏱️ 남은 시간: {remaining}초[/]")
                        else:
                            timer.update(f"[bold red]⏱️ 남은 시간: {remaining}초![/]")
                    except Exception:
                        pass

                    if remaining == 0:
                        self._add_chat_message("[bold red]⏰ 시간 종료! 투표로 이동합니다...[/]")
                        await asyncio.sleep(1)
                        await self._do_proceed()
                        break

                await self._poll_agent_messages()

                new_messages = self.game_engine.chat_history.get_messages_from(
                    self.game_engine.last_displayed_msg_id + 1
                )

                if new_messages:
                    for msg in new_messages:
                        if msg.player_index != self.game_engine.human_player_index:
                            player = self.game_engine.players[msg.player_index]
                            player_color = get_player_color(msg.player_index)
                            self._add_chat_message(f"[bold {player_color}]\\[{player.name}][/] {msg.message}")
                        self.game_engine.last_displayed_msg_id = msg.msg_id

                await asyncio.sleep(0.5)
            except AttributeError as e:
                self._add_chat_message(f"[red]채팅 시스템 초기화 안됨: {e}[/]")
                await asyncio.sleep(1)
            except Exception as e:
                self._add_chat_message(f"[red]메시지 확인 오류: {e}[/]")
                await asyncio.sleep(1)

    async def _poll_agent_messages(self) -> None:
        """Poll all agents for pending messages"""
        async with httpx.AsyncClient(timeout=2.0) as client:
            tasks = []
            for player in self.game_engine.players:
                if not player.is_human and player.alive:
                    tasks.append(self._get_agent_messages(client, player))

            if tasks:
                results = await asyncio.gather(*tasks, return_exceptions=True)

                for player, result in zip(
                    [p for p in self.game_engine.players if not p.is_human and p.alive],
                    results
                ):
                    if not isinstance(result, Exception) and result:
                        messages = result.get("messages", [])
                        for msg in messages:
                            await self.game_engine.broadcast_chat_message(player.index, msg)

    async def _get_agent_messages(self, client: httpx.AsyncClient, player) -> dict:
        """Get pending messages from a single agent"""
        try:
            response = await client.get(f"{player.address}/chat/messages")
            if response.status_code == 200:
                return response.json()
            return {"messages": []}
        except Exception:
            return {"messages": []}

    async def _do_proceed(self) -> None:
        """Internal async proceed handler"""
        if self.should_proceed:
            return

        self.should_proceed = True
        if self.message_check_task:
            self.message_check_task.cancel()

        try:
            await self.game_engine.stop_agent_chat_phase()
        except Exception:
            pass

    def action_proceed(self) -> None:
        """Proceed to voting phase"""
        asyncio.create_task(self._do_proceed())

    async def on_key(self, event) -> None:
        """Handle key events"""
        if event.key == "ctrl+d":
            event.prevent_default()
            event.stop()
            await self._do_proceed()
