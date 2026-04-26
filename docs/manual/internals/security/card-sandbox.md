# Card Sandbox

How openhort enforces — mechanically, not by convention — that a card can only access the vaults, pulses, streams, and powers it has declared a need for.

## Why this exists

openhort runs **server-side** subprocess isolation per llming. A community llming's Python code can't read another llming's Python memory, credentials, or framework internals; that's enforced by process boundaries and the IPC bridge (see [Llming Isolation](../llming-isolation.md)).

Server-side isolation does **not** carry into the browser. Until the card sandbox lands, every compiled `card.vue` runs in the host page's JavaScript context with full access to:

- `window.LlmingClient.getRegistry()` and every other card's class, instance, and Vue refs
- `document.cookie`, `localStorage`, `IndexedDB`, every storage backend the host can reach
- `window.hortWS` — the live control socket (read/write any message)
- The DOM of every other widget

A buggy or hostile card running in this context sees everything the host page sees. Server-side `_authorize` checks (see [Group Isolation](group-isolation.md), [Wiring Model](wiring-model.md)) only catch cross-llming calls that *go through* the WS boundary; nothing stops a card from walking another card's mounted Vue components and reading state directly in-memory.

The card sandbox closes that gap by giving every card its own browser process, declaring its capability set in the manifest, and routing every cross-namespace operation through a host-controlled bridge that authorizes by **forge-proof identity**.

## Sandbox is mandatory

There is **no opt-out**. Every llming with a `ui_widgets` declaration runs sandboxed. The manifest no longer accepts a "trust tier" — historical `trust: 'first-party'` values are rejected at server load with a validation error pointing at this document.

Practical consequences:

- Drop a llming under `llmings/<provider>/<name>/` with `ui_widgets`, no `card.vue` of yours will ever execute in the host page's JS context.
- The audit script (`tools/audit_card_sandbox.py`) is a CI gate — any merge that introduces a forbidden pattern (raw `window.hortWS`, `localStorage`, `document.cookie`, etc.) fails before review.
- "I'll just sandbox the third-party ones" was an earlier, weaker design and is no longer available. First-party cards run under exactly the same isolation as community cards. Maintainer-shipped llmings get audited like every other llming.

The framework-level connector scripts (`lan_connector`, `cloud_connector`, `telegram_connector`) load inline because they extend the host chrome itself, not the widget grid. They do not have `ui_widgets`. If you find yourself wanting to bypass the sandbox for a "real" widget, you're trying to introduce a vector — find the vault/pulse/stream/power equivalent instead.

## Architecture

```
┌─ host page (trusted) ───────────────────────────────────┐
│                                                          │
│  - Real LlmingClient, real WS, real authorize hook       │
│  - WeakMap<Window, llmingId>   identity registry         │
│  - Map<llmingId, Capabilities> capability table          │
│  - Bridge: postMessage in ↔ WS / vault / pulse / stream  │
│                                                          │
│  ┌─ iframe[cameras] ──────┐  ┌─ iframe[email] ────────┐  │
│  │ sandbox=allow-scripts  │  │ sandbox=allow-scripts  │  │
│  │ origin: opaque (null)  │  │ origin: opaque (null)  │  │
│  │                        │  │                        │  │
│  │ Vue + Quasar + card.js │  │ Vue + Quasar + card.js │  │
│  │ vaultRef/useStream/... │  │ vaultRef/useStream/... │  │
│  │     ↓ postMessage      │  │     ↓ postMessage      │  │
│  └────────────────────────┘  └────────────────────────┘  │
└──────────────────────────────────────────────────────────┘
```

Three forge-proof properties make enforcement reliable:

