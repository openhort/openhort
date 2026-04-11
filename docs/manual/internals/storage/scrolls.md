# Scroll Store

MongoDB-compatible scroll storage backed by SQLite. Every llming
gets its own isolated database — no cross-llming access without
explicit permission.

## API

```python
# Insert
doc_id = await self.persist.scrolls.insert("circuits",
    {"name": "my-flow", "nodes": [...]},
    ttl=None,           # permanent (or seconds until expiry)
    access="private",   # private | shared | public
)

# Find one
flow = await self.persist.scrolls.find_one("circuits", {"name": "my-flow"})

# Find many (with sort, limit, skip)
recent = await self.persist.scrolls.find("circuits",
    {"active": True},
    sort=[("created", -1)],
    limit=10, skip=0,
)

# Count
n = await self.persist.scrolls.count("circuits", {"active": True})

# Update
await self.persist.scrolls.update_one("circuits",
    {"_id": flow_id},
    {"$set": {"active": False}},
)

# Increment
await self.persist.scrolls.update_one("counters",
    {"_id": "visits"},
    {"$inc": {"count": 1}},
)

# Delete
await self.persist.scrolls.delete_one("circuits", {"_id": flow_id})
await self.persist.scrolls.delete_many("cache", {"stale": True})
```

## Query Operators

| Operator | Example | Description |
|----------|---------|-------------|
| (exact) | `{"name": "x"}` | Exact match |
| `$gt` | `{"age": {"$gt": 18}}` | Greater than |
| `$gte` | `{"age": {"$gte": 18}}` | Greater than or equal |
| `$lt` | `{"age": {"$lt": 65}}` | Less than |
| `$lte` | `{"age": {"$lte": 65}}` | Less than or equal |
| `$ne` | `{"status": {"$ne": "deleted"}}` | Not equal |
| `$in` | `{"tag": {"$in": ["a", "b"]}}` | Value in list |
| `$exists` | `{"email": {"$exists": true}}` | Field exists |
| `$and` | `{"$and": [{...}, {...}]}` | Logical AND |
| `$or` | `{"$or": [{...}, {...}]}` | Logical OR |

## Update Operators

| Operator | Example | Description |
|----------|---------|-------------|
| `$set` | `{"$set": {"name": "new"}}` | Set field values |
| `$unset` | `{"$unset": {"old": ""}}` | Remove fields |
| `$inc` | `{"$inc": {"count": 1}}` | Increment number |
| `$push` | `{"$push": {"tags": "new"}}` | Append to array |

Without operators, the update replaces the entire scroll (except `_id`).

## TTL

```python
# Expires in 5 minutes
await self.runtime.scrolls.insert("cache", {"key": "temp"}, ttl=300)
```

- Expired scrolls are invisible to all queries immediately
- Garbage collector removes them from disk every 60 seconds
- No TTL = permanent (until explicitly deleted)

## Access Levels

Every scroll has an `_access` field:

| Level | Who reads | Who writes |
|-------|----------|------------|
| `private` | Owner llming only | Owner only |
| `shared` | Llmings with wire permission | Owner only |
| `public` | Any llming | Owner only |

```python
# Private credential — only this llming
await self.persist.scrolls.insert("config", {"token": "..."}, access="private")

# Shared metric — permitted llmings can query
await self.persist.scrolls.insert("metrics", {"cpu": 42}, access="shared")

# Public status — anyone can read
await self.persist.scrolls.insert("status", {"online": True}, access="public")
```

## Under the Hood

- SQLite with WAL mode (crash-safe, concurrent reads)
- One `.db` file per llming per lifetime (runtime/persist)
- Collections are SQLite tables, created on first use
- Scrolls stored as JSON text columns
- Filtering done in Python (small datasets) — scales to ~100K scrolls per collection
- Thread-safe (one connection per thread via `threading.local`)
