# Llmings — The Panel Architecture

## What is a Llming?

A **llming** is any self-contained interactive panel in openhort. Window streams, terminals, browser previews, and custom plugins are all llmings. They share the same lifecycle, layout, and UI primitives.

## Architecture

```
┌─────────────────────────────────────────────┐
│  Top Toolbar (llming-specific actions)      │
│  ← Back   Title   [custom icons]   Close   │
├─────────────────────────────────────────────┤
│                                             │
│              Llming Content                 │
│  (stream view, terminal, custom panel)      │
│                                             │
├─────────────────────────────────────────────┤
│  Bottom Bar (llming-specific controls)      │
│  [soft keys toggle] [custom buttons]        │
└─────────────────────────────────────────────┘
         ┌──────────────┐
         │ Floating Soft │  (optional, toggleable,
         │ Keys / Tools  │   draggable overlay)
         └──────────────┘
```

Every llming gets:
- **Back button** (returns to grid) — shared
- **Title** — provided by the llming
- **Close button** with Quasar confirmation dialog — shared
- **Custom top toolbar icons** — defined by the llming
- **Custom bottom bar** — defined by the llming (e.g. terminal soft keys, viewer fit controls)
- **Floating overlays** — shared primitives for soft keys, toolbars, palettes

## Base Classes

### Python: `LlmingBase`

```python
class LlmingBase(ABC):
    """Server-side base for all llmings."""

    @property
    @abstractmethod
    def llming_id(self) -> str: ...

    @property
    @abstractmethod
    def llming_type(self) -> str: ...    # "window-stream", "terminal", "custom"

    @property
    @abstractmethod
    def title(self) -> str: ...

    @abstractmethod
    async def handle_message(self, msg: dict) -> None: ...

    async def on_open(self) -> None: ...
    async def on_close(self) -> None: ...
```

### JavaScript: `LlmingBase`

```javascript
class LlmingBase {
    static type = '';              // e.g. 'terminal', 'window-stream'
    static label = '';             // shown in the "New Panel" launcher
    static icon = '';              // Phosphor icon class
    static description = '';       // shown in launcher

    // ---- Lifecycle ----
    setup(app, Quasar) {}          // register Vue components
    destroy() {}                   // cleanup

    // ---- Toolbar configuration ----
    get topActions() { return []; }
    // Each: { icon: 'ph ph-...', title: '...', onClick: fn, active: bool }

    get bottomBar() { return null; }
    // A Vue component name string, or null for no bottom bar

    // ---- Floating overlay ----
    get floatingKeys() { return null; }
    // A Vue component name string for soft keys overlay
}
```

## Built-in Llmings

### Window Stream (`window-stream`)

| Part | Content |
|---|---|
| Top toolbar | Fit (F), Fit-vertical (V), Active mode (I), Overview (G), Settings gear |
| Content | JPEG stream with zoom/pan/fit |
| Bottom bar | — (none, full screen for the stream) |
| Floating | — (minimap appears when zoomed) |

### Terminal (`terminal`)

| Part | Content |
|---|---|
| Top toolbar | — (minimal) |
| Content | xterm.js terminal |
| Bottom bar | Toggle soft keys button |
| Floating | Soft keys overlay (Esc, Tab, Ctrl+C/D/Z, arrows, backspace) — toggleable, draggable |

## Shared UI Primitives

### Floating Toolbar

A draggable, toggleable overlay used for soft keys, tool palettes, etc:

```javascript
// Shared component: 'llming-floating-bar'
// Props: visible, position (bottom-left, bottom-right, etc.)
// Slots: default (buttons/content)
// Features: draggable, toggleable, remembers position in localStorage
```

### Top Toolbar

Shared layout with back button, title, close button. Llmings add custom icons:

```javascript
// Shared component: 'llming-toolbar'
// Props: title, actions (array of {icon, title, onClick, active})
// Slots: left (back), right (close)
```

### Bottom Bar

Shared container at the bottom. Llmings provide their own content:

```javascript
// Shared component: 'llming-bottom-bar'
// Slots: default
// Features: auto-hides when keyboard is open (mobile)
```

## Launcher

The "New Panel" (`+`) card opens the **Llming Launcher** — a searchable grid of available llming types. Each registered llming type appears with its icon, label, and description.

Built-in types are always shown. Extension types are added via `LlmingBase.register()`. Types can be marked as `disabled` (e.g. "coming soon").

## Naming Convention

| Old term | New term |
|---|---|
| Panel | Llming |
| Panel type | Llming type |
| New Panel dialog | Llming Launcher |
| HortExtension | LlmingBase (client) |
| Extension panel | Custom llming |

## Grid Card

Each active llming appears as a card in the landing grid:
- Window stream: live JPEG thumbnail
- Terminal: terminal icon
- Custom: llming-defined icon

The card shows the llming type label and instance title.
