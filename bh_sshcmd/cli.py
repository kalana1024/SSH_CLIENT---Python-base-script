"""Command-line entry point: run, fleet, shell, sftp, script, config subcommands."""

from __future__ import annotations

import argparse
import logging
import sys

from . import output, plugins, script_runner
from .config import (
    HostProfile, add_profile, get_profile, load_inventory,
    load_profiles, remove_profile,
)
from .core import ConnectionSpec, SSHSession
from .fleet import run_fleet
from .hexdump import hexdump
from .sftp_ops import download_dir, download_file, upload_dir, upload_file


def _setup_logging(args: argparse.Namespace) -> None:
    log_level = logging.DEBUG if getattr(args, "debug_hexdump", False) else (
        logging.INFO if getattr(args, "verbose", False) else logging.WARNING
    )
    logging.basicConfig(level=log_level, format="[%(asctime)s] %(levelname)s: %(message)s")
    if getattr(args, "log_file", None):
        fh = logging.FileHandler(args.log_file)
        fh.setFormatter(logging.Formatter("[%(asctime)s] %(levelname)s: %(message)s"))
        logging.getLogger().addHandler(fh)


def _add_common_connection_args(p: argparse.ArgumentParser) -> None:
    p.add_argument("--password", help="SSH password (use with caution; consider --key-file or an agent instead)")
    p.add_argument("--key-file", help="Path to SSH private key file")
    p.add_argument("--passphrase", help="Passphrase for an encrypted private key")
    p.add_argument("--port", type=int, default=22, help="SSH server port (default: 22)")
    p.add_argument("--timeout", type=float, default=10.0, help="Connection/command timeout in seconds")
    p.add_argument("--no-agent", action="store_true", help="Disable SSH agent / look-for-keys auth")
    p.add_argument("--no-ssh-config", action="store_true", help="Ignore ~/.ssh/config")
    p.add_argument("--jump-host", help="Bastion/jump host as user@host[:port]")
    p.add_argument("--host-key-policy", choices=["auto", "warn", "reject"], default="auto",
                    help="How to handle unknown host keys (default: auto = trust & store)")
    p.add_argument("--retries", type=int, default=0, help="Connection retry attempts on failure")
    p.add_argument("--profile", help="Use a saved connection profile instead of ip/user flags")


def _add_common_logging_args(p: argparse.ArgumentParser) -> None:
    p.add_argument("--verbose", "-v", action="store_true", help="Enable verbose logging (INFO level)")
    p.add_argument("--debug-hexdump", action="store_true", help="Enable hexdump logging for output (DEBUG level)")
    p.add_argument("--log-file", help="Log output to this file")


def _spec_from_args(args: argparse.Namespace) -> ConnectionSpec:
    host, user = args.ip, args.user
    key_file, password, port, jump_host, host_key_policy = (
        args.key_file, args.password, args.port, args.jump_host, args.host_key_policy,
    )
    if args.profile:
        prof = get_profile(args.profile)
        if not prof:
            print(f"No such profile: {args.profile}", file=sys.stderr)
            sys.exit(2)
        host, user = prof.host, prof.user
        key_file = key_file or prof.key_file
        password = password or prof.password
        port = args.port if args.port != 22 else prof.port
        jump_host = jump_host or prof.jump_host
        host_key_policy = host_key_policy if host_key_policy != "auto" else prof.host_key_policy

    return ConnectionSpec(
        host=host, user=user, password=password, key_file=key_file,
        port=port, timeout=args.timeout, use_agent=not args.no_agent,
        use_ssh_config=not args.no_ssh_config, jump_host=jump_host,
        host_key_policy=host_key_policy, retries=args.retries,
        passphrase=getattr(args, "passphrase", None),
    )


# --- Subcommand: run ---------------------------------------------------------

