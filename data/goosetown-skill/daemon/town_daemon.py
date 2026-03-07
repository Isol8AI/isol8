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


class TownDaemon:
    def __init__(self):
        self.state: dict = {}
        self.running = True
        self.ws = None
        self._initial_state_event = asyncio.Event()
        self._arrived_event = asyncio.Event()

    def _write_state(self):
        STATE_DIR.mkdir(parents=True, exist_ok=True)
        STATE_FILE.write_text(json.dumps(self.state, indent=2))

    def _handle_event(self, data: dict):
        event = data.get("event", "")
        if event == "connected":
            self.state = {"agent": data.get("agent", {}), "nearby": [], "pending_messages": [], "connected": True}
            self._initial_state_event.set()
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

    async def listen_ws(self):
        """Listen for events from GooseTown."""
        try:
            async for raw in self.ws:
                try:
                    data = json.loads(raw)
                    if data.get("type") == "town_event":
                        self._handle_event(data)
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

            # Run WS listener and socket server concurrently
            await asyncio.gather(
                self.listen_ws(),
                self.run_socket_server(),
            )
        finally:
            if self.ws:
                await self.ws.close()
            PID_FILE.unlink(missing_ok=True)
            logger.info("Daemon stopped")


def main():
    if not WS_URL or not TOKEN or not AGENT_NAME:
        print(json.dumps({"error": "Missing TOWN_WS_URL, TOWN_TOKEN, or TOWN_AGENT"}))
        sys.exit(1)

    daemon = TownDaemon()

    # Handle shutdown signals gracefully
    def shutdown(sig, frame):
        daemon.running = False

    signal.signal(signal.SIGTERM, shutdown)
    signal.signal(signal.SIGINT, shutdown)

    asyncio.run(daemon.run())


if __name__ == "__main__":
    main()
