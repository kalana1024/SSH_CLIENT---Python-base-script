"""SFTP file and directory transfer helpers, layered on an existing SSHSession."""

from __future__ import annotations

import logging
import os
from typing import Callable, Optional

import paramiko

from .core import SSHSession

logger = logging.getLogger("bh_sshcmd.sftp")

ProgressCB = Optional[Callable[[str, int, int], None]]  # (path, transferred, total)


def _sftp(session: SSHSession) -> paramiko.SFTPClient:
    assert session.client is not None, "call connect() first"
    return session.client.open_sftp()


def upload_file(session: SSHSession, local_path: str, remote_path: str, progress: ProgressCB = None) -> None:
    sftp = _sftp(session)
    try:
        cb = (lambda t, total: progress(local_path, t, total)) if progress else None
        sftp.put(local_path, remote_path, callback=cb)
        logger.info("Uploaded %s -> %s:%s", local_path, session.spec.host, remote_path)
    finally:
        sftp.close()


def download_file(session: SSHSession, remote_path: str, local_path: str, progress: ProgressCB = None) -> None:
    sftp = _sftp(session)
    try:
        cb = (lambda t, total: progress(remote_path, t, total)) if progress else None
        sftp.get(remote_path, local_path, callback=cb)
        logger.info("Downloaded %s:%s -> %s", session.spec.host, remote_path, local_path)
    finally:
        sftp.close()


def upload_dir(session: SSHSession, local_dir: str, remote_dir: str, progress: ProgressCB = None) -> None:
    sftp = _sftp(session)
    try:
        _mkdir_p(sftp, remote_dir)
        for root, dirs, files in os.walk(local_dir):
            rel = os.path.relpath(root, local_dir)
            remote_root = remote_dir if rel == "." else _posix_join(remote_dir, rel)
            _mkdir_p(sftp, remote_root)
            for fname in files:
                local_path = os.path.join(root, fname)
                remote_path = _posix_join(remote_root, fname)
                cb = (lambda t, total, lp=local_path: progress(lp, t, total)) if progress else None
                sftp.put(local_path, remote_path, callback=cb)
        logger.info("Uploaded directory %s -> %s:%s", local_dir, session.spec.host, remote_dir)
    finally:
        sftp.close()


def download_dir(session: SSHSession, remote_dir: str, local_dir: str, progress: ProgressCB = None) -> None:
    sftp = _sftp(session)
    try:
        os.makedirs(local_dir, exist_ok=True)
        _download_dir_recursive(sftp, remote_dir, local_dir, progress)
        logger.info("Downloaded directory %s:%s -> %s", session.spec.host, remote_dir, local_dir)
    finally:
        sftp.close()


def _download_dir_recursive(sftp: paramiko.SFTPClient, remote_dir: str, local_dir: str, progress: ProgressCB) -> None:
    import stat as statmod

    os.makedirs(local_dir, exist_ok=True)
    for entry in sftp.listdir_attr(remote_dir):
        remote_path = _posix_join(remote_dir, entry.filename)
        local_path = os.path.join(local_dir, entry.filename)
        if statmod.S_ISDIR(entry.st_mode):
            _download_dir_recursive(sftp, remote_path, local_path, progress)
        else:
            cb = (lambda t, total, rp=remote_path: progress(rp, t, total)) if progress else None
            sftp.get(remote_path, local_path, callback=cb)


def _mkdir_p(sftp: paramiko.SFTPClient, remote_dir: str) -> None:
    parts = remote_dir.strip("/").split("/")
    path = ""
    for part in parts:
        path = f"{path}/{part}" if path else f"/{part}"
        try:
            sftp.stat(path)
        except FileNotFoundError:
            sftp.mkdir(path)


def _posix_join(*parts: str) -> str:
    return "/".join(p.strip("/") for p in parts if p)
