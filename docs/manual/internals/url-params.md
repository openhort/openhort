# URL Parameters (Deep Linking)

The home screen honours a small set of query-string parameters so that any
view state worth bookmarking, sharing, or routing into can be expressed as a
single URL. Apply order on every load (and on every back/forward navigation):
**`desktop` → `app`**.

## Parameters

| Param | Value | Behaviour |
|---|---|---|
| `desktop` | integer (0-based) | Switch to the Nth desktop on load. Out-of-range values are clamped to `[0, desktops.length - 1]`. Survives history navigation. |
| `app` | llming id (e.g. `weather`, `cameras`, `now-playing`) | Open the named llming. Default mode is **window** for non-fullscreen-capable llmings, **fullscreen** for `fullscreenCapable` llmings (e.g. `llming-lens`). |
| `mode` | `window` \| `fullscreen` \| `widget` | Explicit mode override — see below. Has no effect without `app`. |

### `mode` values

- **`window`** — always open as a hovering float, even for `fullscreenCapable` llmings on small screens.
- **`fullscreen`** — always navigate to the full-screen llming view, even on a 4K monitor where the default would be float.
- **`widget`** — no-op for opening. Used by share links that want to land the user on a specific desktop with the widget already on the grid (no popup). Effectively the same as omitting `app`, but explicit so the URL semantics are clear.

## Examples

```
/                                  →  default home screen
/?desktop=2                        →  open the third desktop
/?app=weather                      →  pop the weather window on the home desktop
/?app=llming-lens&mode=fullscreen  →  force fullscreen even on big screens
/?app=cameras&mode=window          →  force float even on small screens
/?desktop=1&app=now-playing        →  desktop 1 + music window
/?desktop=3&app=hort-chief&mode=widget  →  desktop 3, no popup
```

## Llmings without a UI

Some llmings (connectors like `claude-cli-ext`, background workers like
`hort-chief`) have no `card.vue` and no `app.vue`. Opening them via `?app=`
still produces a small placeholder float ("this llming has no UI yet")
instead of failing silently. This keeps share links from looking broken when
the recipient lands on a llming that hasn't grown a UI yet.

## Idempotency

The parser tracks the last-applied `app|mode` key. Re-running the parser
with the same key (e.g. when `popstate` fires for a back-navigation that
lands back on the same URL) is a no-op — the existing window stays open
instead of being torn down and re-created.

## Open / close round-trip with the URL

The URL is the single source of truth for which app is open. Every open
and close path goes through it, so browser history Just Works:

| User action | What happens |
|---|---|
| Click widget on grid | `history.pushState({_whFloat: true}, '', '?app=NAME&mode=window')` then re-parse. Parser sees a new `app`, opens the float. |
| Click X / Esc / backdrop | If `history.state._whFloat` was set (we pushed), do `history.back()` — the popstate fires the parser, which sees no `app` and closes the float. Otherwise (deep-link entry, no in-app history) `replaceState` removing `app=` and `mode=`, then re-parse. Either way the float closes and the URL no longer points at the app. |
| Browser ← back | `popstate` → parser → `app` differs from `_appliedAppKey` → closes the previously-opened float. |
| Browser → forward | `popstate` → parser → `app` reappears → re-opens the float. |
| Reload mid-app | `?app=...` is in the URL on initial load; the parser opens the float as soon as manifests are ready. |

The `_appliedAppKey` guard means: if the parser sees the URL transition
*away* from an app it previously opened, it closes that app's float.
Conversely, if it sees a new app appear in the URL (and manifests are
ready), it opens it. The two halves of the contract are symmetric.

Implementation note: `window.__hortCloseApp(id)` is the single close path
all UI surfaces (X button, backdrop click, escape key) route through.

## Escape always closes the topmost app

Pressing **Esc** anywhere — including inside a sandboxed iframe — closes
the topmost open app, with one exception: the app can intercept it.

How it works:

- Each iframe scaffold (`card-host.html`, `app-host.html`) listens for `keydown` and posts `app.escape` to the parent.
- The bridge re-dispatches a synthetic `keydown` event on the host document, so the host's global handler fires regardless of where focus was.
- The handler routes through `window.__hortCloseApp(id)`, which negotiates with the iframe via the **beforeClose** protocol below.

This means an unfocused iframe and a focused iframe both close on Esc — the user never gets stuck.

## App-level close interception (`onBeforeClose`)

Apps that hold unsaved state (text editors, edit dialogs, in-flight forms) need to ask the user before closing. The shim exposes:

```js
// inside an app.vue / card.vue setup()
import { inject } from 'vue'
const $llming = inject('llming')

$llming.onBeforeClose(async () => {
  if (!hasUnsavedChanges.value) return true   // allow close
  const ok = await Quasar.Dialog.create({
    title: 'Discard changes?',
    message: 'You have unsaved edits.',
    cancel: true,
  }).onOk(() => true).onCancel(() => false)
  return ok                                    // false = veto, true = proceed
})

// later, when the app finished its own confirm flow and is ready to go:
$llming.closeSelf()
```

Contract:

- The host calls `requestClose(llmingId)` on every close (X button, Esc, backdrop click). The bridge posts `app.beforeClose` to every iframe of that llming and waits up to **250 ms** for `app.beforeCloseResponse`.
- **Default = allow.** A missing handler, a buggy handler, or a slow one (>250 ms) does not block the close — the user is never trapped in an app.
- A handler returning `false` (or a Promise resolving to `false`) means "I'm handling this — don't close yet". The app then owns the close flow.
- When the app is ready to close (after its own confirm dialog accepted), it calls `$llming.closeSelf()`. The bridge sets a one-shot bypass flag so the next `__hortCloseApp` call skips the negotiation and closes immediately.
- Multiple iframes of the same llming (widget + float + fullscreen) all get the request; if any vetoes, the close is cancelled.

This is an opt-in mechanism — apps that don't register a handler get the default behaviour (close immediately).

## Open programmatically

JavaScript callers should use `LlmingClient.openLlming(id, sub, opts)`
directly (it's the same code path the URL parser uses):

```js
LlmingClient.openLlming('weather');                       // window
LlmingClient.openLlming('weather', null, { mode: 'fullscreen' });
LlmingClient.openLlming('llming-wire', 'thread/abc');     // sub-route → fullscreen
```

For URL-driven navigation:

```js
history.pushState({}, '', '/?app=weather&mode=window');
window._applyHortUrlParams();  // re-parse + apply
```

(`_applyHortUrlParams` is exposed on `window` for exactly this case.)

## Implementation

| File | Concern |
|---|---|
| `hort/static/index.html` | `_applyHortUrlParams()` — desktop switch + open delegation |
| `hort/static/vendor/hort-ext.js` | `LlmingClient.openLlming(id, sub, opts)` — manifest lookup, mode resolution, float vs navigate |

The parser fires from four points (in order of likely arrival):

1. After `HortPlugins.discoverAndLoadPlugins()` resolves in the WS-connect callback.
2. From `HortPicker.onMounted` — exposes `state.desktops` to the parser.
3. From a `watch(state.desktops.length)` — fires when the IndexedDB layout finishes loading.
4. On every `popstate` event.

Calling the parser before manifests or desktops are ready is safe: the
`app=` branch only runs when `HortPlugins.getPlugins().length > 0`, and the
`desktop=` branch only runs when `state.desktops.length > 0`. Each branch
is idempotent (the `_appliedAppKey` guard prevents double-opening).

## See also

- [UI Concepts](ui-concepts.md) — the broader widget / desktop / app model.
- [SPA Navigation](../develop/spa-navigation.md) — the History API router used for sub-routes.
- [Card Sandbox](security/card-sandbox.md) — why card-host vs app-host pick different scaffolds.