1. **Identity is bound to the iframe reference, not the message payload.** The host puts `(iframeWindow → llmingId)` into a WeakMap when it creates the iframe. Every `postMessage` from that frame is keyed by `event.source` for the lookup. A card cannot claim to be a different llming by changing its message body.
2. **Capability list is stamped at iframe creation from the manifest.** The card cannot widen its own capabilities at runtime — it has no API for that.
3. **`sandbox="allow-scripts"` (no `allow-same-origin`) gives the iframe an opaque origin.** Even though the static asset is served from the host's origin, the iframe is a different origin from the parent and from every other card iframe. No DOM access, no shared storage, no cookie access. The only outbound channel is `window.parent.postMessage`.

This is the same security model VS Code webviews and Telegram Mini Apps use.

## Two persistence APIs: vault vs local

Cards have **two** sanctioned persistence stores. Pick by audience, not by reflex.

| API | Scope | Synced across user's devices? | Use for |
|---|---|---|---|
| `$llming.vault.*` | Per-llming, server-side | **Yes** | Configuration, user preferences, anything that should follow the user (theme, schedules, contacts, accumulated state) |
| `$llming.local.*` | Per-llming, this browser only | **No** | UI ephemera (selected tab, scroll position), render caches, device-specific layout, anything that's meaningless on a different machine |

Both are name-spaced and isolated per llming — one card cannot read another's local store. The local store is backed by IndexedDB on the host (the iframe's own opaque-origin storage is wiped on each load and can't be used directly), accessed through the same postMessage bridge as vault.

```js
// device-local: theme picked on this laptop
await $llming.local.set('panel.collapsed', true)
const collapsed = await $llming.local.get('panel.collapsed', false)

// device-shared: light schedule the user wants on every device
await $llming.vault.set('state', { schedule: [...] })
```

Rule of thumb: **if the data would surprise a user when they open the same llming on their phone, it goes in `local`. If they would expect it to be there, it goes in `vault`.**

The forbidden patterns audit treats raw `localStorage` / `IndexedDB` access the same way it treats raw `window.hortWS`: ban the global, point at the sanctioned API.

## Manifest schema

Cards declare what they need:

```json
{
  "name": "cameras",
  "version": "0.1.0",
  "needs": {
    "vault": [
      "self:state",
      "system-monitor:state.cpu_percent"
    ],
    "pulse": [
      "subscribe:cameras:motion_detected",
      "publish:notifications:critical"
    ],
    "stream": [
      "cameras:*"
    ],
    "powers": [
      "claude_code:send_message"
    ]
  }
}
```

`trust` is no longer settable — every card with `ui_widgets` is sandboxed.

`$llming.local.*` is **always** available without a `needs:` declaration — it operates exclusively on the card's own device-local namespace and never touches another llming's data.

### Capability spec language

Three shapes per capability (vault, pulse, stream, powers):

| Form | Example | Meaning |
|---|---|---|
| `self:KEY` | `self:state` | Own namespace; always implicitly allowed for vault read/write of own keys |
| `OWNER:KEY` | `system-monitor:state.cpu_percent` | Exact key on another llming |
| `OWNER:GLOB` | `cameras:state.*`, `*:tick:*` | Glob-scoped permission |

For pulse, the prefix `subscribe:` or `publish:` selects the operation. For vault, the operation (`read` / `write` / `watch`) is inferred from the call site; if the card needs write access to another llming's vault, declare both: `"vault": ["other:state"]` covers read + watch but not write — declare `"vault_write": ["other:state"]` separately.

### Defaults

- **Deny everything except `self:*`.** Unless the manifest declares a need, the card doesn't get the capability.
- **`trust:` defaults to `sandboxed`** (after the sandbox lands).
- **No implicit cross-llming powers.** If the card needs to invoke `vaults["x"].get` or `call("y", ...)` on another llming, it must be in `needs:`.

## Wire protocol

postMessage between iframe and host. Messages are JSON; binary frames (camera images etc.) flow via blob URLs that the host minted and granted to the iframe.

### Card → host (request)

