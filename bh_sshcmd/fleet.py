"""Concurrent multi-host command execution ("fleet mode")."""

from __future__ import annotations

import logging
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Callable, Optional

from .config import InventoryHost
from .core import CommandResult, ConnectionSpec, SSHSession

logger = logging.getLogger("bh_sshcmd.fleet")


def render_command(template: str, inv_host: InventoryHost) -> str:
    """Substitute {hostname} / {user} / {alias} placeholders in a command template."""
    return template.format(
        hostname=inv_host.host,
        user=inv_host.user,
        alias=inv_host.alias or inv_host.host,
    )


def _run_one(
    inv_host: InventoryHost,
    command_template: str,
    default_key_file: Optional[str],
    default_password: Optional[str],
    timeout: float,
    host_key_policy: str,
    retries: int,
    dry_run: bool,
) -> CommandResult:
    label = inv_host.alias or inv_host.host
    command = render_command(command_template, inv_host)

    if dry_run:
        return CommandResult(host=label, command=command, stdout="(dry-run: not executed)", exit_code=0)

    spec = ConnectionSpec(
        host=inv_host.host,
        user=inv_host.user,
        password=inv_host.password or default_password,
        key_file=inv_host.key_file or default_key_file,
        port=inv_host.port,
        timeout=timeout,
        host_key_policy=host_key_policy,
        retries=retries,
    )
    session = SSHSession(spec)
    try:
        session.connect()
    except Exception as exc:  # noqa: BLE001
        logger.error("Connect failed for %s: %s", label, exc)
        return CommandResult(host=label, command=command, error=str(exc))

    try:
        result = session.exec_command(command)
        result.host = label
        return result
    finally:
        session.close()


def run_fleet(
    hosts: list[InventoryHost],
    command_template: str,
    max_workers: int = 10,
    default_key_file: Optional[str] = None,
    default_password: Optional[str] = None,
    timeout: float = 10.0,
    host_key_policy: str = "auto",
    retries: int = 0,
    dry_run: bool = False,
    on_result: Optional[Callable[[CommandResult], None]] = None,
) -> list[CommandResult]:
    """Run `command_template` against every host concurrently, returning results
    in host order (not completion order). `on_result` fires as each finishes,
    useful for live progress bars / TUI updates."""
    results: dict[int, CommandResult] = {}
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        future_to_idx = {
            executor.submit(
                _run_one, h, command_template, default_key_file, default_password,
                timeout, host_key_policy, retries, dry_run,
            ): i
            for i, h in enumerate(hosts)
        }
        for future in as_completed(future_to_idx):
            idx = future_to_idx[future]
            result = future.result()
            results[idx] = result
            if on_result:
                on_result(result)

    return [results[i] for i in range(len(hosts))]
