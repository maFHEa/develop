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

        # Chat display
        yield RichLog(id="chat_display", highlight=True, markup=True, auto_scroll=True)

        # Input
        with Horizontal(id="input_container"):
            yield Input(placeholder="메시지를 입력하세요... (Ctrl+D로 진행)", id="chat_input")

    async def on_mount(self) -> None:
        """Initialize chat screen"""
        # Start timer
        import time
        self.start_time = time.time()

        # Check if human player is alive
        human_player = self.game_engine.players[self.game_engine.human_player_index]

        # Initialize last_displayed_msg_id if not set
        if not hasattr(self.game_engine, 'last_displayed_msg_id'):
            self.game_engine.last_displayed_msg_id = -1

        # Welcome messages
        chat = self.query_one("#chat_display", RichLog)
        chat.write(Text("=" * 60, style="bold yellow"))
        day_num = self.game_engine.game_phases.day_number if self.game_engine.game_phases else 0
        chat.write(Text(f"DAY {day_num} - 토론 단계", style="bold cyan"))
        chat.write(Text("=" * 60, style="bold yellow"))

        if not human_player.alive:
            chat.write(Text("💀 당신은 사망했습니다", style="bold red"))
            chat.write(Text("👻 관전만 가능하며 참여는 불가합니다", style="dim"))
            # Disable input for dead players
            chat_input = self.query_one("#chat_input", Input)
            chat_input.disabled = True
            chat_input.placeholder = "사망하여 메시지를 보낼 수 없습니다"
        else:
            chat.write(Text("💬 다른 플레이어들과 대화하세요", style="dim"))
            chat.write(Text("⌨️  Ctrl+D를 눌러 투표로 진행하세요", style="dim"))
        chat.write("")

        # Focus input
        self.query_one("#chat_input", Input).focus()

        # Start message checker
        self.message_check_task = asyncio.create_task(self._check_messages())

    async def on_input_submitted(self, event: Input.Submitted) -> None:
        """Handle message submission"""
        message = event.value.strip()
        if not message:
            return

        # Check if player is alive
        human_player = self.game_engine.players[self.game_engine.human_player_index]
        if not human_player.alive:
            chat = self.query_one("#chat_display", RichLog)
            chat.write(Text("💀 사망하여 메시지를 보낼 수 없습니다", style="red"))
            event.input.value = ""
            return

        # Clear input
        event.input.value = ""

        # Display own message with player color and send status
        chat = self.query_one("#chat_display", RichLog)
        human_color = get_player_color(self.game_engine.human_player_index)

        try:
            # Send to game engine (this adds message to chat_history)
            await self.game_engine.broadcast_chat_message(
                self.game_engine.human_player_index,
                message
            )

            # Update last_displayed_msg_id to the latest message (our own message)
            # This prevents the message checker from displaying our message again
            if self.game_engine.chat_history.messages:
                latest_msg = self.game_engine.chat_history.messages[-1]
                self.game_engine.last_displayed_msg_id = latest_msg.msg_id

            # 메시지와 성공 표시를 같은 줄에
            msg_text = Text(f"[나] {message} ", style=f"bold {human_color}")
            msg_text.append("✓", style="green")
            chat.write(msg_text)
        except Exception as e:
            # 메시지와 실패 표시를 같은 줄에
            msg_text = Text(f"[나] {message} ", style=f"bold {human_color}")
            msg_text.append("✗", style="red")
            chat.write(msg_text)

    async def _check_messages(self) -> None:
        """Background task to check for new messages from chat history and agents"""
        chat = self.query_one("#chat_display", RichLog)

        while not self.should_proceed:
            try:
                # Update timer
                import time
                if self.start_time:
                    elapsed = int(time.time() - self.start_time)
                    remaining = max(0, self.duration_seconds - elapsed)

                    # Update title with remaining time
                    try:
                        player_bar = self.query_one("#player_bar", PlayerStatusBar)
                        day_num = self.game_engine.game_phases.day_number if self.game_engine.game_phases else 0
                        # PlayerStatusBar doesn't have direct title update, so we skip this for now

                    except Exception:
                        pass

                    # Auto-proceed when time runs out
                    if remaining == 0:
                        chat.write(Text("\n⏰ 시간 종료! 투표로 이동합니다...", style="bold red"))
                        await asyncio.sleep(1)
                        await self._do_proceed()
                        break

                # Poll agent messages and broadcast them
                await self._poll_agent_messages()

                # Get new messages since last check from chat history
                new_messages = self.game_engine.chat_history.get_messages_from(
                    self.game_engine.last_displayed_msg_id + 1
                )

                if new_messages:
                    for msg in new_messages:
                        # Skip human player's own messages (already displayed)
                        if msg.player_index != self.game_engine.human_player_index:
                            player = self.game_engine.players[msg.player_index]
                            player_color = get_player_color(msg.player_index)
                            # 플레이어 이름은 색상으로, 메시지는 흰색으로
                            name_text = Text(f"[{player.name}] ", style=f"bold {player_color}")
                            msg_text = Text(msg.message, style="white")
                            chat.write(name_text + msg_text)
                        # Update last displayed ID
                        self.game_engine.last_displayed_msg_id = msg.msg_id

                await asyncio.sleep(0.5)  # Poll every 0.5 seconds
            except AttributeError as e:
                chat.write(Text(f"채팅 시스템 초기화 안됨: {e}", style="red"))
                await asyncio.sleep(1)
            except Exception as e:
                chat.write(Text(f"메시지 확인 오류: {e}", style="red"))
                await asyncio.sleep(1)

    async def _poll_agent_messages(self) -> None:
        """Poll all agents for pending messages and broadcast them"""
        async with httpx.AsyncClient(timeout=2.0) as client:
            tasks = []
            for player in self.game_engine.players:
                if not player.is_human and player.alive:
                    tasks.append(self._get_agent_messages(client, player))

            if tasks:
                results = await asyncio.gather(*tasks, return_exceptions=True)

                # Broadcast any messages we received
                for player, result in zip(
                    [p for p in self.game_engine.players if not p.is_human and p.alive],
                    results
                ):
                    if not isinstance(result, Exception) and result:
                        messages = result.get("messages", [])
                        for msg in messages:
                            # Broadcast to all agents (including sender will filter it out)
                            await self.game_engine.broadcast_chat_message(player.index, msg)

    async def _get_agent_messages(self, client: httpx.AsyncClient, player) -> dict:
        """Get pending messages from a single agent"""
        try:
            response = await client.get(f"{player.address}/chat/messages")
            if response.status_code == 200:
                return response.json()
            return {"messages": []}
        except Exception:
            # Silently fail - agent might not have messages
            return {"messages": []}

    async def _do_proceed(self) -> None:
        """Internal async proceed handler"""
        if self.should_proceed:
            return  # Already proceeding

        self.should_proceed = True
        if self.message_check_task:
            self.message_check_task.cancel()

        # Stop agent chat phase
        try:
            await self.game_engine.stop_agent_chat_phase()
        except Exception:
            pass

        # Note: dismiss()를 호출하지 않음 - app.py의 while 루프가 should_proceed를 감지하고 처리

    def action_proceed(self) -> None:
        """Proceed to voting phase (Ctrl+D handler)"""
        # Schedule the async work
        asyncio.create_task(self._do_proceed())

    async def on_key(self, event) -> None:
        """Handle key events - backup for Ctrl+D when input has focus"""
        if event.key == "ctrl+d":
            event.prevent_default()
            event.stop()
            await self._do_proceed()
