# n8n Hosted App Internals

This document records the work needed to make `n8n` run as an openhort hosted app through:

- direct local/LAN access
- P2P access through the hosted viewer and DataChannel transport
- cloud proxy access through `/proxy/{host_id}/...`

The key requirement is that the same `n8n` container instance must work under multiple outer URL shapes without being reconfigured for each mode.

## URL Model

The stable openhort hosted-app entrypoint is:

```text
/app/{instance}/~/
```

Examples:

- local/LAN: `http://localhost:8940/app/workflows/~/`
- local HTTPS dev proxy: `https://localhost:8950/app/workflows/~/`
- cloud proxy: `https://hub.openhort.ai/proxy/{host_id}/app/workflows/~/`

The important distinction is:

- the container should behave as if it lives at `/`
- openhort is responsible for adapting browser-visible URLs to the correct hosted-app prefix

This avoids binding `n8n` to one specific external base URL.

## Why n8n Broke Initially

`n8n` assumes it is effectively mounted at root. Its HTML, JS bootstrap, router base-path handling, dynamic imports, CSS preloads, API calls, and some JSON bootstrap data all contain rooted URLs such as:

```text
/static/base-path.js
/static/prefers-color-scheme.css
/assets/index-....js
/rest/login
```

That works when `n8n` is served directly at `/`, but fails when the app is actually visible at:

```text
/app/workflows/~/
```

or:

```text
/proxy/{host_id}/app/workflows/~/
```

The browser resolves those rooted URLs against the site root and escapes the hosted-app prefix. The immediate symptoms were:

- large numbers of `404` errors for `/assets/...` and `/static/...`
- SPA routes such as `/signin` showing n8n's own 404 page
- frontend crashes because some JSON bootstrap fields were missing in public-mode responses
- URL behavior differing between direct access and proxy access

## Design Decision

The chosen model is:

1. Keep the container configured as root-based.
2. Do not make the container own the outer prefix.
3. Make the openhort hosted-app proxy adapt responses to the browser-visible prefix.

This is the only approach that scales cleanly across:

- LAN access
- P2P transport
- cloud proxy transport

If the container had to know whether it was being viewed at `/app/...` or `/proxy/{host_id}/app/...`, the configuration would become transport-specific and fragile.

## Main Changes in `hort/app.py`

Most of the implementation currently lives in `hort/app.py`.

### 1. Hosted-App Route Shape

Dedicated routes were added for:

```text
/app/{instance}/~/
/app/{instance}/~
/app/{instance}/~/{path:path}
```

`/app/{instance}` now redirects to `/app/{instance}/~/`.

This established one canonical app root and prevented ambiguous behavior around missing trailing segments.

### 2. HTML Bootstrap Injection

The hosted-app proxy injects a bootstrap shim into HTML responses. Its job is to keep browser-side navigation and network calls inside the hosted-app prefix.

The shim patches browser APIs such as:

- `fetch`
- `XMLHttpRequest`
- `WebSocket`
- `EventSource`
- `history.pushState`
- `history.replaceState`

This is needed because some URLs are generated at runtime by the frontend, not only in static HTML markup.

### 3. HTML, JS, and CSS Rewriting

For content types that drive browser loading behavior, openhort rewrites rooted self-references into hosted-app-relative ones.

Examples:

- `"/assets/..."`
- `"/static/..."`
- `"/rest/..."`
- `"/favicon.ico"`
- `"/login"`
- `"/logout"`

This rewriting is applied to:

- HTML
- JavaScript
- CSS
- selected JSON payloads

To make rewriting reliable, the proxy requests upstream content with identity encoding and also supports decompression when needed.

### 4. `Location` Header Rewriting

Upstream redirects that point at root paths are rewritten back into the current hosted-app root.

Without this, redirects would escape from `/app/{instance}/~/...` or from `/proxy/{host_id}/app/{instance}/~/...`.

### 5. WebSocket Forwarding Improvements

The hosted-app WebSocket bridge was extended to preserve more of the original request shape, including query-string handling.

This is important for apps like `n8n`, which can depend on WebSocket endpoints or runtime channels that are not simple path-only sockets.

### 6. Root Asset Fallback

Even after HTML rewriting, some runtime code paths in `n8n` still attempted to request assets from root:

```text
/assets/...
```

To tolerate this, openhort added a root-level asset fallback:

```text
/assets/{path:path}
/favicon.ico
```

The fallback determines the hosted-app instance from:

1. the `Referer`
2. the `ohapp_instance` cookie

and then proxies the request to the correct hosted-app container.

This made dynamic imports and late asset loads much more robust.

### 7. Hosted-App Cookie

HTML responses for hosted apps now set:

```text
ohapp_instance={instance}
```

with a root path.

This cookie supports the root asset fallback described above. It is especially useful when late browser requests no longer preserve enough route context on their own.

### 8. SPA Route Fallback

For GET and HEAD requests that look like frontend routes rather than upstream server endpoints, the hosted-app proxy serves the upstream app shell instead of forwarding the literal route to `n8n`.

This was required for routes such as:

```text
/app/workflows/~/signin
```

Before this fallback, the request was proxied upstream as a literal `/signin` server path and n8n rendered its own in-app 404 screen.