```js
{ id: 42, op: 'vault.read',     namespace: 'cameras', key: 'state' }
{ id: 43, op: 'vault.write',    namespace: 'self',    key: 'preferences', data: {...} }
{ id: 44, op: 'vault.watch',    namespace: 'system-monitor', key: 'state' }
{ id: 45, op: 'vault.unwatch',  namespace: 'system-monitor', key: 'state' }
{ id: 46, op: 'pulse.subscribe',channel: 'cameras:motion_detected' }
{ id: 47, op: 'pulse.publish',  channel: 'notifications:critical', payload: {...} }
{ id: 48, op: 'stream.subscribe', channel: 'cameras:frontdoor', opts: {...} }
{ id: 49, op: 'stream.ack',     channel: 'cameras:frontdoor' }
{ id: 50, op: 'power.call',     llming: 'claude_code', power: 'send_message', args: {...} }
{ id: 51, op: 'subapp.open',    widget: 'cameras-card', props: {...}, opts: {...} }
{ id: 52, op: 'app.open',       llming: 'system-monitor' }
{ id: 53, op: 'local.read',     key: 'panel.collapsed' }
{ id: 54, op: 'local.write',    key: 'panel.collapsed', data: true }
{ id: 55, op: 'local.delete',   key: 'panel.collapsed' }
{ id: 56, op: 'local.keys' }
```

`local.*` ops carry no `namespace` field — the host always uses the calling iframe's llming id, so a card cannot reach another llming's local store.

### Host → card (reply)

```js
{ id: 42, ok: true,  data: {...} }
{ id: 42, ok: false, error: 'denied: vault.read system-monitor:state' }
```

### Host → card (push)

```js
{ op: 'vault.update',   namespace: 'cameras', key: 'state', data: {...} }
{ op: 'pulse.event',    channel: 'motion_detected', payload: {...} }
{ op: 'stream.frame',   channel: 'cameras:frontdoor', data: 'blob:…' }
```

The iframe-side ACK gate (see [Streams](../../develop/card-api.md)) lives unchanged inside the iframe. The host hands frames over postMessage; the iframe paces consumption and sends `stream.ack` back the same way it does for the in-page version today.

## Host-side enforcement

```js
function onCardMessage(e) {
  const llmingId = iframeIdentity.get(e.source);
  if (!llmingId) return;                           // unknown / orphaned frame
  const caps = capabilities.get(llmingId);
  const msg = e.data;

  if (msg.op === 'vault.read') {
    if (!matchAny(caps.vault_read, msg.namespace, msg.key)) {
      return reply(e.source, msg.id, { ok: false, error: 'denied' });
    }
    realLlmingClient.vault(msg.namespace).get(msg.key)
      .then(data => reply(e.source, msg.id, { ok: true, data }));
    return;
  }
  // …same shape per op
}
```

The `_authorize` hook documented in [Wiring Model](wiring-model.md) and [Group Isolation](group-isolation.md) is invoked by the host on every operation. Same hook, same policy — the sandbox is just the chokepoint that makes the policy unbypassable on the browser side.

## What this prevents

A card can no longer:

- Read another llming's vault via in-memory Vue refs (no shared memory).
- Subscribe to channels it didn't declare (host filters dispatches by capability).
- Call powers on other llmings without explicit permission.
- Read auth cookies, host `localStorage`, host `IndexedDB`, *or another card's* device-local storage (opaque origin + per-llming `$llming.local` namespacing on the host).
- Hook the host's `fetch` / `WebSocket` / `postMessage` to intercept other cards' traffic (different origin, no shared globals).
- Mount UI outside its widget bounding box (iframe is the bounding box; for popups use `subapp.open`).
- Load runtime scripts from arbitrary URLs (CSP forbids it; bundle the dependency).

A compromised card can still misuse what it *was* granted. That is the entire point: the trust surface is exactly the manifest's `needs:` block, and nothing more.

## Forbidden patterns in cards

