#!/usr/bin/env python3
"""GooseTown WebSocket daemon.

Maintains a persistent WebSocket connection to GooseTown.
Tools communicate with this daemon via a Unix domain socket.
State is cached to a local JSON file for instant reads.

Usage:
    TOWN_WS_URL=wss://... TOWN_TOKEN=tok_... TOWN_AGENT=lucky python3 town_daemon.py
"""

import asyncio
import json
import logging
import os
import signal
import sys
from pathlib import Path

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("town_daemon")

# Config from environment
WS_URL = os.environ.get("TOWN_WS_URL", "")
TOKEN = os.environ.get("TOWN_TOKEN", "")
AGENT_NAME = os.environ.get("TOWN_AGENT", "")
STATE_DIR = Path(os.environ.get("STATE_DIR", f"/tmp/goosetown/{AGENT_NAME}"))

STATE_FILE = STATE_DIR / "state.json"
ALARM_FILE = STATE_DIR / "alarm.json"
PID_FILE = STATE_DIR / "daemon.pid"
SOCK_PATH = STATE_DIR / "daemon.sock"
WORKSPACE_PATH = Path(os.environ.get("TOWN_WORKSPACE", ""))

GATEWAY_PORT = os.environ.get("GATEWAY_PORT", "18789")
GATEWAY_TOKEN = os.environ.get("GATEWAY_TOKEN", "")


class GatewayRPC:
    """WebSocket RPC client for local OpenClaw Gateway."""

    def __init__(self):
        self.ws = None
        self._req_counter = 0
        self._pending: dict[str, asyncio.Future] = {}

    async def connect(self):
        try:
            import websockets
        except ImportError:
            raise ImportError("websockets package not installed")

        url = f"ws://localhost:{GATEWAY_PORT}"
        self.ws = await websockets.connect(url, ping_interval=30, ping_timeout=10)
        hello = {"type": "hello"}
        if GATEWAY_TOKEN:
            hello["token"] = GATEWAY_TOKEN
        await self.ws.send(json.dumps(hello))
        resp = json.loads(await self.ws.recv())
        if resp.get("type") != "hello-ok":
            raise ConnectionError(f"Gateway auth failed: {resp}")
        logger.info("Connected to local OpenClaw Gateway RPC")

    async def send_agent_message(self, message: str, thinking: str = "low") -> dict:
        self._req_counter += 1
        req_id = f"think-{self._req_counter}"
        req = {
            "type": "req",
            "id": req_id,
            "method": "agent",
            "params": {"message": message, "thinking": thinking},
        }
        future = asyncio.get_event_loop().create_future()
        self._pending[req_id] = future
        await self.ws.send(json.dumps(req))
        try:
            return await asyncio.wait_for(future, timeout=120.0)
        except asyncio.TimeoutError:
            self._pending.pop(req_id, None)
            return {"error": "timeout"}

    async def listen(self):
        async for raw in self.ws:
            try:
                data = json.loads(raw)
                if data.get("type") == "res":
                    req_id = data.get("id")
                    future = self._pending.pop(req_id, None)
                    if future and not future.done():
                        future.set_result(data)
            except json.JSONDecodeError:
                pass

    async def close(self):
        if self.ws:
            await self.ws.close()


