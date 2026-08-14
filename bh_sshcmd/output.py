"""Formatted output: colorized when `rich` is installed, plain text otherwise,
plus a --json mode for piping into other tools."""

from __future__ import annotations

import json
from dataclasses import asdict
from typing import Iterable

from .core import CommandResult

try:
    from rich.console import Console
    from rich.table import Table
    from rich.text import Text
    HAVE_RICH = True
    _console = Console()
except ImportError:  # pragma: no cover - optional dependency
    HAVE_RICH = False
    _console = None


def print_result(result: CommandResult, verbose: bool = False) -> None:
    if HAVE_RICH:
        status = Text("OK", style="bold green") if result.ok else Text("FAIL", style="bold red")
        _console.print(f"[bold]{result.host}[/bold]  {status}  ({result.duration:.2f}s)")
        if result.error:
            _console.print(f"  [red]error:[/red] {result.error}")
        if result.stdout:
            _console.print(result.stdout.rstrip())
        if result.stderr:
            _console.print(f"[yellow]{result.stderr.rstrip()}[/yellow]")
    else:
        status = "OK" if result.ok else "FAIL"
        print(f"{result.host}  {status}  ({result.duration:.2f}s)")
        if result.error:
            print(f"  error: {result.error}")
        if result.stdout:
            print(result.stdout.rstrip())
        if result.stderr:
            print(result.stderr.rstrip())


def print_fleet_table(results: Iterable[CommandResult]) -> None:
    results = list(results)
    if HAVE_RICH:
        table = Table(title="Fleet run results")
        table.add_column("Host")
        table.add_column("Status")
        table.add_column("Exit")
        table.add_column("Duration")
        table.add_column("Output (truncated)")
        for r in results:
            status = "[green]OK[/green]" if r.ok else "[red]FAIL[/red]"
            snippet = (r.stdout or r.error or "").strip().replace("\n", " ")[:60]
            table.add_row(r.host, status, str(r.exit_code), f"{r.duration:.2f}s", snippet)
        _console.print(table)
    else:
        print(f"{'HOST':<20}{'STATUS':<8}{'EXIT':<6}{'TIME':<8}OUTPUT")
        for r in results:
            status = "OK" if r.ok else "FAIL"
            snippet = (r.stdout or r.error or "").strip().replace("\n", " ")[:60]
            print(f"{r.host:<20}{status:<8}{str(r.exit_code):<6}{r.duration:<8.2f}{snippet}")


def to_json(results: Iterable[CommandResult]) -> str:
    return json.dumps([asdict(r) for r in results], indent=2)


def print_diff_groups(results: Iterable[CommandResult]) -> None:
    """Group hosts by identical stdout, to spot config drift across a fleet."""
    results = list(results)
    groups: dict[str, list[str]] = {}
    for r in results:
        key = r.stdout.strip()
        groups.setdefault(key, []).append(r.host)

    if HAVE_RICH:
        _console.print(f"[bold]{len(groups)}[/bold] distinct output group(s) across {len(results)} host(s)")
        for i, (output, hosts) in enumerate(sorted(groups.items(), key=lambda kv: -len(kv[1])), 1):
            _console.print(f"\n[bold cyan]Group {i}[/bold cyan] ({len(hosts)} host(s)): {', '.join(hosts)}")
            _console.print(output if output else "[dim](empty output)[/dim]")
    else:
        print(f"{len(groups)} distinct output group(s) across {len(results)} host(s)")
        for i, (output, hosts) in enumerate(sorted(groups.items(), key=lambda kv: -len(kv[1])), 1):
            print(f"\nGroup {i} ({len(hosts)} host(s)): {', '.join(hosts)}")
            print(output if output else "(empty output)")


def make_progress():
    """Return a rich Progress context manager, or a no-op stand-in."""
    if HAVE_RICH:
        from rich.progress import Progress
        return Progress()

    class _NoOpProgress:
        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

        def add_task(self, *a, **kw):
            return None

        def update(self, *a, **kw):
            pass

        def advance(self, *a, **kw):
            pass

    return _NoOpProgress()
