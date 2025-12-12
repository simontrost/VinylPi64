import subprocess
import threading
import sys
from typing import Optional
from vinylpi.paths import BASE_DIR

_recognizer_proc: Optional[subprocess.Popen] = None
_lock = threading.Lock()

def is_running() -> bool:
    global _recognizer_proc
    if _recognizer_proc is None:
        return False
    if _recognizer_proc.poll() is None:
        return True
    _recognizer_proc = None
    return False

def start(*, silence_output: bool) -> bool:
    global _recognizer_proc
    with _lock:
        if is_running():
            return False

        cmd = [sys.executable, "-u", "-m", "vinylpi.main"]

        if silence_output:
            _recognizer_proc = subprocess.Popen(
                cmd,
                cwd=BASE_DIR,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
        else:
            _recognizer_proc = subprocess.Popen(cmd, cwd=BASE_DIR)

        return True

def stop() -> bool:
    global _recognizer_proc
    with _lock:
        if not is_running():
            _recognizer_proc = None
            return False

        _recognizer_proc.terminate()
        try:
            _recognizer_proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            _recognizer_proc.kill()
        finally:
            _recognizer_proc = None
        return True
