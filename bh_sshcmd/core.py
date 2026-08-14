"""Core SSH connection/execution engine.

Wraps Paramiko with: ~/.ssh/config resolution, SSH-agent auth, jump-host
(ProxyJump) chaining, pluggable host-key policies, retry/backoff, streaming
command execution, and interactive PTY shells.
"""

from __future__ import annotations

import logging
import os
import socket
import time
from dataclasses import dataclass
from typing import Callable, Optional

import paramiko

logger = logging.getLogger("bh_sshcmd.core")

HOST_KEY_POLICIES = {
    # Silently trust and store unknown host keys. Convenient, but exposes
    # you to MITM on first connect - opt in explicitly, never the default
    # for anything touching production.
    "auto": paramiko.AutoAddPolicy,
    # Trust unknown host keys but log a loud warning (paramiko's own policy).
    "warn": paramiko.WarningPolicy,
    # Refuse to connect to any host not already in known_hosts.
    "reject": paramiko.RejectPolicy,
}


@dataclass
class ConnectionSpec:
    host: str
    user: str
    password: Optional[str] = None
    key_file: Optional[str] = None
    port: int = 22
    timeout: float = 10.0
    use_agent: bool = True
    use_ssh_config: bool = True
    ssh_config_path: Optional[str] = None
    jump_host: Optional[str] = None  # "user@host[:port]"
    host_key_policy: str = "auto"
    retries: int = 0
    retry_backoff: float = 2.0
    passphrase: Optional[str] = None


@dataclass
class CommandResult:
    host: str
    command: str
    stdout: str = ""
    stderr: str = ""
    exit_code: Optional[int] = None
    error: Optional[str] = None
    duration: float = 0.0

    @property
    def ok(self) -> bool:
        return self.error is None and self.exit_code == 0


def _resolve_with_ssh_config(spec: ConnectionSpec) -> dict:
    """Merge ~/.ssh/config (or a custom path) settings into the connection spec."""
    cfg_path = spec.ssh_config_path or os.path.expanduser("~/.ssh/config")
    resolved = {
        "hostname": spec.host,
        "port": spec.port,
        "username": spec.user,
        "key_filename": spec.key_file,
    }
    if not spec.use_ssh_config or not os.path.exists(cfg_path):
        return resolved

    config = paramiko.SSHConfig()
    with open(cfg_path) as f:
        config.parse(f)
    host_cfg = config.lookup(spec.host)

    resolved["hostname"] = host_cfg.get("hostname", spec.host)
    if "port" in host_cfg and spec.port == 22:
        resolved["port"] = int(host_cfg["port"])
    if "user" in host_cfg and spec.user is None:
        resolved["username"] = host_cfg["user"]
    if "identityfile" in host_cfg and not spec.key_file:
        identities = host_cfg["identityfile"]
        resolved["key_filename"] = identities[0] if isinstance(identities, list) else identities
    if "proxyjump" in host_cfg and not spec.jump_host:
        spec.jump_host = host_cfg["proxyjump"]
    return resolved


def _parse_jump_spec(jump_spec: str) -> tuple[str, str, int]:
    user = None
    hostport = jump_spec
    if "@" in jump_spec:
        user, hostport = jump_spec.split("@", 1)
    if ":" in hostport:
        host, port = hostport.split(":", 1)
        port = int(port)
    else:
        host, port = hostport, 22
    return user, host, port


