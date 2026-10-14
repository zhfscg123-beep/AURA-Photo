"""ASCII directory access for Windows tools without allocating drive letters.

Junctions contain no copied application data. They are shared by processes,
verified against the original directory, and never overwrite existing entries.
"""
import ctypes
import hashlib
import os
from pathlib import Path
import subprocess
import threading

_lock = threading.RLock()


def _short_path(path):
    buffer = ctypes.create_unicode_buffer(32768)
    api = ctypes.WinDLL('kernel32', use_last_error=True).GetShortPathNameW
    api.argtypes = [ctypes.c_wchar_p, ctypes.c_wchar_p, ctypes.c_uint32]
    api.restype = ctypes.c_uint32
    length = api(str(path), buffer, len(buffer))
    return Path(buffer.value) if 0 < length < len(buffer) and buffer.value.isascii() else None


def _junction_base(target):
    local = os.environ.get('LOCALAPPDATA')
    if not local:
        raise RuntimeError('Windows LOCALAPPDATA is unavailable for ASCII path access.')
    base = Path(local).resolve()
    # JDK 17 file creation fails through a cross-volume junction on Windows.
    # Keep the entry on the target volume; only the link lives here, no data copy.
    if base.drive.casefold() != target.drive.casefold() or not str(base).isascii():
        if not target.drive or target.drive.startswith('\\\\'):
            raise RuntimeError('英文目录入口需要可写的本地磁盘；不会创建虚拟盘符。')
        return Path(target.anchor) / '.aura-photo-paths'
    return base / 'AURA-Photo' / 'path-links'


def _verify_link(link, target):
    if not link.is_junction() or not os.path.samefile(link, target):
        raise RuntimeError(f'ASCII path entry belongs to another directory: {link}')


def ascii_directory(directory):
    """Return the same directory through an ASCII path, preserving all drives."""
    target = Path(directory).resolve(strict=True)
    if not target.is_dir():
        raise NotADirectoryError(target)
    if os.name != 'nt' or str(target).isascii():
        return target
    short = _short_path(target)
    if short is not None:
        return short
    with _lock:
        base = _junction_base(target)
        base.mkdir(parents=True, exist_ok=True)
        key = hashlib.sha256(str(target).casefold().encode('utf8')).hexdigest()[:24]
        link = base / key
        if not os.path.lexists(link):
            # Paths travel as environment values, never as interpolated shell code.
            env = dict(os.environ, AURA_LINK_PATH=str(link), AURA_LINK_TARGET=str(target))
            powershell = Path(os.environ['SystemRoot']) / 'System32/WindowsPowerShell/v1.0/powershell.exe'
            result = subprocess.run(
                [str(powershell), '-NoLogo', '-NoProfile', '-NonInteractive', '-Command',
                 "$ErrorActionPreference='Stop'; New-Item -ItemType Junction "
                 '-Path $env:AURA_LINK_PATH -Target $env:AURA_LINK_TARGET | Out-Null'],
                env=env, capture_output=True, creationflags=subprocess.CREATE_NO_WINDOW,
            )
            # Another process may have created this exact junction concurrently.
            if result.returncode and not os.path.lexists(link):
                raise RuntimeError('无法准备 GPU/开发工具的英文目录入口；不会创建虚拟盘符。')
        _verify_link(link, target)
        return link