def cmd_run(args: argparse.Namespace) -> int:
    _setup_logging(args)
    if not args.password and not args.key_file and not args.profile and not args.use_agent_only:
        logging.warning("No --password/--key-file/--profile given; relying on SSH agent / default keys.")

    if args.plugin_dir:
        n = plugins.load_plugin_dir(args.plugin_dir)
        logging.info("Loaded %d plugin parser(s) from %s", n, args.plugin_dir)

    spec = _spec_from_args(args)

    if args.dry_run:
        print(f"[dry-run] would connect to {spec.user}@{spec.host}:{spec.port} and run: {args.command}")
        return 0

    session = SSHSession(spec)
    try:
        session.connect()
    except Exception as exc:  # noqa: BLE001
        print(f"Connection failed: {exc}", file=sys.stderr)
        return 1

    stream_cb = None
    if args.stream:
        def stream_cb(kind, chunk):  # noqa: ANN001
            (sys.stdout if kind == "stdout" else sys.stderr).write(chunk)
            (sys.stdout if kind == "stdout" else sys.stderr).flush()

    try:
        result = session.exec_command(args.command, stream_callback=stream_cb)
    finally:
        session.close()

    if args.debug_hexdump:
        if result.stdout:
            logging.debug("stdout hexdump:\n%s", hexdump(result.stdout.encode("utf-8", errors="replace")))
        if result.stderr:
            logging.debug("stderr hexdump:\n%s", hexdump(result.stderr.encode("utf-8", errors="replace")))

    if args.json:
        print(output.to_json([result]))
    elif args.parse:
        import json as _json
        print(_json.dumps(plugins.parse_output(args.command, result.stdout), indent=2))
    elif not args.stream:
        output.print_result(result)

    return result.exit_code if result.exit_code is not None else 1


# --- Subcommand: fleet --------------------------------------------------------

def cmd_fleet(args: argparse.Namespace) -> int:
    _setup_logging(args)
    hosts = load_inventory(args.inventory)
    if not hosts:
        print("Inventory is empty.", file=sys.stderr)
        return 2

    if args.tui:
        try:
            from .tui import run_fleet_tui
            results = run_fleet_tui(hosts, args.command, dict(
                max_workers=args.max_workers, default_key_file=args.key_file,
                default_password=args.password, timeout=args.timeout,
                host_key_policy=args.host_key_policy, retries=args.retries,
                dry_run=args.dry_run,
            ))
        except ImportError as exc:
            print(f"{exc}\nFalling back to plain output.", file=sys.stderr)
            results = _run_fleet_with_progress(hosts, args)
    else:
        results = _run_fleet_with_progress(hosts, args)

    if args.json:
        print(output.to_json(results))
    elif args.diff:
        output.print_diff_groups(results)
    else:
        output.print_fleet_table(results)

    return 0 if all(r.ok for r in results) else 1


def _run_fleet_with_progress(hosts, args):
    with output.make_progress() as progress:
        task = progress.add_task("Running fleet command...", total=len(hosts))

        def on_result(_result):
            progress.update(task, advance=1)

        return run_fleet(
            hosts, args.command, max_workers=args.max_workers,
            default_key_file=args.key_file, default_password=args.password,
            timeout=args.timeout, host_key_policy=args.host_key_policy,
            retries=args.retries, dry_run=args.dry_run, on_result=on_result,
        )


# --- Subcommand: shell --------------------------------------------------------

def cmd_shell(args: argparse.Namespace) -> int:
    _setup_logging(args)
    spec = _spec_from_args(args)
    session = SSHSession(spec)
    try:
        session.connect()
    except Exception as exc:  # noqa: BLE001
        print(f"Connection failed: {exc}", file=sys.stderr)
        return 1

    shell = session.invoke_shell()
    try:
        print(f"-- interactive shell to {spec.user}@{spec.host}:{spec.port} (Ctrl-D / 'exit' to quit) --")
        shell.run()
    finally:
        shell.close()
        session.close()
    return 0


# --- Subcommand: sftp ----------------------------------------------------------

