"""  
Chat Screen for Discussion Phase
"""
from textual.app import ComposeResult
from textual.widgets import Header, Footer, Label, RichLog, Input
from textual.containers import Container, Horizontal
from textual.binding import Binding
from textual.screen import Screen
from rich.text import Text
from typing import Optional
import asyncio
import httpx


class ChatScreen(Screen):
    """Chat discussion phase screen"""
    
    CSS = """
    ChatScreen {
        background: $surface;
    }
    
    #game_info {
        dock: top;
        height: 3;
        background: $primary;
        content-align: center middle;
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
    
    def compose(self) -> ComposeResult:
        yield Header()
        
        # Game info bar
        with Container(id="game_info"):
            yield Label(id="info_label")
        
        # Chat display
        yield RichLog(id="chat_display", highlight=True, markup=True, auto_scroll=True)
        
        # Input
        with Horizontal(id="input_container"):
            yield Input(placeholder="Type your message... (Ctrl+D to proceed)", id="chat_input")
        
        yield Footer()
    
    async def on_mount(self) -> None:
        """Initialize chat screen"""
        # Start timer
        import time
        self.start_time = time.time()
        
        # Check if human player is alive
        human_player = self.game_engine.players[self.game_engine.human_player_index]
        
        # Update game info
        alive_count = sum(1 for p in self.game_engine.players if p.alive)
        info = self.query_one("#info_label", Label)
        day_num = self.game_engine.game_phases.day_number if self.game_engine.game_phases else 0
        
        if not human_player.alive:
            info.update(f"Day {day_num} | DISCUSSION | Alive: {alive_count} | ☠️ YOU ARE DEAD")
        else:
            info.update(f"Day {day_num} | DISCUSSION | Alive: {alive_count} | Time: {self.duration_seconds}s")
        
        # Initialize last_displayed_msg_id if not set
        if not hasattr(self.game_engine, 'last_displayed_msg_id'):
            self.game_engine.last_displayed_msg_id = -1
        
        # Welcome messages
        chat = self.query_one("#chat_display", RichLog)
        chat.write(Text("=" * 60, style="bold yellow"))
        day_num = self.game_engine.game_phases.day_number if self.game_engine.game_phases else 0
        chat.write(Text(f"DAY {day_num} - DISCUSSION PHASE", style="bold cyan"))
        chat.write(Text("=" * 60, style="bold yellow"))
        
        if not human_player.alive:
            chat.write(Text("💀 YOU ARE DEAD", style="bold red"))
            chat.write(Text("👻 You can observe but cannot participate", style="dim"))
            # Disable input for dead players
            chat_input = self.query_one("#chat_input", Input)
            chat_input.disabled = True
            chat_input.placeholder = "You are dead and cannot send messages"
        else:
            chat.write(Text("💬 Chat with other players", style="dim"))
            chat.write(Text("⌨️  Press Ctrl+D to proceed to voting", style="dim"))
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
            chat.write(Text("💀 You are dead and cannot send messages", style="red"))
            event.input.value = ""
            return
        
        # Clear input
        event.input.value = ""
        
        # Display own message
        chat = self.query_one("#chat_display", RichLog)
        chat.write(Text(f"[You] {message}", style="bold cyan"))
        
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
            
            chat.write(Text("✓ Message sent", style="dim green"))
        except Exception as e:
            chat.write(Text(f"❌ Failed to send: {e}", style="red"))
    
    async def _check_messages(self) -> None:
        """Background task to check for new messages from chat history and agents"""
        chat = self.query_one("#chat_display", RichLog)
        info = self.query_one("#info_label", Label)
        
        while not self.should_proceed:
            try:
                # Update timer
                import time
                if self.start_time:
                    elapsed = int(time.time() - self.start_time)
                    remaining = max(0, self.duration_seconds - elapsed)
                    
                    alive_count = sum(1 for p in self.game_engine.players if p.alive)
                    day_num = self.game_engine.game_phases.day_number if self.game_engine.game_phases else 0
                    info.update(f"Day {day_num} | DISCUSSION | Alive: {alive_count} | Time: {remaining}s")
                    
                    # Auto-proceed when time runs out
                    if remaining == 0:
                        chat.write(Text("\n⏰ Time's up! Moving to voting...", style="bold red"))
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
                            chat.write(Text(f"[{player.name}] {msg.message}", style="white"))
                        # Update last displayed ID
                        self.game_engine.last_displayed_msg_id = msg.msg_id
                
                await asyncio.sleep(0.5)  # Poll every 0.5 seconds
            except AttributeError as e:
                chat.write(Text(f"Chat system not initialized: {e}", style="red"))
                await asyncio.sleep(1)
            except Exception as e:
                chat.write(Text(f"Error checking messages: {e}", style="red"))
                await asyncio.sleep(1)
    
    async def _poll_agent_messages(self) -> None:
        """Poll all agents for pending messages and broadcast them"""
        import httpx
        
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
        except Exception as e:
            # Silently fail - agent might not have messages
            return {"messages": []}
    
    async def _do_proceed(self) -> None:
        """Internal async proceed handler"""
        self.should_proceed = True
        if self.message_check_task:
            self.message_check_task.cancel()
        
        # Stop agent chat phase
        await self.game_engine.stop_agent_chat_phase()
        
        # Return to main app flow
        self.dismiss()
    
    def action_proceed(self) -> None:
        """Proceed to voting phase (Ctrl+D handler)"""
        # Schedule the async work
        asyncio.create_task(self._do_proceed())
