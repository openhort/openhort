"""Typewriter display — smooth character-by-character output.

Consumes stream events on a background thread and drains them to
stdout at an adaptive rate so the output always looks and feels like
fast, real-time streaming — even when the underlying data arrives in
large blocks.
"""

from __future__ import annotations

import subprocess
import sys
import threading
import time
from collections import deque
from typing import Callable, Generator

from .stream import stream_response

# Characters per second bounds
MIN_CPS = 300    # floor — never slower than this
MAX_CPS = 4000   # ceiling — never faster than this
MAX_DRAIN_S = 2.0  # max seconds to flush remaining buffer after stream ends

# Type alias for the stream function
StreamFn = Callable[
    [subprocess.Popen[bytes]],
    Generator[tuple[str, str | dict], None, None],
]


def typewriter(
    proc: subprocess.Popen[bytes],
    stream_fn: StreamFn = stream_response,
) -> dict:
    """Print streamed text with a smooth typewriter effect.

    A background reader thread fills a character deque from
    ``stream_fn(proc)``.  The main thread drains the deque at a rate
    between ``MIN_CPS`` and ``MAX_CPS``, adapting to buffer depth:

    * Buffer < 20 chars  → ``MIN_CPS`` (stream is trickling in live)
    * Buffer 20–80 chars → linear ramp
    * Buffer > 80 chars  → ``MAX_CPS`` + multi-char chunks

    Once the stream ends, any remaining buffer is flushed within
    ``MAX_DRAIN_S`` seconds using increasingly large chunks so the
    user never waits more than ~2 s for the tail of a response.

    Returns:
        dict with ``session_id`` (str) and ``cost`` (float).
    """
    buf: deque[str] = deque()
    meta: dict = {}
    done = threading.Event()
    first_char = threading.Event()

    def reader() -> None:
        first_text = True
        for kind, data in stream_fn(proc):
            if kind == "text":
                assert isinstance(data, str)
                if first_text:
                    data = data.lstrip("\n")
                    first_text = False
                    if not data:
                        continue
                for ch in data:
                    buf.append(ch)
                if not first_char.is_set():
                    first_char.set()
            elif kind == "meta":
                assert isinstance(data, dict)
                meta.update(data)
        done.set()
        first_char.set()  # unblock main thread if no text arrived

    t = threading.Thread(target=reader, daemon=True)
    t.start()

    first_char.wait()

    got_text = False
    draining = False
    drain_start = 0.0
    while True:
        if buf:
            pending = len(buf)

            if draining:
                elapsed = time.monotonic() - drain_start
                remaining_time = max(MAX_DRAIN_S - elapsed, 0.01)
                chunk_size = max(1, int(pending / (remaining_time * MAX_CPS)) + 1)
                chunk_size = min(chunk_size, pending)
                chunk = "".join(buf.popleft() for _ in range(chunk_size))
                sys.stdout.write(chunk)
                sys.stdout.flush()
                got_text = True
                time.sleep(1.0 / MAX_CPS)
            else:
                if pending > 80:
                    cps = MAX_CPS
                elif pending > 20:
                    cps = MIN_CPS + (MAX_CPS - MIN_CPS) * (pending - 20) / 60
                else:
                    cps = MIN_CPS

                chunk_size = max(1, pending // 40)
                chunk = "".join(
                    buf.popleft() for _ in range(min(chunk_size, len(buf) or 1))
                )
                sys.stdout.write(chunk)
                sys.stdout.flush()
                got_text = True
                time.sleep(1.0 / cps)
        elif done.is_set():
            break
        else:
            time.sleep(0.002)

        if done.is_set() and not draining and buf:
            draining = True
            drain_start = time.monotonic()

    t.join()

    if got_text:
        print()
    else:
        print("(no response)")

    return meta