These are forbidden today by convention; the sandbox makes them mechanical. Card authors should never write:

| Pattern | Sanctioned alternative |
|---|---|
| `window.LlmingClient.getRegistry()` walking, reading other cards' refs | `vaults["x"].get()`, `subscribe("y")`, `call("z")` |
| `document.cookie` | Auth cookies are HttpOnly and unreachable; per-llming state goes in `$llming.vault` (cross-device) or `$llming.local` (device-local) |
| Raw `localStorage` / `sessionStorage` | `$llming.local.set(...)` for device-local data, `$llming.vault.set(...)` for cross-device data |
| Direct `IndexedDB` access | `$llming.local.*` (the host backs it with a per-llming IndexedDB partition) |
| `document.createElement('script')` with an external src | Bundle the dependency at build time |
| `position: fixed` overlays escaping the widget container | `LlmingClient.openSubapp(...)` / `openFloat(...)` |
| Direct access to `window.hortWS` or `window.__hort` | `$llming.*` and the `vaultRef` / `useStream` / `usePulse` composables |

These rules ship alongside the [Card API](../../develop/card-api.md) developer documentation and are enforced by the audit grep in `tools/audit_card_sandbox.py`.

## Migration path

1. Add `trust:` and `needs:` fields to every shipped manifest.
2. Run the audit grep; fix any first-party card that violated the conventions.
3. Land the bridge code in llming-com (protocol + `IframeBridge` + iframe-side shims) and openhort (host-side dispatcher + `_authorize` hook integration).
4. Flip llmings to `trust: 'sandboxed'` one at a time. First-party cards can stay `'first-party'` during the transition.
5. Once every first-party card runs sandboxed without regression, switch the default `trust:` from `first-party` to `sandboxed`. Cards that opt back in to `first-party` need maintainer sign-off.
6. Accept community llmings — they ship with `trust: 'sandboxed'` (the only allowed value for unreviewed sources).

## Sharing state across widget, subapp, and fullscreen

A single llming can be visible at once as: a widget on Home, the same widget on Smart Home, an open subapp window, and a fullscreen app. Each of those is its own iframe — its own JS context, its own Vue instance, its own globals. **They cannot share JavaScript variables, in-memory caches, or Vue refs directly.** They share state through the host bridge.

The bridge is the single source of truth for cross-instance data. Every iframe of `cameras` reads/writes to the same vault key, the same `local` IndexedDB row, the same pulse channel. The host fans changes out to every subscribed iframe of that llming.

### Recipe — cross-instance device-local state (`localRef`)

Use when: this device should remember a value across reloads, but it should NOT sync to the user's other devices. Examples: which tab is selected, scroll position, "panel collapsed", a render-time cache.

```vue
<script setup>
const collapsed = $llming.localRef('panel.collapsed', false)
// Reading: collapsed.value
// Writing: collapsed.value = true   ← every other iframe of this llming sees the change on next tick
</script>

<template>
  <button @click="collapsed = !collapsed">{{ collapsed ? 'Expand' : 'Collapse' }}</button>
</template>
```

Mechanism: `localRef` registers a `local.watch` with the host. The host stores the value in a per-llming IndexedDB row (`hort-card-local` DB, key = `(llmingId, 'panel.collapsed')`). Every `local.write` triggers a `local.update` push to *every* iframe of the same llming, which updates their reactive ref. No polling, no manual sync, no echo (the writing iframe suppresses its own update).

### Recipe — cross-device shared state (`vault` / `vaultRef`)

Use when: the value should follow the user across all their devices. Examples: light schedules, contacts, anything the user expects to find on their phone too.

```vue
<script setup>
const schedule = vaultRef('self', 'state.schedule', [])
// Reading: schedule.value
// Writing: $llming.vault.set('state', { schedule: [...] })
</script>
```

Mechanism: same fan-out to every iframe of the llming, plus the value is persisted server-side and replicated across the user's devices.

