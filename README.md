<div align="center">

# 🔐 bh-sshcmd

**A fully-loaded SSH automation toolkit built on [Paramiko](https://www.paramiko.org/)**

[![Python](https://img.shields.io/badge/Python-3.9%2B-3776AB?style=for-the-badge&logo=python&logoColor=white)](https://python.org)
[![Paramiko](https://img.shields.io/badge/Powered%20by-Paramiko-4B8BBE?style=for-the-badge)](https://www.paramiko.org/)
[![License](https://img.shields.io/badge/License-MIT-22C55E?style=for-the-badge)](LICENSE)
[![Version](https://img.shields.io/badge/Version-2.0.0-F59E0B?style=for-the-badge)](pyproject.toml)

*From a single-host runner to a full fleet automation toolkit — six subcommands, zero SSH headaches.*

</div>

---

## 📖 Overview

`bh-sshcmd` started as a simple "run one command on one host" script and evolved into a small but powerful toolkit. It covers **single-host execution**, **concurrent fleet runs**, **interactive shells**, **SFTP transfers**, **multi-step playbooks**, and **saved connection profiles** — all from one unified CLI.

> **Optional enhancements:** `pyyaml` for YAML inventories/playbooks · `rich` for colorized output · `textual` for a live TUI dashboard.
> Everything degrades gracefully to plain text/JSON if they're not installed.

---

## ⚡ Quick Start

### Installation

```bash
# Clone the repo
git clone <your-repo-url>
cd bh_sshcmd

# Install core dependency
pip install -r requirements.txt

# Or install all optional extras at once
pip install -e ".[full]"
```

### Run

```bash
# As a module
python -m bh_sshcmd <subcommand> ...

# As a console command (after pip install -e .)
bh-sshcmd <subcommand> ...
```

---

## 🛠️ Subcommands

### `run` — Single Host, Single Command

Execute a command on one remote host with full auth flexibility.

```bash
# Key-based auth
python -m bh_sshcmd run 192.168.100.131 ubuntu \
  --key-file ~/.ssh/id_ed25519 \
  --command "df -h"

# Password auth with live streaming output
python -m bh_sshcmd run 192.168.100.131 ubuntu \
  --password mypass \
  --command "ls -l" \
  --stream

# Use a saved profile, output as JSON
python -m bh_sshcmd run 192.168.100.131 ubuntu \
  --profile prod-web \
  --command "uptime" \
  --json

# Structured output via plugin parser
python -m bh_sshcmd run 192.168.100.131 ubuntu \
  --command "id" \
  --parse
```

<details>
<summary><strong>Key flags</strong></summary>

| Flag | Description |
|------|-------------|
| `--stream` | Print output line-by-line as it arrives |
| `--json` | Emit result as JSON |
| `--parse` | Run stdout through a plugin parser for structured output |
| `--dry-run` | Print what would be executed without connecting |
| `--retries N` | Retry failed connections up to N times |
| `--jump-host user@bastion` | Tunnel through a jump/bastion host |
| `--host-key-policy` | `auto` \| `warn` \| `reject` |
| `--no-agent` | Disable SSH agent forwarding |
| `--no-ssh-config` | Ignore `~/.ssh/config` |
| `--profile NAME` | Use a saved connection profile |

</details>

---

### `fleet` — Same Command, Many Hosts, Concurrently

Run a command across an entire inventory in parallel.

```bash
# Run against a YAML inventory with 20 parallel workers
python -m bh_sshcmd fleet examples/inventory.yaml \
  --command "uptime" \
  --max-workers 20

# Spot config drift — groups hosts by identical output
python -m bh_sshcmd fleet examples/inventory.txt \
  --command "cat /etc/os-release" \
  --diff

# Command templating with host variables
python -m bh_sshcmd fleet examples/inventory.yaml \
  --command "echo {alias}@{hostname}" \
  --json

# Live TUI dashboard (requires `textual`)
python -m bh_sshcmd fleet examples/inventory.yaml \
  --command "uname -a" \
  --tui
```

**Supported inventory formats:**

| Format | Example |
|--------|---------|
| YAML | `host`, `user`, `port`, `key_file`, `alias`, `password` keys |
| CSV | Same columns as YAML |
| Plain text | `user@host[:port]` one per line |

> **`--diff` mode** is a config-drift detector: it buckets hosts by identical stdout so you can immediately see which machines disagree.

---

### `shell` — Interactive PTY

Drop into a real interactive terminal session on a remote host.

```bash
python -m bh_sshcmd shell 192.168.100.131 ubuntu \
  --key-file ~/.ssh/id_ed25519
```

> Provides a **raw-mode PTY bridge** on Linux/macOS, with a line-buffered fallback on Windows. Handles `sudo` prompts, interactive menus, and anything `exec_command` can't.

---

### `sftp` — File & Directory Transfer

Upload or download files and entire directories over SFTP.

```bash
# Upload a file with a progress bar
python -m bh_sshcmd sftp upload 192.168.100.131 ubuntu \
  --local ./build.tar.gz \
  --remote /tmp/build.tar.gz \
  --progress

# Download a directory recursively
python -m bh_sshcmd sftp download 192.168.100.131 ubuntu \
  --local ./backup \
  --remote /var/backups \
  --recursive
```

---

### `script` — Multi-Step Playbooks

Run a sequence of commands with conditional branching and variable capture — a mini Ansible for one host.

```bash
python -m bh_sshcmd script 192.168.100.131 ubuntu \
  --playbook examples/playbook.yaml
```

**Playbook features:**

- `on_failure: stop | continue` — conditional branching on step failure
- `register:` — capture command output into a named variable
- `{{varname}}` — interpolate captured variables into later steps

> See [`examples/playbook.yaml`](examples/playbook.yaml) for a full working example.

---

### `config` — Saved Connection Profiles

Save, list, and reuse connection profiles so you never type credentials twice.

```bash
# Save a profile
python -m bh_sshcmd config add prod-web 192.168.100.131 ubuntu \
  --key-file ~/.ssh/id_ed25519

# List all saved profiles
python -m bh_sshcmd config list

# Use a saved profile in any subcommand
python -m bh_sshcmd run --profile prod-web \
  --command "systemctl status nginx"
```

> Profiles are stored in `~/.bh_sshcmd/config.yaml`.
> Passwords are **not** saved unless you explicitly pass `--save-password` (stored in plaintext — prefer keys or an agent).

---

## ✨ Feature Highlights

| Feature | Description |
|---------|-------------|
| 🔑 **SSH Agent + `~/.ssh/config`** | Auth falls back to your agent/default keys; `Hostname`, `Port`, `User`, `IdentityFile`, `ProxyJump` are read automatically |
| 🏗️ **Jump Host / Bastion Chaining** | `--jump-host user@bastion[:port]` tunnels via a real Paramiko `direct-tcpip` channel |
| 🛡️ **Host-Key Policy Control** | `auto` (TOFU), `warn`, or `reject` — protect against MITM in production |
| 🔁 **Retry / Backoff** | `--retries` on connection failures |
| 📡 **Live Output Streaming** | `--stream` — see output as it arrives, don't wait for completion |
| 📊 **Structured / JSON Output** | `--json` — pipe results directly into other tooling |
| 🧩 **Plugin System** | Built-in parsers for `id`, `uname`, `df`, `ss`; drop your own in any directory with `--plugin-dir` |
| 🔍 **Diff / Drift Detection** | `--diff` in fleet mode groups hosts by identical output |
| 📺 **Live TUI Dashboard** | `--tui` (needs `textual`) shows per-host status as a fleet run progresses |
| 🔬 **Hexdump Debugging** | `--debug-hexdump` for inspecting raw binary stdout/stderr |
| 📝 **File Logging** | `--log-file` writes alongside console output |
| 📋 **Command Templating** | `{hostname}`, `{user}`, `{alias}` substitution in fleet commands |

---

## 📁 Project Layout

```
bh_sshcmd/
├── core.py           # SSHSession: connect (agent/ssh-config/jump-host/retry), exec_command, invoke_shell
├── fleet.py          # Concurrent multi-host runner + command templating
├── sftp_ops.py       # Upload/download, single file or recursive directory
├── script_runner.py  # Playbook loader + step runner (conditionals, variable capture)
├── config.py         # Saved profiles + inventory (YAML/CSV/txt) loading
├── plugins.py        # Output-parser registry + built-ins + external plugin loading
├── output.py         # rich/plain table, JSON, diff-group, progress bar rendering
├── tui.py            # Optional textual live dashboard
└── cli.py            # argparse subcommands — wires everything together

examples/
├── inventory.yaml    # Sample YAML fleet inventory
├── inventory.txt     # Sample plain-text inventory
└── playbook.yaml     # Sample multi-step playbook
```

---

## 🔒 Security Notes

> [!WARNING]
> **Prefer `--key-file` or an SSH agent over `--password`.**
> Passwords on the command line land in shell history and process listings.

> [!CAUTION]
> **`--host-key-policy auto`** (the default, for backwards compatibility) trusts unknown host keys automatically.
> For anything touching production, use `--host-key-policy reject` with a populated `known_hosts`, or at minimum `warn`.

> [!CAUTION]
> **`config add --save-password`** stores the password in **plaintext** on disk.
> Only use this in throwaway/lab environments — never in production.

---

## 📦 Dependencies

| Package | Required | Purpose |
|---------|----------|---------|
| `paramiko >= 3.4` | ✅ **Required** | SSH protocol implementation |
| `pyyaml >= 6.0` | ⚙️ Optional | YAML inventories and playbooks |
| `rich >= 13.0` | ⚙️ Optional | Colorized, formatted console output |
| `textual >= 0.50` | ⚙️ Optional | Live TUI fleet dashboard |

---

<div align="center">

Built with ❤️ on top of [Paramiko](https://www.paramiko.org/) — the SSH library for Python.

</div>
