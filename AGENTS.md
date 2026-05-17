# Agent Notes

## Documentation

- Use Material for MkDocs for project documentation.
- Keep public docs white-labeled and suitable for the OpenHort repository.
- Use Mermaid for technical architecture and sequence diagrams.
- Use Excalidraw and exported SVGs for polished flow and concept visualizations.
- Mermaid diagrams and SVG/Excalidraw images in the MkDocs site should be inspectable through the diagram lightbox.

## Platform Repositories

- `openhort`: public OpenHort runtime, isolated agentic service execution, public docs, and OpenHort-specific wrappers.
- `llming-com`: shared communication primitives, P2P/proxy/relay code, generic viewers, and reusable deployment baselines.
- `www_openhort_ai`: public website and Cloudflare Workers deployed for OpenHort-hosted web/API surfaces.
- `openhort-concept`: private concept repository for business logic, business policy, commercial platform decisions, and managed-service planning.

## Private Concepts

- Business logic, business concepts, account-plan details, pricing, billing, and managed-service policy decisions must stay out of this repository.
- Private concept work lives in a separate repository. The local path is recorded in `.agents/private-concepts.local.md`.
- `.agents/private-concepts.local.md` is intentionally git-ignored. Do not commit it, and do not copy private concept details from that repository into OpenHort.

## Shared Transport Boundary

- OpenHort is about isolated execution and orchestration of agentic services.
- Shared P2P, relay, proxy, pairing, reconnect, and browser viewer primitives belong in `llming-com`.
- Current shared homes are `llming_com/p2p/admission.py`, `llming_com/p2p/proxy.py`, `llming_com/access/remote.py`, `llming_com/mcp/`, `llming_com/server/p2p/relay/cloudflare/`, and `llming_com/static/p2p/`.
- OpenHort may wrap those primitives for OpenHort-specific host setup, agent-service routing, local config, and documentation, but it should not become the canonical home for generic P2P/proxy transport code.
- If a temporary relay/proxy/viewer implementation exists in OpenHort or the website repo, treat it as migration debt and keep the public contract compatible with `llming-com`.
- QR codes should contain only opaque bootstrap credentials. After pairing, the browser should redirect to a stable viewer/app URL that reads cookies or IndexedDB credentials and initiates future handshakes from storage.

## Current Platform Layout

- The surrounding `openhort_platform` directory was reorganized. Relative path dependencies in `pyproject.toml` can be stale after moves.
- At the moment Poetry should not be assumed to provide a valid environment. Check dependency paths and rebuild/repair the environment before treating Poetry test results as authoritative.
- The existing `.venv` may still be useful as a bootstrap environment, but it can contain absolute paths from the old layout.