### Recipe — cross-instance live events (`pulse`)

Use when: something happened *now* and every open instance should react. Examples: motion detected, song changed, build finished.

```vue
<script setup>
$llming.subscribe('motion_detected', payload => {
  // every iframe of this llming with a subscriber gets the same payload
})

// elsewhere (with `pulse: ["publish:cameras:motion_detected"]` declared):
function onMotion(camId) {
  $llming.emit('motion_detected', { cam: camId, at: Date.now() })
}
</script>
```

### Recipe — cross-instance binary streams

Already automatic. `useStream('cameras:frontdoor', ...)` from N iframes of the cameras llming gets fanned out by the host bridge — each iframe has its own ACK gate, the upstream is subscribed once.

### What you cannot do

| Want | Why it doesn't work | Use this instead |
|---|---|---|
| `window.someGlobal = ...` to share with the subapp | Each iframe has its own `window` | `localRef` (device-local) or `vaultRef` (cross-device) |
| `import { someState } from './shared.js'` between widget and app | Each iframe imports a fresh copy | `localRef` / `vaultRef` |
| In-memory cache shared across iframes | No shared memory; opaque-origin storage is fresh per iframe | `localRef` (host IndexedDB is the cache) |
| `BroadcastChannel` between iframes | Opaque origins can't share a channel | `pulse` (host fan-out) |
| Same `SharedWorker` from all iframes | Origin must match — opaque origins can't | `pulse` |

The framework's "every iframe of one llming sees the same data" property is **not** an emergent behaviour — it's the explicit shape of the bridge. Any sharing pattern that doesn't go through the bridge will not survive the sandbox.

## Permission contract — what the author is responsible for

The framework enforces capabilities. **The author is responsible for declaring them honestly.** The contract is small and explicit:

1. **Every cross-llming access must be declared.** Every `vaultRef('other', ...)`, every `useStream('other:...')`, every `$llming.subscribe('other:channel')`, every `$llming.callOn('other', 'power', ...)` corresponds to one entry in the manifest's `needs:` block. Self access (`self:*`) is implicit and need not be declared.
2. **No declaration → no access.** Undeclared operations are denied at the host bridge with a loud `console.warn` showing exactly which manifest entry would have allowed it. The card author sees the message in the host devtools and knows what to add (or what to stop using).
3. **Declared but unused capabilities are a smell.** The audit tool (`tools/audit_card_sandbox.py`) flags entries in `needs:` that aren't referenced by any card source file. Tighten or remove.
4. **Glob with intent.** `system-monitor:state.cpu_percent` is preferred over `system-monitor:state.*`. Wildcards exist for cases where the consumer genuinely doesn't know the key shape upfront.
5. **Pulse needs the operation.** Pulse entries are `subscribe:owner:channel` or `publish:owner:channel`. A card that only listens shouldn't be allowed to emit on the same channel.
6. **Powers identify the target.** `claude_code:send_message` — the target llming and the specific power name. `*:*` is not accepted; if you need broad access, that's a sign the design needs revisiting.

The bridge logs every denial to the host console with this format:

```
[card:cameras] denied vault.read system-monitor:state — add to manifest needs:
    "needs": { "vault": ["system-monitor:state"] }
```

Card authors who write code that needs an undeclared capability see this message immediately. There is no silent failure.

## Device-local storage backing

`$llming.local.*` is backed by a **single host-owned IndexedDB database** (`hort-card-local`) with one object store keyed by `(llmingId, key)`. The card never touches IndexedDB directly; the host opens the DB once, namespaces every request, and proxies reads/writes through the bridge.

Why host-owned and not iframe-owned:

- An `<iframe sandbox="allow-scripts">` runs in an opaque origin. Browsers give opaque origins a **fresh** storage partition on every load — anything written there is gone after a refresh. Useless for persistence.
- Host-owned IndexedDB persists normally and survives reloads, the same as any other openhort device-local data (widget layout, demo-mode preference).
- Centralising storage in the host means one quota, one backup story, one place for `$llming.local.clear(name)` if the user uninstalls a llming.

