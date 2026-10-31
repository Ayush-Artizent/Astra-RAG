"""A real MCP client: spawns `astra-mcp` and speaks JSON-RPC over its stdin and stdout.

The demo page is a client, not a second caller of the planes. That is the whole point of it: what the
page shows is what DevX's agent will see, including the merged tool list, the hidden `project_id` and
the note that arrives in front of a payload.

One child process, started on demand and restartable. Replies are read on a background thread so a
server that stops answering times out instead of hanging the page.
"""
import json
import queue
import subprocess
import sys
import threading

PROTOCOL_VERSION = "2025-06-18"
START_COMMAND = [sys.executable, "-c", "from astra_mcp import main; main()"]


class SessionError(Exception):
    """The session could not be started or did not answer. The message is safe to show."""


class McpSession:
    def __init__(self, env: dict, command: list[str] | None = None, timeout: float = 30.0):
        self._env = env
        self._command = command or START_COMMAND
        self._timeout = timeout
        self._lock = threading.Lock()
        self._proc: subprocess.Popen | None = None
        self._replies: queue.Queue = queue.Queue()
        self._last_id = 0
        self.server_info: dict = {}
        self.instructions: str = ""
        self.start_error: str = ""

    # -- lifecycle -------------------------------------------------------

    def running(self) -> bool:
        return self._proc is not None and self._proc.poll() is None

    def start(self) -> None:
        """Spawn the server and complete the handshake. Safe to call when already running."""
        with self._lock:
            if self.running():
                return
            self.start_error = ""
            try:
                self._proc = subprocess.Popen(
                    self._command, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                    stderr=subprocess.DEVNULL, text=True, encoding="utf-8", env=self._env,
                )
            except OSError as exc:
                self.start_error = f"Could not start the MCP server ({type(exc).__name__})."
                raise SessionError(self.start_error) from None
            self._replies = queue.Queue()
            threading.Thread(target=self._read, args=(self._proc,), daemon=True).start()
            try:
                reply = self._request_locked("initialize", {
                    "protocolVersion": PROTOCOL_VERSION, "capabilities": {},
                    "clientInfo": {"name": "astra-demo", "version": "0"},
                })
            except SessionError as exc:
                # A configuration problem makes the server exit 2 before answering.
                self.start_error = str(exc)
                self._stop_locked()
                raise
            self.server_info = reply.get("serverInfo") or {}
            self.instructions = reply.get("instructions") or ""
            self._send({"jsonrpc": "2.0", "method": "notifications/initialized"})

    def stop(self) -> None:
        with self._lock:
            self._stop_locked()

    def restart(self) -> None:
        self.stop()
        self.start()

    def _stop_locked(self) -> None:
        proc, self._proc = self._proc, None
        if proc is None:
            return
        try:
            if proc.poll() is None and proc.stdin:
                proc.stdin.close()
            proc.wait(timeout=5)
        except (subprocess.TimeoutExpired, OSError):
            proc.kill()
        finally:
            for stream in (proc.stdin, proc.stdout):
                if stream and not stream.closed:
                    stream.close()

    # -- protocol --------------------------------------------------------

    def list_tools(self) -> list[dict]:
        return self.request("tools/list").get("tools") or []

    def call_tool(self, name: str, arguments: dict) -> dict:
        return self.request("tools/call", {"name": name, "arguments": arguments})

    def request(self, method: str, params: dict | None = None) -> dict:
        if not self.running():
            self.start()
        with self._lock:
            return self._request_locked(method, params)

    def _request_locked(self, method: str, params: dict | None) -> dict:
        self._last_id += 1
        message_id = self._last_id
        message = {"jsonrpc": "2.0", "id": message_id, "method": method}
        if params is not None:
            message["params"] = params
        self._send(message)
        reply = self._await(message_id)
        if "error" in reply:
            error = reply["error"] or {}
            raise SessionError(str(error.get("message") or "The MCP server returned an error."))
        return reply.get("result") or {}

    def _send(self, message: dict) -> None:
        proc = self._proc
        if proc is None or proc.stdin is None or proc.poll() is not None:
            raise SessionError("The MCP server is not running.")
        try:
            print(json.dumps(message), file=proc.stdin, flush=True)
        except (OSError, ValueError):
            raise SessionError("The MCP server stopped accepting requests.") from None

    def _await(self, message_id: int) -> dict:
        """Wait for this id. Anything else on the queue is a notification and is dropped."""
        while True:
            try:
                reply = self._replies.get(timeout=self._timeout)
            except queue.Empty:
                raise SessionError(f"The MCP server did not answer within {self._timeout:.0f}s.") from None
            if reply is None:
                raise SessionError("The MCP server closed the connection.")
            if reply.get("id") == message_id:
                return reply

    def _read(self, proc: subprocess.Popen) -> None:
        for line in proc.stdout:
            line = line.strip()
            if not line:
                continue
            try:
                self._replies.put(json.loads(line))
            except ValueError:
                continue  # not JSON-RPC; the server never writes anything else to stdout
        self._replies.put(None)  # the process ended: unblock whoever is waiting
