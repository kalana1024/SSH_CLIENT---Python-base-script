# bh_sshcmd

A fully-loaded SSH command/fleet automation toolkit built on [Paramiko](https://www.paramiko.org/). Started as a single-file "run one command on one host" script; now a small toolkit with six subcommands covering single-host execution, concurrent fleet runs, interactive shells, SFTP transfer, multi-step playbooks, and saved connection profiles.

## Install

```bash
pip install -r requirements.txt
```

Only `paramiko` is required. `pyyaml`, `rich`, and `textual` are optional — install them for YAML inventories/playbooks, colorized output, and the live TUI dashboard respectively. Everything degrades gracefully to plain text/JSON if they're missing.

Run via `python -m bh_sshcmd <subcommand> ...`, or `pip install -e .` for a `bh-sshcmd` console command.

## Subcommands

### `run` — single host, single command

```bash
python -m bh_sshcmd run 192.168.100.131 ubuntu --key-file ~/.ssh/id_ed25519 --command "df -h"
python -m bh_sshcmd run 192.168.100.131 ubuntu --password mypass --command "ls -l" --stream
python -m bh_sshcmd run 192.168.100.131 ubuntu --profile prod-web --command "uptime" --json
python -m bh_sshcmd run 192.168.100.131 ubuntu --command "id" --parse   # structured output via plugins
```

Key flags: `--stream` (live output), `--json`, `--parse` (run through a plugin parser), `--dry-run`, `--retries`, `--jump-host user@bastion`, `--host-key-policy {auto,warn,reject}`, `--no-agent`, `--no-ssh-config`.

### `fleet` — the same command, many hosts, concurrently

```bash
python -m bh_sshcmd fleet examples/inventory.yaml --command "uptime" --max-workers 20
python -m bh_sshcmd fleet examples/inventory.txt --command "cat /etc/os-release" --diff   # group hosts by identical output
python -m bh_sshcmd fleet examples/inventory.yaml --command "echo {alias}@{hostname}" --json
python -m bh_sshcmd fleet examples/inventory.yaml --command "uname -a" --tui              # live dashboard (needs `textual`)
```

Inventories are YAML (list of `host`/`user`/`port`/`key_file`/`alias`/`password` dicts), CSV with the same columns, or a plain `user@host[:port]`-per-line text file. `--diff` is a config-drift tool: it buckets hosts by identical stdout so you can immediately see which machines disagree.

### `shell` — interactive PTY

```bash
python -m bh_sshcmd shell 192.168.100.131 ubuntu --key-file ~/.ssh/id_ed25519
```

A real interactive terminal session (raw-mode PTY bridging on Linux/macOS; a line-buffered fallback on Windows), for sudo prompts, menus, or anything `exec_command` can't handle.

### `sftp` — file/directory transfer

```bash
python -m bh_sshcmd sftp upload 192.168.100.131 ubuntu --local ./build.tar.gz --remote /tmp/build.tar.gz --progress
python -m bh_sshcmd sftp download 192.168.100.131 ubuntu --local ./backup --remote /var/backups --recursive
```

### `script` — multi-step playbooks

```bash
python -m bh_sshcmd script 192.168.100.131 ubuntu --playbook examples/playbook.yaml
```

Runs a sequence of commands with conditional branching (`on_failure: stop|continue`) and variable capture (`register:` + `{{varname}}` substitution in later steps) — a mini Ansible for one host. See `examples/playbook.yaml`.

### `config` — saved connection profiles

```bash
python -m bh_sshcmd config add prod-web 192.168.100.131 ubuntu --key-file ~/.ssh/id_ed25519
python -m bh_sshcmd config list
python -m bh_sshcmd run --profile prod-web --command "systemctl status nginx"
```

Profiles live in `~/.bh_sshcmd/config.yaml`. Passwords are **not** saved unless you pass `--save-password` explicitly (stored in plaintext — prefer keys or an agent).

## Everything else it does

- **SSH agent + `~/.ssh/config`** — auth falls back to your agent/default keys, and `Hostname`/`Port`/`User`/`IdentityFile`/`ProxyJump` are read from your SSH config automatically (`--no-agent`/`--no-ssh-config` to opt out).
- **Jump host / bastion chaining** (`--jump-host user@bastion[:port]`) — tunnels the connection through an intermediate host via a real Paramiko `direct-tcpip` channel.
- **Host-key policy control** — `auto` (trust-on-first-use, the old default, flagged as MITM-risky), `warn`, or `reject` (refuse unknown host keys outright).
- **Retry/backoff** on connection failures (`--retries`).
- **Live output streaming** (`--stream`) instead of waiting for the whole command to finish.
- **Structured/JSON output** (`--json`) for piping into other tooling.
- **Command templating** in fleet mode (`{hostname}`, `{user}`, `{alias}`).
- **Plugin system** for parsing known command output (`id`, `uname`, `df`, `ss` built in) into structured dicts; drop your own parser modules in a directory and pass `--plugin-dir`.
- **Diff mode** for fleets — spot config drift by grouping hosts with identical output.
- **Live TUI dashboard** (`--tui`, needs `textual`) showing per-host status as a fleet run progresses.
- **Hexdump debugging** (`--debug-hexdump`) for inspecting raw binary stdout/stderr.
- **Logging to file** (`--log-file`) alongside console output.

## Project layout

```
bh_sshcmd/
  core.py           SSHSession: connect (agent/ssh-config/jump-host/retry), exec_command, invoke_shell
  fleet.py           concurrent multi-host runner + command templating
  sftp_ops.py         upload/download, single file or recursive directory
  script_runner.py     playbook loader + step runner (conditionals, variable capture)
  config.py             saved profiles + inventory (YAML/CSV/txt) loading
  plugins.py             output-parser registry + built-ins + external plugin loading
  output.py                rich/plain table, JSON, diff-group, progress bar rendering
  tui.py                     optional textual live dashboard
  cli.py                      argparse subcommands, wires everything together
examples/
  inventory.yaml, inventory.txt, playbook.yaml
```

## Security notes

- Prefer `--key-file` or an SSH agent over `--password` — passwords on the command line land in shell history and process listings.
- `--host-key-policy auto` (the default, for backwards compatibility) trusts unknown host keys automatically. For anything touching production, use `--host-key-policy reject` with a populated `known_hosts`, or at least `warn`.
- `config add --save-password` stores the password in **plaintext** on disk — only use it in throwaway/lab environments.