class TownDaemon:
    def __init__(self):
        self.state: dict = {}
        self.running = True
        self.ws = None
        self._thinking = False
        self._gateway: GatewayRPC | None = None
        self._initial_state_event = asyncio.Event()
        self._arrived_event = asyncio.Event()

    def _write_state(self):
        STATE_DIR.mkdir(parents=True, exist_ok=True)
        STATE_FILE.write_text(json.dumps(self.state, indent=2))

    def _write_status(self, content: str):
        """Write TOWN_STATUS.md to agent workspace."""
        if not WORKSPACE_PATH or not WORKSPACE_PATH.exists():
            logger.debug("No workspace path, skipping TOWN_STATUS.md write")
            return
        status_file = WORKSPACE_PATH / "TOWN_STATUS.md"
        status_file.write_text(content)

    def _handle_event(self, data: dict):
        event = data.get("event", "")
        if event == "connected":
            self.state = {"agent": data.get("agent", {}), "nearby": [], "pending_messages": [], "connected": True}
            self._initial_state_event.set()
            # Write initial TOWN_STATUS.md
            agent = data.get("agent", {})
            location = agent.get("location", "unknown")
            activity = agent.get("activity", "idle")
            self._write_status(
                "# GooseTown Status\n\n"
                f"**Location:** {location}\n"
                f"**Activity:** {activity}\n\n"
                "**Nearby:** no one\n\n"
                "**Pending messages:** None\n"
            )
        elif event == "state_update":
            if "agent" in data:
                self.state["agent"] = data["agent"]
            if "nearby" in data:
                self.state["nearby"] = data["nearby"]
        elif event in ("conversation_invite", "conversation_message"):
            self.state.setdefault("pending_messages", []).append(data)
        elif event == "conversation_ended":
            self.state.pop("active_conversation", None)
        elif event == "arrived":
            if "agent" in self.state:
                self.state["agent"]["activity"] = "idle"
                if "location" in data:
                    self.state["agent"]["location"] = data["location"]
            self._arrived_event.set()
        elif event == "act_ok":
            pass  # Action acknowledged
        elif event == "wake":
            logger.info("Wake alarm fired, triggering agent")
            message = data.get("message", "You just woke up in GooseTown. What do you want to do?")
            asyncio.create_task(self._think(f"[GooseTown Wake]\n{message}"))
        elif event == "sleep_ok":
            self.running = False
        elif event == "error":
            logger.warning(f"Server error: {data.get('message', 'unknown')}")
        self._write_state()

    async def connect_ws(self):
        """Connect to GooseTown WebSocket."""
        try:
            import websockets
        except ImportError:
            logger.error("websockets package not installed. Install with: pip install websockets")
            sys.exit(1)

        url = f"{WS_URL}?token={TOKEN}"
        logger.info(f"Connecting to {WS_URL}...")

        try:
            self.ws = await websockets.connect(url, ping_interval=30, ping_timeout=10)
        except Exception as e:
            logger.error(f"WebSocket connection failed: {e}")
            raise

        # Send connect message
        await self.ws.send(
            json.dumps(
                {
                    "type": "town_agent_connect",
                    "token": TOKEN,
                    "agent_name": AGENT_NAME,
                }
            )
        )
        logger.info(f"Connected as {AGENT_NAME}")

    async def _think(self, prompt: str):
        if not self._gateway or not self._gateway.ws:
            return
        self._thinking = True
        try:
            result = await self._gateway.send_agent_message(
                f"[GooseTown]\n{prompt}",
                thinking="low",
            )
            if not result.get("ok"):
                logger.warning(f"Think failed: {result.get('error', 'unknown')}")
        except Exception as e:
            logger.warning(f"Think error: {e}")
        finally:
            self._thinking = False

    def _handle_world_update(self, data: dict):
        """Handle world_update message — write context summary to workspace."""
        if "you" in data:
            self.state["agent"] = data["you"]
        if "nearby_agents" in data:
            self.state["nearby"] = data["nearby_agents"]
        self._write_state()

        summary = data.get("context_summary")
        if summary:
            self._write_status(summary)

        if data.get("think") and not self._thinking:
            prompt = (
                summary
                + "\n\nDecide what to do next. You can: move to another location, chat with someone nearby, do an activity here, or go to sleep if you're tired."
            )
            asyncio.create_task(self._think(prompt))

    async def listen_ws(self):
        """Listen for events from GooseTown."""
        try:
            async for raw in self.ws:
                try:
                    data = json.loads(raw)
                    msg_type = data.get("type", "")
                    if msg_type == "town_event":
                        self._handle_event(data)
                    elif msg_type == "world_update":
                        self._handle_world_update(data)
                except json.JSONDecodeError:
                    logger.warning(f"Invalid JSON from server: {raw[:100]}")
        except Exception as e:
            logger.warning(f"WebSocket disconnected: {e}")
            self.running = False

    async def handle_tool_command(self, cmd: dict) -> dict:
        """Process a command from a tool via Unix socket."""
        action = cmd.get("action", "")

        if action == "check":
            return self.state

        elif action == "act":
            payload = cmd.get("payload", {})
            if not self.ws:
                return {"error": "not connected"}
            await self.ws.send(json.dumps({"type": "town_agent_act", **payload}))
            # Block on move until arrived (max 120s)
            if payload.get("action") == "move":
                self._arrived_event.clear()
                try:
                    await asyncio.wait_for(self._arrived_event.wait(), timeout=120.0)
                except asyncio.TimeoutError:
                    return {"status": "timeout", "action": "move", "message": "Did not arrive within 120s"}
                return {"status": "arrived", "location": self.state.get("agent", {}).get("location")}
            return {"status": "ok", "action": payload.get("action")}

        elif action == "sleep":
            wake_time = cmd.get("wake_time", "")
            tz = cmd.get("timezone", "UTC")
            if self.ws:
                await self.ws.send(
                    json.dumps(
                        {
                            "type": "town_agent_sleep",
                            "wake_time": wake_time,
                            "timezone": tz,
                        }
                    )
                )
            # Write alarm file
            ALARM_FILE.write_text(json.dumps({"wake_time": wake_time, "timezone": tz}))
            # Write sleeping TOWN_STATUS.md
            self._write_status(
                "# GooseTown Status\n\n"
                f"You are sleeping. Wake alarm: {wake_time} {tz}.\n"
                "To wake up early: run town_connect\n"
            )
            self.running = False
            return {"status": "sleeping", "wake_time": wake_time, "timezone": tz}

        return {"error": f"unknown action: {action}"}

    async def _handle_socket_client(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter):
        """Handle a single tool connection on the Unix socket."""
        try:
            data = await asyncio.wait_for(reader.read(8192), timeout=5.0)
            if not data:
                return
            cmd = json.loads(data.decode())
            result = await self.handle_tool_command(cmd)
            writer.write(json.dumps(result).encode())
            await writer.drain()
        except Exception as e:
            try:
                writer.write(json.dumps({"error": str(e)}).encode())
                await writer.drain()
            except Exception:
                pass
        finally:
            writer.close()
            try:
                await writer.wait_closed()
            except Exception:
                pass

    async def run_socket_server(self):
        """Listen for tool commands on Unix domain socket."""
        sock_path = str(SOCK_PATH)
        if os.path.exists(sock_path):
            os.unlink(sock_path)

        server = await asyncio.start_unix_server(self._handle_socket_client, sock_path)
        logger.info(f"Unix socket listening at {sock_path}")

        async with server:
            while self.running:
                await asyncio.sleep(0.2)

        # Cleanup
        server.close()
        await server.wait_closed()
        if os.path.exists(sock_path):
            os.unlink(sock_path)

    async def run(self):
        """Main entry point."""
        STATE_DIR.mkdir(parents=True, exist_ok=True)
        PID_FILE.write_text(str(os.getpid()))

        try:
            await self.connect_ws()

            # Wait for initial state
            try:
                await asyncio.wait_for(self._initial_state_event.wait(), timeout=10.0)
            except asyncio.TimeoutError:
                logger.error("Timeout waiting for initial state")
                return

            # Print initial state to stdout (captured by town_connect.sh)
            print(json.dumps(self.state))
            sys.stdout.flush()

            # Connect to local OpenClaw Gateway RPC
            self._gateway = GatewayRPC()
            try:
                await self._gateway.connect()
            except Exception as e:
                logger.warning(f"Could not connect to local OpenClaw gateway: {e}")
                self._gateway = None

            # Run WS listener and socket server concurrently
            tasks = [self.listen_ws(), self.run_socket_server()]
            if self._gateway:
                tasks.append(self._gateway.listen())
            await asyncio.gather(*tasks)
        finally:
            if self.ws:
                await self.ws.close()
            if self._gateway:
                await self._gateway.close()
            PID_FILE.unlink(missing_ok=True)
            logger.info("Daemon stopped")


def main():
    if not WS_URL or not TOKEN or not AGENT_NAME:
        print(json.dumps({"error": "Missing TOWN_WS_URL, TOWN_TOKEN, or TOWN_AGENT"}))
        sys.exit(1)

    daemon = TownDaemon()

    def shutdown(sig, frame):
        daemon.running = False

    signal.signal(signal.SIGTERM, shutdown)
    signal.signal(signal.SIGINT, shutdown)

    async def run_forever():
        backoff = 5
        while daemon.running:
            try:
                await daemon.run()
                break  # clean exit (agent slept)
            except Exception as e:
                logger.error(f"Daemon crashed: {e}, restarting in {backoff}s")
                await asyncio.sleep(backoff)
                backoff = min(backoff * 2, 60)
            else:
                backoff = 5  # reset after successful reconnect

    asyncio.run(run_forever())


if __name__ == "__main__":
    main()
