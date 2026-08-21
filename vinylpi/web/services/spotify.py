from __future__ import annotations

import subprocess
import sys
import threading
from typing import Optional

from vinylpi.paths import BASE_DIR

_spotify_proc: Optional[subprocess.Popen] = None
_lock = threading.Lock()


def is_running() -> bool:
    global _spotify_proc
    if _spotify_proc is None:
        return False
    if _spotify_proc.poll() is None:
        return True
    _spotify_proc = None
    return False


def start(*, silence_output: bool) -> bool:
    global _spotify_proc
    with _lock:
        if is_running():
            return False

        cmd = [sys.executable, "-u", "-m", "vinylpi.spotify_worker"]
        kwargs = {"cwd": BASE_DIR}
        if silence_output:
            kwargs.update(stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        _spotify_proc = subprocess.Popen(cmd, **kwargs)
        return True


def stop() -> bool:
    global _spotify_proc
    with _lock:
        if not is_running():
            _spotify_proc = None
            return False

        _spotify_proc.terminate()
        try:
            _spotify_proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            _spotify_proc.kill()
        finally:
            _spotify_proc = None
        return True