def cmd_sftp(args: argparse.Namespace) -> int:
    _setup_logging(args)
    spec = _spec_from_args(args)
    session = SSHSession(spec)
    try:
        session.connect()
    except Exception as exc:  # noqa: BLE001
        print(f"Connection failed: {exc}", file=sys.stderr)
        return 1

    def progress(path, transferred, total):
        pct = (transferred / total * 100) if total else 0
        print(f"\r{path}: {transferred}/{total} ({pct:.0f}%)", end="", flush=True)

    try:
        if args.action == "upload":
            fn = upload_dir if args.recursive else upload_file
            fn(session, args.local, args.remote, progress=progress if args.progress else None)
        else:
            fn = download_dir if args.recursive else download_file
            fn(session, args.remote, args.local, progress=progress if args.progress else None)
        if args.progress:
            print()
        print("Done.")
    except Exception as exc:  # noqa: BLE001
        print(f"\nSFTP error: {exc}", file=sys.stderr)
        return 1
    finally:
        session.close()
    return 0


# --- Subcommand: script --------------------------------------------------------

def cmd_script(args: argparse.Namespace) -> int:
    _setup_logging(args)
    steps = script_runner.load_playbook(args.playbook)
    spec = _spec_from_args(args)
    session = SSHSession(spec)
    try:
        session.connect()
    except Exception as exc:  # noqa: BLE001
        print(f"Connection failed: {exc}", file=sys.stderr)
        return 1

    try:
        outcomes = script_runner.run_playbook(session, steps)
    finally:
        session.close()

    ok = True
    for outcome in outcomes:
        output.print_result(outcome.result)
        ok = ok and outcome.result.ok
    return 0 if ok else 1


# --- Subcommand: config --------------------------------------------------------

def cmd_config(args: argparse.Namespace) -> int:
    if args.config_action == "list":
        profiles = load_profiles()
        if not profiles:
            print("No saved profiles.")
            return 0
        for name, p in profiles.items():
            print(f"{name}: {p.user}@{p.host}:{p.port}" + (f" (key: {p.key_file})" if p.key_file else ""))
        return 0

    if args.config_action == "add":
        add_profile(HostProfile(
            name=args.name, host=args.ip, user=args.user, port=args.port,
            key_file=args.key_file, jump_host=args.jump_host,
            host_key_policy=args.host_key_policy,
            password=args.password if args.save_password else None,
        ))
        print(f"Saved profile '{args.name}'.")
        return 0

    if args.config_action == "remove":
        removed = remove_profile(args.name)
        print(f"Removed profile '{args.name}'." if removed else f"No such profile: {args.name}")
        return 0 if removed else 1

    return 0


# --- Argument parser assembly ---------------------------------------------------