The host enforces:

- Each `local.*` op gets the calling iframe's llming id by `WeakMap` lookup. The card cannot ask for another llming's local data.
- Quota per llming (default 5 MB; configurable per-llming in the manifest if a card legitimately needs more).
- Eviction order on quota pressure: oldest writes first; the card receives a pulse-style `local.evicted` notification.

## Where the code lives

| Concern | Location |
|---|---|
| Wire protocol (message types, schemas) | `llming-com/docs/card-bridge-protocol.md` |
| Iframe-side shim (vaultRef, useStream, $llming, openSubapp) | `llming-com/static/llming-card-client.js` |
| Host-side bridge (identity registry, dispatcher, capability check) | `llming-com/static/llming-card-host.js` |
| Vue framework helpers built on the shim | `llming-com-vue/` (separate package) |
| Manifest schema (`trust`, `needs`) | `llming-com/llming_com/manifest_schema.py` |
| Authorize hook contract | `llming-com/llming_com/authorize.py` |
| Hort-specific authorize policy (wiring + groups) | `hort/security/authorize.py` |
| Iframe scaffold (cards, lightweight — no Quasar) | `hort/static/card-host.html` |
| Iframe scaffold (apps, full Quasar) | `hort/static/app-host.html` |
| Audit script | `tools/audit_card_sandbox.py` |

## Card vs App scaffold

There are **two iframe scaffolds**, picked by the rendering surface:

| Surface | Scaffold | Loads | Used for |
|---|---|---|---|
| Widget tile (home grid) | `card-host.html` | Vue + Phosphor + hort.css | The card.vue — must be lightweight to keep cold-load fast (19 widgets × full Quasar = 6s+ in earlier iterations). |
| Float window / fullscreen view | `app-host.html` | Vue + **Quasar** (UMD + CSS) + Phosphor + hort.css | The app.vue when present, falls back to card.vue. Apps are typically richer (forms, dialogs, charts) and are allowed to use the full Quasar component library (`<q-btn>`, `<q-input>`, etc.). |

Both scaffolds use the same `card-shim.js` runtime and the same postMessage protocol, so the `$llming.*` API surface is identical. The only difference is whether Quasar is registered with the iframe's Vue app.

**Cold-load consequence:** dropping Quasar from card-host.html cut widget-grid cold load from ~6 s to ~2.2 s on a 19-widget home desktop. Cards that need a button/input use plain `<button>` / `<input>` styled with hort.css variables — see `tools/audit_card_sandbox.py` (which flags raw Quasar tags in card.vue files).

**Bridge `init` payload now includes both URLs:**
```js
{
  op: 'init',
  llmingId: 'weather',
  scriptUrl: '/ext/weather/static/cards.js',     // compiled card.vue
  appScriptUrl: '/ext/weather/static/app.js',    // compiled app.vue (or '')
  widget: 'weather-app' | 'weather-card',         // which component to mount
  props: {...},
  capabilities: {...},
}
```

App-host loads both scripts (so an app.vue can reference card components). Card-host ignores `appScriptUrl`.

**CORS for fonts:** sandboxed iframes have an opaque origin, so same-origin asset fetches become cross-origin from the iframe's POV. Fonts loaded via `@font-face` need `Access-Control-Allow-Origin: *` or they render as boxes. The static-files middleware in `hort/app.py` adds this header on `/static/`, `/ext/`, and `/sample-data/` responses.

**Click forwarding for cards (not apps):** card-host.html listens for clicks on non-interactive areas (anything not inside `button, input, select, textarea, a, label, [role=button], [data-stop]`) and posts `card.click` to the host. The bridge re-dispatches a click on the parent `.widget` element, so the home-grid `onWidgetClick` handler still fires through the iframe boundary. App-host does NOT do this — apps own their click handling.

