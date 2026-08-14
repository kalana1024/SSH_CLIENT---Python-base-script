"""Optional live TUI dashboard for fleet runs, built on `textual`.

Falls back gracefully (raises ImportError with a helpful message) if textual
isn't installed - the CLI catches this and drops back to the plain progress
bar / table output.
"""

from __future__ import annotations

from typing import Optional

from .config import InventoryHost
from .core import CommandResult

try:
    from textual.app import App, ComposeResult
    from textual.widgets import DataTable, Footer, Header
    HAVE_TEXTUAL = True
except ImportError:  # pragma: no cover - optional dependency
    HAVE_TEXTUAL = False


def run_fleet_tui(
    hosts: list[InventoryHost],
    command_template: str,
    fleet_kwargs: dict,
) -> list[CommandResult]:
    """Launch a live-updating table of fleet run status. Returns the final
    results once the run completes (or the app is quit)."""
    if not HAVE_TEXTUAL:
        raise ImportError("textual is not installed; run `pip install textual` for --tui, "
                           "or drop --tui to use the plain table output.")

    from . import fleet as fleet_mod

    class FleetDashboard(App):
        BINDINGS = [("q", "quit", "Quit")]
        CSS = """
        DataTable { height: 1fr; }
        """

        def __init__(self) -> None:
            super().__init__()
            self.results: list[Optional[CommandResult]] = [None] * len(hosts)
            self.row_keys = []
            self.col_keys = []

        def compose(self) -> ComposeResult:
            yield Header(show_clock=True)
            yield DataTable(id="table")
            yield Footer()

        def on_mount(self) -> None:
            table = self.query_one("#table", DataTable)
            self.col_keys = table.add_columns("Host", "Status", "Exit", "Duration", "Output")
            for h in hosts:
                label = h.alias or h.host
                key = table.add_row(label, "pending", "-", "-", "")
                self.row_keys.append(key)
            self.run_worker(self._run_fleet, thread=True)

        def _run_fleet(self) -> None:
            results = fleet_mod.run_fleet(
                hosts, command_template,
                on_result=lambda r: self._safe_update(r),
                **fleet_kwargs,
            )
            self.results = results
            self.call_from_thread(self.exit, results)

        def _safe_update(self, result: CommandResult) -> None:
            for i, h in enumerate(hosts):
                label = h.alias or h.host
                if label == result.host and self.results[i] is None:
                    self.call_from_thread(self._update_row, i, result)
                    self.results[i] = result
                    break

        def _update_row(self, idx: int, result: CommandResult) -> None:
            table = self.query_one("#table", DataTable)
            status = "OK" if result.ok else "FAIL"
            snippet = (result.stdout or result.error or "").strip().replace("\n", " ")[:40]
            row_key = self.row_keys[idx]
            _, status_col, exit_col, dur_col, out_col = self.col_keys
            table.update_cell(row_key, status_col, status)
            table.update_cell(row_key, exit_col, str(result.exit_code))
            table.update_cell(row_key, dur_col, f"{result.duration:.2f}s")
            table.update_cell(row_key, out_col, snippet)

    app = FleetDashboard()
    final = app.run()
    return final if isinstance(final, list) else [r for r in app.results if r is not None]
