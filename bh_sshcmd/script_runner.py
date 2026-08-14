"""Playbook / script mode: run a sequence of commands against a host with
conditional branching on exit code, and simple variable registration.

Playbook format (YAML or JSON), a list of steps:

    - command: "uname -a"
      register: os_info
    - command: "systemctl restart nginx"
      on_failure: stop        # stop | continue (default: stop)
    - command: "echo {{os_info}}"

`{{varname}}` in a later command is replaced with the registered stdout
(stripped) of an earlier step.
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass
from typing import Optional

from .core import CommandResult, SSHSession

try:
    import yaml
    HAVE_YAML = True
except ImportError:  # pragma: no cover
    HAVE_YAML = False

logger = logging.getLogger("bh_sshcmd.script")

VAR_PATTERN = re.compile(r"\{\{(\w+)\}\}")


@dataclass
class Step:
    command: str
    register: Optional[str] = None
    on_failure: str = "stop"  # stop | continue
    description: Optional[str] = None


@dataclass
class StepOutcome:
    step: Step
    result: CommandResult
    skipped: bool = False


def load_playbook(path: str) -> list[Step]:
    with open(path, "r", encoding="utf-8") as f:
        content = f.read()
    if path.lower().endswith((".yaml", ".yml")) and HAVE_YAML:
        raw = yaml.safe_load(content)
    else:
        raw = json.loads(content)
    return [Step(**item) for item in raw]


def _substitute(command: str, variables: dict[str, str]) -> str:
    def repl(m: re.Match) -> str:
        key = m.group(1)
        return variables.get(key, m.group(0))
    return VAR_PATTERN.sub(repl, command)


def run_playbook(session: SSHSession, steps: list[Step]) -> list[StepOutcome]:
    variables: dict[str, str] = {}
    outcomes: list[StepOutcome] = []

    for step in steps:
        command = _substitute(step.command, variables)
        logger.info("Running step: %s", command)
        result = session.exec_command(command)
        outcomes.append(StepOutcome(step=step, result=result))

        if step.register:
            variables[step.register] = result.stdout.strip()

        if not result.ok and step.on_failure == "stop":
            logger.warning("Step failed, stopping playbook: %s", command)
            break

    return outcomes
