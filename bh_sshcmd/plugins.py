"""Output-parsing plugin system.

Built-in parsers turn common command output into structured dicts (handy for
--json fleet reports). Users can add their own by dropping a .py file into a
plugins directory; each file just needs a module-level `register()` function
that returns {command_prefix: parser_fn}.
"""

from __future__ import annotations

import importlib.util
import os
import re
from typing import Callable, Optional

ParserFn = Callable[[str], dict]

_REGISTRY: dict[str, ParserFn] = {}


def parser(command_prefix: str):
    """Decorator to register a built-in parser under a command prefix."""
    def wrap(fn: ParserFn) -> ParserFn:
        _REGISTRY[command_prefix] = fn
        return fn
    return wrap


@parser("id")
def parse_id(output: str) -> dict:
    m = re.match(r"uid=(\d+)\((\S+)\)\s+gid=(\d+)\((\S+)\)\s+groups=(.+)", output.strip())
    if not m:
        return {"raw": output}
    return {
        "uid": int(m.group(1)),
        "user": m.group(2),
        "gid": int(m.group(3)),
        "group": m.group(4),
        "groups": m.group(5),
    }


@parser("uname")
def parse_uname(output: str) -> dict:
    fields = output.strip().split()
    labels = ["kernel_name", "hostname", "kernel_release", "kernel_version", "machine"]
    return dict(zip(labels, fields)) or {"raw": output}


@parser("df")
def parse_df(output: str) -> dict:
    lines = output.strip().splitlines()
    if len(lines) < 2:
        return {"raw": output}
    header = lines[0].split()
    rows = [dict(zip(header, line.split(maxsplit=len(header) - 1))) for line in lines[1:]]
    return {"filesystems": rows}


@parser("ss")
def parse_ss(output: str) -> dict:
    lines = output.strip().splitlines()
    if len(lines) < 2:
        return {"raw": output}
    header = lines[0].split()
    rows = [dict(zip(header, line.split(maxsplit=len(header) - 1))) for line in lines[1:]]
    return {"sockets": rows}


def get_parser(command: str) -> Optional[ParserFn]:
    prefix = command.strip().split()[0] if command.strip() else ""
    return _REGISTRY.get(prefix)


def parse_output(command: str, output: str) -> dict:
    fn = get_parser(command)
    if fn is None:
        return {"raw": output}
    try:
        return fn(output)
    except Exception:  # noqa: BLE001 - never let a parser crash the run
        return {"raw": output}


def load_plugin_dir(directory: str) -> int:
    """Load user plugins from a directory. Each .py file must expose register()
    returning {command_prefix: parser_fn}. Returns count of prefixes loaded."""
    if not os.path.isdir(directory):
        return 0
    loaded = 0
    for fname in os.listdir(directory):
        if not fname.endswith(".py"):
            continue
        path = os.path.join(directory, fname)
        spec = importlib.util.spec_from_file_location(f"bh_sshcmd_plugin_{fname[:-3]}", path)
        if spec is None or spec.loader is None:
            continue
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        if hasattr(module, "register"):
            for prefix, fn in module.register().items():
                _REGISTRY[prefix] = fn
                loaded += 1
    return loaded