## Warm app-iframe pool

Loading an `app-host.html` iframe cold is slow — Vue + Quasar sum to ~700 KB of JS to parse in a fresh V8 context, plus Quasar CSS. To keep the open-app gesture feeling instant, the host maintains a **single warm iframe** at all times:

```
page load                   user opens app                user closes app
─────────                   ──────────────                ───────────────
warm = create_iframe()  →  acquire(warm)              →  destroy(used)
                            (post init, mount)           refill: warm = create()
```

| Stage | Detail |
|---|---|
| **Create** | After page load, an idle-callback creates a hidden iframe at body level (`position:fixed; left:-9999px; visibility:hidden`) pointing at `/static/app-host.html` with **no `?llming=` param**. Its handshake is sent with empty id and the bridge ignores it — the iframe just sits at the "waiting for init" state, with Vue + Quasar fully parsed. |
| **Acquire** | When a float opens, `_HortAppPool.acquire()` returns the warm iframe (and schedules a refill). The bridge's `acquireWarm(iframe, llmingId, widget, props)` registers identity on the existing `contentWindow` and posts the `init` message — the iframe starts mounting the app immediately, no parse cost. |
| **Position** | The iframe is *never re-parented* (Chrome reloads iframes when their parent changes, killing the warm context). It stays at body level; the `hort-app-frame` Vue component renders an empty slot div inside the float body and a `requestAnimationFrame` loop syncs the iframe's `position: fixed` rect to the slot's `getBoundingClientRect()`. The iframe follows the float through drag, resize, scroll, and minimize. |
| **Destroy** | When the float closes, the bridge unregisters identity and the iframe is removed from the DOM. The pool then schedules a new warm iframe so the next open is again ~50 ms instead of ~1-2 s. |

**Measured impact:** first app open dropped from ~1-2 seconds (cold parse) to ~70 ms (warm). Subsequent opens are ~50 ms because the pool refills in the background during the previous app's lifetime.

**Why not re-parent the iframe?** Moving an iframe between DOM parents triggers a full reload in Chromium-family browsers (and unspecified in WebKit). The `position: fixed` overlay sidesteps this cleanly: the iframe's position in the document tree never changes, only its CSS coords.

**Why one and not a pool of N?** The current UX has at most one app open at a time. If multiple concurrent floats become a feature, the pool can grow trivially (`acquire()` returns from a queue of warm iframes; `scheduleWarm` keeps the queue at length N).

Implementation: `window._HortAppPool` in `hort/static/index.html`, plus `HortCardBridge.acquireWarm` / `destroyAcquired` in `hort/static/vendor/hort-card-bridge.js`.

## Threat model

The sandbox assumes the card is potentially hostile. It does **not** protect against:

- A compromised host page (XSS in the host wins everything; defended by CSP and same-origin policy on the host's resources).
- A network adversary (defended by TLS).
- A compromised server (defended by container/process isolation, see [Container Security](container-security.md)).
- A user who installs a malicious card and grants it broad capabilities anyway (capability declaration is *informed consent*; the user needs to read the manifest's `needs:` block before installing — surfaced in the install UI).

It **does** protect against:

- A card reading another card's data without declared permission.
- A card calling another card's powers without declared permission.
- A card escaping its widget area into the host chrome.
- A card exfiltrating cookies / storage / session state from the host.

## See also

- [Wiring Model](wiring-model.md) — declarative cross-llming connections (the policy the host enforces).
- [Group Isolation](group-isolation.md) — colored groups and zone semantics.
- [Llming Isolation](../llming-isolation.md) — server-side subprocess isolation (the parallel mechanism on the Python side).
- [Threat Model](threat-model.md) — full system threat model.
- [Card API](../../develop/card-api.md) — developer-facing surface for writing cards.
