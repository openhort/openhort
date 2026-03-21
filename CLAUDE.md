# llming-control

Remote macOS window viewer — watch your Mac from your phone/tablet.

## Architecture

- **Server:** FastAPI (Python), HTTP on 8940, HTTPS on 8950 (self-signed cert)
- **UI:** Vanilla JS single-page app in `hort/static/index.html`
- **Capture:** macOS Quartz API via pyobjc (`CGWindowListCreateImage`)
- **Streaming:** WebSocket, JPEG frames
- **State:** All client-side state in localStorage (groups, per-window zoom, settings)

## Key Files

- `hort/app.py` — FastAPI routes, WebSocket streaming, observer tracking
- `hort/models.py` — Pydantic models (strict types, frozen where appropriate)
- `hort/screen.py` — Window screenshot capture (Quartz → PIL → JPEG)
- `hort/windows.py` — Window listing/filtering (Quartz)
- `hort/network.py` — LAN IP detection, QR code generation
- `hort/cert.py` — Self-signed TLS certificate generation
- `hort/static/index.html` — Complete mobile-first UI

## Guidelines

- [UX Guidelines](docs/ux-guidelines.md) — interaction model, fit modes, panning rules, resolution strategy

## Quality Standards

- 100% test coverage (`pytest --cov=hort`)
- mypy strict on `hort/` (tests excluded)
- Pydantic v2 for all data models
- OS-level Quartz wrappers isolated behind `_raw_*` functions for testability

## Running

```bash
poetry run python run.py
```

Requires Screen Recording permission for the terminal app in System Settings.
