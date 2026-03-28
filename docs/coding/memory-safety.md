# Memory Safety

Critical findings from debugging a 95 GB memory leak (March 2026).

## Root Cause: Quartz CGImage Native Memory

`CGWindowListCreateImage()` returns a Core Foundation `CGImage` object.
Its pixel buffer (10-50 MB per capture, depending on window resolution
and Retina scaling) is allocated in **native C memory** that Python's
garbage collector does not track.

Python only sees a lightweight pyobjc wrapper object (~100 bytes).
The GC can collect the wrapper, but the native pixel buffer stays
allocated until the Core Foundation reference count reaches zero.

### The Leak

```python
# BEFORE (leaking):
def capture_window(window_id, max_width, quality):
    cg_image = CGWindowListCreateImage(...)       # 30 MB native alloc
    pil_image = _cgimage_to_pil(cg_image)         # copies pixels, but cg_image still alive
    # ... encode to JPEG ...
    return jpeg_bytes
    # cg_image goes out of scope here, but pyobjc may NOT release it immediately
    # At 10 FPS = 300 MB/sec of unreleased native memory
```

### The Fix

```python
# AFTER (fixed):
def capture_window(window_id, max_width, quality):
    cg_image = CGWindowListCreateImage(...)
    try:
        pil_image = _cgimage_to_pil(cg_image)
    finally:
        CFRelease(cg_image)                        # explicit native release
        del cg_image                               # drop Python reference
    # ... encode to JPEG ...
    pil_image.close()                              # release PIL's internal buffer
    return jpeg_bytes
```

### Why Python's GC Doesn't Help

1. **Pyobjc bridge objects** hold a reference to the underlying CF object.
   Python's refcount may drop to zero, but pyobjc defers the `CFRelease`
   to its own ref tracking, which can lag.

2. **Circular references** between the CGImage, its data provider, and
   the raw data object prevent immediate collection. The cyclic GC
   eventually collects them, but "eventually" at 10 FPS means hundreds
   of frames accumulate before a GC cycle runs.

3. **Python's memory allocator (pymalloc)** does not return freed memory
   to the OS. Once the process RSS grows, it stays high even after GC
   runs. Only restarting the process reclaims OS memory.

### Impact

| Scenario | Leak rate | Time to 10 GB |
|----------|----------|---------------|
| Streaming at 10 FPS, 1080p window | ~120 MB/min | ~83 minutes |
| Streaming at 10 FPS, via cloud proxy | ~120 MB/min | ~83 minutes |
| No streaming (thumbnails only) | ~2 MB/min | ~83 hours |

## Secondary Issue: WebSocket Backpressure

When the browser connects through the cloud proxy (access server tunnel),
JPEG frames are:
1. Captured by `hort/screen.py`
2. Sent via `websocket.send_bytes()` to the browser
3. Relayed via the tunnel client as base64-encoded JSON

If the tunnel (Azure WebSocket) is slower than the capture rate,
`send_bytes()` queues frames in Starlette's internal buffer. Each
frame is ~200 KB. At 10 FPS with a slow tunnel, this adds ~2 MB/sec
of buffered data on top of the CGImage leak.

### Fix: Frame Queue with Drop

`hort/stream.py` now uses a `maxsize=1` asyncio Queue. The capture
loop puts the latest frame in; the send loop takes it out. If a new
frame arrives before the old one was sent, the old one is replaced.
At most 1 frame is ever buffered.

```python
_frame_queue: asyncio.Queue[bytes | None] = asyncio.Queue(maxsize=1)

# Capture loop:
if _frame_queue.full():
    _frame_queue.get_nowait()   # drop old frame
_frame_queue.put_nowait(frame)

# Send loop:
frame = await _frame_queue.get()
await websocket.send_bytes(frame)
```

### Tunnel Client Backpressure

`hort/access/tunnel_client.py` has the same issue for binary frames
forwarded through the H2H tunnel. Fix: a lock-based drop mechanism
that skips frames when the previous send is still in progress.

## Rules

1. **Do NOT call `CFRelease()` on pyobjc-managed objects** — pyobjc
   owns the reference and a double-release causes SIGABRT (crash).
   Instead, `del` the Python reference and let pyobjc handle it.
   Extract pixel data into Python bytes ASAP, then `del` the CGImage
   and its data provider so pyobjc can release the native memory.

2. **Always `pil_image.close()`** after encoding to JPEG/PNG. PIL
   images hold internal C buffers that are not freed until `close()`
   or `__del__()`.

3. **Never queue frames unbounded.** Any producer-consumer pattern
   for binary data (frames, audio, video) must have a bounded buffer
   with a drop policy. Use `asyncio.Queue(maxsize=1)` for latest-wins.

4. **Test with continuous streaming.** Memory leaks in capture/stream
   paths only manifest under sustained load. The debug endpoint
   `GET /api/debug/memory` returns RSS, GC object counts, and asyncio
   task counts for monitoring.

## Debug Endpoint

`GET /api/debug/memory` returns:

```json
{
  "rss_mb": 154.5,
  "gc_objects": 150275,
  "asyncio_tasks": 22,
  "task_names": ["Task-1", "..."],
  "top_object_counts": [["dict", 49736], ...],
  "top_object_sizes_mb": [["dict", 11.28], ...]
}
```

Key signals:
- **RSS growing but gc_objects stable** → native memory leak (CGImage, PIL buffers)
- **RSS growing and gc_objects growing** → Python object leak (unbounded list, leaked tasks)
- **asyncio_tasks growing** → leaked `create_task()` calls (tasks never awaited/cancelled)