After the fix, SPA routes resolve through the frontend router as intended.

### 9. `window.BASE_PATH` Fix

`n8n` uses `window.BASE_PATH` for router setup in production builds. A critical bug was that the app still saw a relative or root base instead of the actual hosted-app path.

The hosted-app proxy now rewrites `static/base-path.js` so it returns the real browser-visible base:

```javascript
window.BASE_PATH = "/app/workflows/~/";
```

This is one of the most important fixes in the whole integration. Without it:

- router navigation can escape the hosted-app root
- SPA routes resolve incorrectly
- assets and lazy-loaded chunks can break again after initial page load

## JSON Normalization for n8n

One class of failures had nothing to do with subpaths. The `n8n` frontend assumed that some public bootstrap/settings responses always contained fields that were actually absent.

This surfaced as frontend crashes such as:

- reading `license.planName`
- reading `security.blockFileAccessToN8nFiles`
- reading `enterprise.projects.team.limit`

To stabilize startup, the hosted-app proxy now normalizes selected JSON responses, most importantly `/rest/settings`.

Defaults currently injected include:

```json
{
  "license": {
    "planName": "Community",
    "consumerId": null,
    "environment": "production"
  },
  "security": {
    "blockFileAccessToN8nFiles": false
  },
  "concurrency": -1,
  "pruning": {
    "isEnabled": false
  },
  "versionNotifications": {
    "enabled": false
  },
  "banners": {
    "dismissed": []
  },
  "versionCli": "",
  "enterprise": {
    "projects": {
      "team": {
        "limit": 0
      }
    }
  }
}
```

This normalization is intentionally pragmatic. It keeps the n8n UI from crashing in hosted-app mode while still reflecting a non-enterprise, non-configured environment.

## JSON Self-URL Rewriting

Some n8n JSON responses also leaked internal absolute URLs such as:

```text
http://localhost:5678/rest/...
```

Those are rewritten by the hosted-app proxy to the visible hosted-app path, for example:

```text
/app/workflows/~/rest/...
```

Without this, the frontend could recover from the initial asset load only to break again when later bootstrap data pointed it back at the raw container origin.

## Why `N8N_PATH` Was Not the Right Fix

An earlier direction used `N8N_PATH` or similar settings to try to mount the app under a path.

That approach is too rigid for openhort because the same app instance must survive both:

- direct hosted-app access at `/app/{instance}/~/...`
- cloud access at `/proxy/{host_id}/app/{instance}/~/...`

Those are different external paths. Baking one of them into the container only solves one transport and breaks the other.

The correct architecture is:

- container owns app logic
- openhort owns path adaptation

## Debugging Lessons

### Stale Server Processes Caused Major Confusion

During development, the largest source of false negatives was stale `uvicorn` processes still bound to port `8940`.

This produced a confusing pattern:

- code changes were correct
- container behavior looked fine
- but the browser still received old HTML or old rewrite behavior

The fix was to explicitly identify and kill the stale listener and then restart one clean server process.

When debugging hosted-app behavior, always verify the actual live response from the server that owns port `8940`.

### Verify Browser-Facing Outputs, Not Just Upstream Container Behavior

Useful checks were:

- `GET /app/workflows/~/`
- `GET /app/workflows/~/signin`
- `GET /app/workflows/~/static/base-path.js`
- `GET /app/workflows/~/rest/settings`
- `HEAD /app/workflows/~/assets/...`
- `HEAD /assets/...` with hosted-app cookie context

It was not enough to verify that the upstream `n8n` container returned `200`. The critical question was whether the openhort proxy emitted browser-correct responses.

## Current State

At the time of writing, the integration has progressed from total startup failure to a substantially working hosted-app load:

- initial HTML loads through the hosted-app proxy
- static assets and dynamic chunks load
- router base-path handling is corrected
- SPA routes such as `/signin` are handled through the app shell
- public settings payloads are normalized enough to avoid several frontend crashes
- the user can already reach the UI far enough to run app events and see meaningful interface state

The console still shows:

```text
GET /app/workflows/~/rest/login 401 Unauthorized
```

This is expected for anonymous startup and, by itself, is not a hosted-app bug.

## Known Risks and Follow-Up Work

The current implementation is intentionally targeted and pragmatic. It is good enough to prove and run the integration, but it should eventually be refactored out of `hort/app.py` into a more explicit hosted-app adaptation layer.

Areas to watch:

- more `n8n` JSON responses may require normalization or self-URL rewriting
- more hosted apps may need app-specific rules beyond generic path adaptation
- WebSocket behavior should be verified in real interactive flows, not only during page bootstrap
- cloud proxy behavior must continue to be checked alongside direct `/app/{instance}/~/...` access
- the root asset fallback is useful, but the long-term preference is still for the app to stay inside explicit hosted-app URLs whenever possible

## Core Principle

The most important conclusion from this work is:

> hosted apps must be transport-agnostic

That means:

- the app container should not know whether the user arrived via LAN, P2P, or cloud proxy
- openhort must present a stable app environment and rewrite browser-facing details to match the current outer URL

That principle is what made `n8n` viable across both proxy and P2P paths.
