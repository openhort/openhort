# Crate Store

Azure Blob Storage-compatible file store backed by local filesystem.
Every llming gets isolated crate storage — no cross-llming access
without explicit permission.

## API

```python
# Upload
info = await self.persist.crates.put(
    "exports",             # container (directory)
    "report.pdf",          # crate name
    pdf_bytes,             # binary data
    content_type="application/pdf",
    metadata={"author": "system-monitor"},
    ttl=86400,             # expires in 24h (or None for permanent)
    access="shared",       # private | shared | public
)

# Download
data, info = await self.persist.crates.get("exports", "report.pdf")

# Metadata only (no download)
info = await self.persist.crates.head("exports", "report.pdf")
# info.size, info.content_type, info.created_at, info.expires_at
# info.metadata, info.etag, info.access

# List crates
crates = await self.persist.crates.list("exports")
crates = await self.persist.crates.list("exports", prefix="report")

# Check existence
if await self.persist.crates.exists("exports", "report.pdf"):
    ...

# Delete
await self.persist.crates.delete("exports", "report.pdf")

# Delete entire container
await self.persist.crates.delete_container("temp-exports")

# List containers
containers = await self.persist.crates.list_containers()
```

## CrateInfo

Returned by `put`, `get`, `head`, and `list`:

```python
@dataclass
class CrateInfo:
    name: str           # "report.pdf"
    container: str      # "exports"
    size: int           # bytes
    content_type: str   # "application/pdf"
    created_at: float   # unix timestamp
    updated_at: float   # unix timestamp
    expires_at: float   # unix timestamp or None
    metadata: dict      # custom key-value metadata
    etag: str           # changes on each write
    access: str         # "private" | "shared" | "public"
```

## TTL

```python
# Expires in 1 hour
await self.runtime.crates.put("cache", "frame.webp", data, ttl=3600)
```

- Expired crates are invisible to `get`, `head`, `list`, `exists`
- Garbage collector deletes files from disk every 60 seconds
- No TTL = permanent (until explicitly deleted)

## Access Levels

| Level | Who reads | Who writes |
|-------|----------|------------|
| `private` | Owner llming only | Owner only |
| `shared` | Llmings with wire permission | Owner only |
| `public` | Any llming | Owner only |

## Containers

Containers are logical groupings (like directories). They're created
automatically on first `put`. Use them to organize crates:

```python
await self.persist.crates.put("screenshots", "daily.png", ...)
await self.persist.crates.put("exports", "report.pdf", ...)
await self.runtime.crates.put("cache", "thumbnail.webp", ..., ttl=60)
```

## Under the Hood

- Crates stored as files on disk (`~/.hort/storage/{llming}/blobs/{container}/`)
- Metadata tracked in SQLite (`_blobs.db` alongside the files)
- WAL mode for crash safety
- File + metadata always in sync (atomic writes)
- Large crates (100MB+) work fine — no size limit
- Thread-safe
