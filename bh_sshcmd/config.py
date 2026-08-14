"""Profile storage and host-inventory loading.

Profiles live in ~/.bh_sshcmd/config.yaml (or config.json if PyYAML isn't
installed) and let you save a host's connection details under a short alias
instead of retyping flags every run.

Inventories (for fleet mode) are plain text/CSV/YAML lists of hosts.
"""

from __future__ import annotations

import csv
import json
import os
from dataclasses import asdict, dataclass
from typing import Optional

try:
    import yaml
    HAVE_YAML = True
except ImportError:  # pragma: no cover - optional dependency
    HAVE_YAML = False

CONFIG_DIR = os.path.expanduser("~/.bh_sshcmd")
CONFIG_FILE_YAML = os.path.join(CONFIG_DIR, "config.yaml")
CONFIG_FILE_JSON = os.path.join(CONFIG_DIR, "config.json")


@dataclass
class HostProfile:
    name: str
    host: str
    user: str
    port: int = 22
    key_file: Optional[str] = None
    jump_host: Optional[str] = None
    host_key_policy: str = "auto"
    # Passwords are intentionally NOT stored here in plaintext by default;
    # use --save-password to opt in, since anyone reading this file could
    # otherwise read the credential.
    password: Optional[str] = None


def _config_path() -> str:
    return CONFIG_FILE_YAML if HAVE_YAML else CONFIG_FILE_JSON


def load_profiles() -> dict[str, HostProfile]:
    path = _config_path()
    if not os.path.exists(path):
        return {}
    with open(path, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f) if HAVE_YAML else json.load(f)
    data = data or {}
    return {name: HostProfile(name=name, **fields) for name, fields in data.get("profiles", {}).items()}


def save_profiles(profiles: dict[str, HostProfile]) -> None:
    os.makedirs(CONFIG_DIR, exist_ok=True)
    payload = {
        "profiles": {
            name: {k: v for k, v in asdict(p).items() if k != "name"}
            for name, p in profiles.items()
        }
    }
    path = _config_path()
    with open(path, "w", encoding="utf-8") as f:
        if HAVE_YAML:
            yaml.safe_dump(payload, f, sort_keys=False)
        else:
            json.dump(payload, f, indent=2)


def add_profile(profile: HostProfile) -> None:
    profiles = load_profiles()
    profiles[profile.name] = profile
    save_profiles(profiles)


def remove_profile(name: str) -> bool:
    profiles = load_profiles()
    if name not in profiles:
        return False
    del profiles[name]
    save_profiles(profiles)
    return True


def get_profile(name: str) -> Optional[HostProfile]:
    return load_profiles().get(name)


# --- Fleet inventory loading -------------------------------------------------

@dataclass
class InventoryHost:
    host: str
    user: str
    port: int = 22
    key_file: Optional[str] = None
    password: Optional[str] = None
    alias: Optional[str] = None


def load_inventory(path: str) -> list[InventoryHost]:
    """Load a fleet inventory from YAML, CSV, or a plain host-list text file.

    YAML: a list of dicts with host/user/port/key_file/alias keys.
    CSV:  header row host,user,port,key_file,alias (port/key_file/alias optional).
    Plain text: one `user@host[:port]` per line, '#' comments allowed.
    """
    ext = os.path.splitext(path)[1].lower()
    with open(path, "r", encoding="utf-8") as f:
        content = f.read()

    if ext in (".yaml", ".yml") and HAVE_YAML:
        rows = yaml.safe_load(content) or []
        return [InventoryHost(**row) for row in rows]

    if ext == ".csv":
        hosts = []
        reader = csv.DictReader(content.splitlines())
        for row in reader:
            row = {k: v for k, v in row.items() if v}
            if "port" in row:
                row["port"] = int(row["port"])
            hosts.append(InventoryHost(**row))
        return hosts

    # Plain text: user@host[:port] per line
    hosts = []
    for line in content.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        user, hostport = (line.split("@", 1) if "@" in line else (None, line))
        if ":" in hostport:
            host, port = hostport.split(":", 1)
            port = int(port)
        else:
            host, port = hostport, 22
        hosts.append(InventoryHost(host=host, user=user or "root", port=port))
    return hosts
