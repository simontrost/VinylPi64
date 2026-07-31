from __future__ import annotations

import asyncio
import atexit
import threading
from concurrent.futures import TimeoutError as FutureTimeoutError
from typing import Any, Coroutine, TypeVar

from shazamio import Shazam

T = TypeVar("T")

_loop: asyncio.AbstractEventLoop | None = None
_loop_thread: threading.Thread | None = None
_loop_lock = threading.Lock()
_client: Shazam | None = None


def _run_loop(loop: asyncio.AbstractEventLoop) -> None:
    asyncio.set_event_loop(loop)
    loop.run_forever()


def _ensure_loop() -> asyncio.AbstractEventLoop:
    global _loop, _loop_thread

    with _loop_lock:
        if (
            _loop is not None
            and _loop_thread is not None
            and _loop_thread.is_alive()
        ):
            return _loop

        loop = asyncio.new_event_loop()
        thread = threading.Thread(
            target=_run_loop,
            args=(loop,),
            name="vinylpi-shazam-runtime",
            daemon=True,
        )
        thread.start()
        _loop = loop
        _loop_thread = thread
        return loop


async def _get_client() -> Shazam:
    global _client
    if _client is None:
        _client = Shazam()
    return _client


def _submit(coroutine: Coroutine[Any, Any, T], *, timeout_seconds: float) -> T:
    loop = _ensure_loop()
    future = asyncio.run_coroutine_threadsafe(coroutine, loop)
    try:
        return future.result(timeout=max(1.0, timeout_seconds))
    except FutureTimeoutError as exc:
        future.cancel()
        raise TimeoutError("Shazam request timed out") from exc


async def _recognize(audio: bytes, timeout_seconds: float) -> dict[str, Any]:
    client = await _get_client()
    result = await asyncio.wait_for(
        client.recognize(audio),
        timeout=max(1.0, timeout_seconds),
    )
    return result if isinstance(result, dict) else {}


def recognize_audio(audio: bytes, *, timeout_seconds: float) -> dict[str, Any]:
    return _submit(
        _recognize(audio, timeout_seconds),
        timeout_seconds=timeout_seconds + 2.0,
    )


async def _get_details(
    track_id: str | None,
    artist_id: str | None,
) -> dict[str, Any]:
    client = await _get_client()
    tasks: list[tuple[str, asyncio.Task]] = []

    if track_id:
        tasks.append(
            ("track", asyncio.create_task(client.track_about(track_id=track_id)))
        )
    if artist_id:
        tasks.append(
            ("artist", asyncio.create_task(client.artist_about(artist_id)))
        )

    result: dict[str, Any] = {"track": None, "artist": None}
    for key, task in tasks:
        try:
            value = await task
            result[key] = value if isinstance(value, dict) else {}
        except Exception as exc:
            result[key] = {"ok": False, "error": str(exc)}
    return result


def get_details(
    track_id: str | None,
    artist_id: str | None,
    *,
    timeout_seconds: float = 20.0,
) -> dict[str, Any]:
    return _submit(
        _get_details(track_id, artist_id),
        timeout_seconds=timeout_seconds,
    )


def shutdown() -> None:
    global _loop, _loop_thread, _client

    with _loop_lock:
        loop = _loop
        thread = _loop_thread
        _loop = None
        _loop_thread = None
        _client = None

    if loop is not None and loop.is_running():
        loop.call_soon_threadsafe(loop.stop)
    if thread is not None and thread.is_alive():
        thread.join(timeout=1.0)
    if loop is not None and not loop.is_running() and not loop.is_closed():
        loop.close()


atexit.register(shutdown)