def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="bh_sshcmd", description="A fully-loaded SSH command/fleet toolkit")
    sub = parser.add_subparsers(dest="subcommand", required=True)

    # run
    p_run = sub.add_parser("run", help="Run a command on a single host")
    p_run.add_argument("ip", help="SSH server IP/hostname")
    p_run.add_argument("user", nargs="?", default=None, help="SSH username (optional if using --profile)")
    p_run.add_argument("--command", default="id", help="Command to execute (default: id)")
    p_run.add_argument("--dry-run", action="store_true", help="Validate args/connectivity plan without connecting")
    p_run.add_argument("--stream", action="store_true", help="Stream stdout/stderr live as the command runs")
    p_run.add_argument("--json", action="store_true", help="Output result as JSON")
    p_run.add_argument("--parse", action="store_true", help="Parse output via a registered plugin parser")
    p_run.add_argument("--plugin-dir", help="Directory of custom output-parser plugins")
    p_run.add_argument("--use-agent-only", action="store_true", help="Suppress the no-credentials warning")
    _add_common_connection_args(p_run)
    _add_common_logging_args(p_run)
    p_run.set_defaults(func=cmd_run)

    # fleet
    p_fleet = sub.add_parser("fleet", help="Run a command across many hosts concurrently")
    p_fleet.add_argument("inventory", help="Inventory file (.yaml/.csv/.txt) of hosts")
    p_fleet.add_argument("--command", default="id",
                          help="Command template; supports {hostname}/{user}/{alias}")
    p_fleet.add_argument("--max-workers", type=int, default=10, help="Concurrent connections (default: 10)")
    p_fleet.add_argument("--diff", action="store_true", help="Group hosts by identical output (drift detection)")
    p_fleet.add_argument("--json", action="store_true", help="Output results as JSON")
    p_fleet.add_argument("--dry-run", action="store_true", help="Render commands without connecting")
    p_fleet.add_argument("--tui", action="store_true", help="Live TUI dashboard (requires `textual`)")
    p_fleet.add_argument("--password", help="Default password for hosts without one in the inventory")
    p_fleet.add_argument("--key-file", help="Default key file for hosts without one in the inventory")
    p_fleet.add_argument("--timeout", type=float, default=10.0)
    p_fleet.add_argument("--host-key-policy", choices=["auto", "warn", "reject"], default="auto")
    p_fleet.add_argument("--retries", type=int, default=0)
    _add_common_logging_args(p_fleet)
    p_fleet.set_defaults(func=cmd_fleet)

    # shell
    p_shell = sub.add_parser("shell", help="Open an interactive PTY shell on a host")
    p_shell.add_argument("ip")
    p_shell.add_argument("user", nargs="?", default=None)
    _add_common_connection_args(p_shell)
    _add_common_logging_args(p_shell)
    p_shell.set_defaults(func=cmd_shell)

    # sftp
    p_sftp = sub.add_parser("sftp", help="Upload/download files or directories")
    p_sftp.add_argument("action", choices=["upload", "download"])
    p_sftp.add_argument("ip")
    p_sftp.add_argument("user", nargs="?", default=None)
    p_sftp.add_argument("--local", required=True, help="Local file/directory path")
    p_sftp.add_argument("--remote", required=True, help="Remote file/directory path")
    p_sftp.add_argument("--recursive", action="store_true", help="Transfer a whole directory tree")
    p_sftp.add_argument("--progress", action="store_true", help="Show transfer progress")
    _add_common_connection_args(p_sftp)
    _add_common_logging_args(p_sftp)
    p_sftp.set_defaults(func=cmd_sftp)

    # script
    p_script = sub.add_parser("script", help="Run a multi-step playbook against a host")
    p_script.add_argument("ip")
    p_script.add_argument("user", nargs="?", default=None)
    p_script.add_argument("--playbook", required=True, help="YAML/JSON playbook file")
    _add_common_connection_args(p_script)
    _add_common_logging_args(p_script)
    p_script.set_defaults(func=cmd_script)

    # config
    p_config = sub.add_parser("config", help="Manage saved connection profiles")
    config_sub = p_config.add_subparsers(dest="config_action", required=True)

    c_list = config_sub.add_parser("list", help="List saved profiles")
    c_list.set_defaults(func=cmd_config)

    c_add = config_sub.add_parser("add", help="Save a connection profile")
    c_add.add_argument("name")
    c_add.add_argument("ip")
    c_add.add_argument("user")
    c_add.add_argument("--port", type=int, default=22)
    c_add.add_argument("--key-file")
    c_add.add_argument("--jump-host")
    c_add.add_argument("--host-key-policy", choices=["auto", "warn", "reject"], default="auto")
    c_add.add_argument("--password", help="Only stored if --save-password is also given")
    c_add.add_argument("--save-password", action="store_true",
                        help="Store the password in plaintext in the profile (not recommended)")
    c_add.set_defaults(func=cmd_config)

    c_remove = config_sub.add_parser("remove", help="Remove a saved profile")
    c_remove.add_argument("name")
    c_remove.set_defaults(func=cmd_config)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.subcommand in ("run", "shell", "sftp", "script"):
        if not args.profile and args.user is None:
            parser.error("USER is required unless --profile is given.")
        if args.subcommand == "run" and not args.password and not args.key_file and not args.profile:
            pass  # allowed: agent/default-key auth is valid and checked inside cmd_run

    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