class SSHSession:
    """A single managed SSH connection, with retry, jump-host, and agent support."""

    def __init__(self, spec: ConnectionSpec):
        self.spec = spec
        self.client: Optional[paramiko.SSHClient] = None
        self._jump_transport: Optional[paramiko.Transport] = None
        self._sock = None

    def connect(self) -> None:
        resolved = _resolve_with_ssh_config(self.spec)
        policy_cls = HOST_KEY_POLICIES.get(self.spec.host_key_policy, paramiko.AutoAddPolicy)
        if self.spec.host_key_policy == "auto":
            logger.warning(
                "Host key policy 'auto' trusts unknown host keys automatically "
                "(MITM risk). Use --host-key-policy reject|warn for safer runs."
            )

        attempt = 0
        last_exc: Optional[Exception] = None
        while attempt <= self.spec.retries:
            try:
                self._connect_once(resolved, policy_cls)
                return
            except Exception as exc:  # noqa: BLE001 - surfaced to caller via retries
                last_exc = exc
                attempt += 1
                if attempt <= self.spec.retries:
                    wait = self.spec.retry_backoff * (2 ** (attempt - 1))
                    logger.warning(
                        "Connection attempt %d/%d to %s failed (%s); retrying in %.1fs",
                        attempt, self.spec.retries, self.spec.host, exc, wait,
                    )
                    time.sleep(wait)
        assert last_exc is not None
        raise last_exc

    def _connect_once(self, resolved: dict, policy_cls) -> None:
        sock = None
        if self.spec.jump_host:
            sock = self._open_jump_channel(resolved["hostname"], resolved["port"])

        client = paramiko.SSHClient()
        client.set_missing_host_key_policy(policy_cls())

        client.connect(
            hostname=resolved["hostname"],
            port=resolved["port"],
            username=resolved["username"] or self.spec.user,
            password=self.spec.password,
            key_filename=resolved["key_filename"],
            passphrase=self.spec.passphrase,
            timeout=self.spec.timeout,
            allow_agent=self.spec.use_agent,
            look_for_keys=self.spec.use_agent,
            sock=sock,
        )
        self.client = client

    def _open_jump_channel(self, dest_host: str, dest_port: int):
        j_user, j_host, j_port = _parse_jump_spec(self.spec.jump_host)
        jump_client = paramiko.SSHClient()
        jump_client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        jump_client.connect(
            hostname=j_host,
            port=j_port,
            username=j_user or self.spec.user,
            password=self.spec.password,
            key_filename=self.spec.key_file,
            timeout=self.spec.timeout,
            allow_agent=self.spec.use_agent,
            look_for_keys=self.spec.use_agent,
        )
        self._jump_transport = jump_client.get_transport()
        channel = self._jump_transport.open_channel(
            "direct-tcpip",
            (dest_host, dest_port),
            ("127.0.0.1", 0),
        )
        return channel

    def exec_command(
        self,
        command: str,
        timeout: Optional[float] = None,
        stream_callback: Optional[Callable[[str, str], None]] = None,
    ) -> CommandResult:
        """Run a command. If stream_callback is given, it's invoked with
        ('stdout'|'stderr', chunk) as output arrives, in addition to the
        full result being returned at the end."""
        assert self.client is not None, "call connect() first"
        start = time.time()
        result = CommandResult(host=self.spec.host, command=command)
        try:
            stdin, stdout, stderr = self.client.exec_command(
                command, timeout=timeout or self.spec.timeout
            )
            stdin.close()

            if stream_callback:
                out_chunks, err_chunks = [], []
                channel = stdout.channel
                while not channel.exit_status_ready() or channel.recv_ready() or channel.recv_stderr_ready():
                    if channel.recv_ready():
                        chunk = channel.recv(4096).decode("utf-8", errors="replace")
                        out_chunks.append(chunk)
                        stream_callback("stdout", chunk)
                    if channel.recv_stderr_ready():
                        chunk = channel.recv_stderr(4096).decode("utf-8", errors="replace")
                        err_chunks.append(chunk)
                        stream_callback("stderr", chunk)
                    if not channel.recv_ready() and not channel.recv_stderr_ready():
                        time.sleep(0.05)
                # drain anything left after exit_status_ready flipped true
                while channel.recv_ready():
                    chunk = channel.recv(4096).decode("utf-8", errors="replace")
                    out_chunks.append(chunk)
                    stream_callback("stdout", chunk)
                while channel.recv_stderr_ready():
                    chunk = channel.recv_stderr(4096).decode("utf-8", errors="replace")
                    err_chunks.append(chunk)
                    stream_callback("stderr", chunk)
                result.stdout = "".join(out_chunks)
                result.stderr = "".join(err_chunks)
                result.exit_code = channel.recv_exit_status()
            else:
                result.stdout = stdout.read().decode("utf-8", errors="replace")
                result.stderr = stderr.read().decode("utf-8", errors="replace")
                result.exit_code = stdout.channel.recv_exit_status()

        except Exception as exc:  # noqa: BLE001
            result.error = str(exc)
            logger.error("Command failed on %s: %s", self.spec.host, exc)
        finally:
            result.duration = time.time() - start
        return result

    def invoke_shell(self) -> "InteractiveShell":
        assert self.client is not None, "call connect() first"
        return InteractiveShell(self.client)

    def close(self) -> None:
        if self.client:
            self.client.close()
        if self._jump_transport:
            self._jump_transport.close()


class InteractiveShell:
    """Thin wrapper around an interactive PTY for a live terminal session."""

    def __init__(self, client: paramiko.SSHClient):
        self.channel = client.invoke_shell(term="xterm")

    def run(self) -> None:
        """Bridge local stdin/stdout to the remote PTY (blocking, terminal-based)."""
        import select
        import sys

        if os.name == "posix":
            import termios
            import tty

            old_tty = termios.tcgetattr(sys.stdin)
            try:
                tty.setraw(sys.stdin.fileno())
                self.channel.settimeout(0.0)
                while True:
                    r, _, _ = select.select([self.channel, sys.stdin], [], [])
                    if self.channel in r:
                        try:
                            data = self.channel.recv(4096)
                            if not data:
                                break
                            sys.stdout.write(data.decode("utf-8", errors="replace"))
                            sys.stdout.flush()
                        except socket.timeout:
                            pass
                    if sys.stdin in r:
                        char = sys.stdin.read(1)
                        if not char:
                            break
                        self.channel.send(char)
            finally:
                termios.tcsetattr(sys.stdin, termios.TCSADRAIN, old_tty)
        else:
            # Windows: no termios/tty/select-on-stdin support; fall back to a
            # simple line-oriented loop.
            import threading

            def reader():
                while True:
                    data = self.channel.recv(4096)
                    if not data:
                        break
                    sys.stdout.write(data.decode("utf-8", errors="replace"))
                    sys.stdout.flush()

            t = threading.Thread(target=reader, daemon=True)
            t.start()
            try:
                while True:
                    line = sys.stdin.readline()
                    if not line:
                        break
                    self.channel.send(line)
            except KeyboardInterrupt:
                pass

    def close(self) -> None:
        self.channel.close()
