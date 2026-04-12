# Llming Development Guide

Build llmings with minimal boilerplate. A llming can be as simple as
a single HTML file or as complex as a full Python + JS application.

## Zero-Config Llming

The simplest llming: a directory with one HTML file.

```
llmings/core/my_dashboard/
  card.html
```

That's it. No manifest, no Python, no JavaScript module. The framework:

- Names it `my-dashboard` (from directory name)
- Serves the HTML as a Quasar card
- Gives it a default icon and size
- Makes it appear in the Spirits grid

### card.html

A pure Quasar/Vue template. The framework wraps it in the card
infrastructure — you just write the content:

```html
<div class="q-pa-md">
  <div class="text-h6">My Dashboard</div>
  <div class="text-subtitle2">{{ time }}</div>
  <q-linear-progress :value="cpu / 100" color="primary" class="q-mt-md" />
  <div class="text-caption">CPU: {{ cpu }}%</div>
</div>

<script>
export default {
  data() {
    return { cpu: 0, time: '' };
  },
  async mounted() {
    // Read from vault
    const data = await this.$llming.vault.get('state');
    if (data.cpu) this.cpu = data.cpu;

    // Subscribe to live updates
    this.$llming.subscribe('system_metrics', (d) => {
      this.cpu = d.cpu_percent;
      this.time = new Date().toLocaleTimeString();
    });
  },
};
</script>
```

### What's available in card.html

Every card template gets these injected:

| API | Description |
|-----|-------------|
| `this.$llming.vault.get(key)` | Read from own vault |
| `this.$llming.vault.set(key, data)` | Write to own vault |
| `this.$llming.vaults(owner).get(key)` | Read other llming's vault |
| `this.$llming.subscribe(channel, handler)` | Subscribe to pulse channel |
| `this.$llming.call(power, args)` | Execute own power |
| `this.$llming.callOn(llming, power, args)` | Execute other llming's power |
| `this.$llming.name` | This llming's name |
| `this.$llming.config` | Llming config from YAML |

Built-in libraries (always available, no imports needed):

| Library | Global | Use case |
|---------|--------|----------|
| Vue 3 | `Vue` | Reactivity, components |
| Quasar | `Quasar` | UI components, dialogs, notifications |
| Plotly.js | `Plotly` | Charts, graphs |
| Three.js | `THREE` | 3D scenes |
| ECharts | `echarts` | Advanced charts |

## Manifest (optional)

If you need more than defaults, add a `manifest.json`:

```json
{
  "name": "my-dashboard",
  "description": "Custom metrics dashboard",
  "icon": "ph ph-chart-bar",
  "version": "0.1.0"
}
```

Everything is optional. Missing fields use defaults:

| Field | Default |
|-------|---------|
| `name` | Directory name (underscores → hyphens) |
| `description` | Empty |
| `icon` | `ph ph-puzzle-piece` |
| `version` | `0.0.0` |
| `entry_point` | `<dir_name>:<ClassName>` (if .py exists) |
| `group` | Empty (own process) |
| `in_process` | `false` |
| `publishes` | `[]` |
| `reads_vaults` | `[]` |

## File Structure

### Minimal (HTML only)

```
my_dashboard/
  card.html          ← Quasar card template
```

### With Python backend

```
my_dashboard/
  manifest.json      ← optional config
  my_dashboard.py    ← Llming class with @power, @on
  card.html          ← card template
  SOUL.md            ← AI prompt (optional)
```

### Full llming

```
my_dashboard/
  manifest.json
  my_dashboard.py    ← main llming class
  card.html          ← grid card (thumbnail)
  app.html           ← full app (opens on card click)
  models.py          ← Pydantic models
  static/
    custom.css
    helpers.js
  SOUL.md
```

## Cards and Apps

Each llming can provide two UI surfaces:

### Card (`card.html`)

Shown in the Spirits grid. Small, glanceable, live-updating.
Renders inside a fixed-size container.

**Sizing** — cards declare min/max sizes in grid units
(roughly 1/4 smartphone width = 1 unit):

```json
{
  "card": {
    "min_width": 1,
    "max_width": 2,
    "min_height": 1,
    "max_height": 2
  }
}
```

| Units | Approximate size |
|-------|------------------|
| 1×1 | Compact icon + number |
| 2×1 | Bar chart or status row |
| 2×2 | Standard card (default) |
| 4×2 | Wide dashboard panel |
| 4×4 | Full-width detailed view |

### App (`app.html`)

Opens when the user clicks the card (or a button on it).
Full-page or floating panel. Has the same API as cards.

```html
<!-- app.html -->
<q-page class="q-pa-md">
  <q-toolbar>
    <q-btn flat icon="arrow_back" @click="$llming.close()" />
    <q-toolbar-title>Hue Bridge</q-toolbar-title>
  </q-toolbar>

  <q-list>
    <q-item v-for="light in lights" :key="light.id">
      <q-item-section>{{ light.name }}</q-item-section>
      <q-item-section side>
        <q-toggle :model-value="light.on"
          @update:model-value="toggleLight(light.id, $event)" />
      </q-item-section>
    </q-item>
  </q-list>
</q-page>

<script>
export default {
  data() {
    return { lights: [] };
  },
  async mounted() {
    const state = await this.$llming.vault.get('state');
    this.lights = state.lights || [];
    this.$llming.subscribe('hue_update', (d) => {
      this.lights = d.lights;
    });
  },
  methods: {
    async toggleLight(id, on) {
      await this.$llming.call('set_light', { light_id: id, on });
    },
  },
};
</script>
```

## Hot Reload

The framework watches all llming directories for changes.
When any tracked file changes while the server is running:

1. Llming is deactivated (clean shutdown)
2. Commands unregistered from CommandRegistry
3. Cards disconnected from viewers
4. Llming reloaded from disk
5. New code activated
6. Cards reconnected, commands re-registered
7. Viewers get a "llming reloaded" event

### Tracked files

By default: `.py`, `.js`, `.css`, `.html`, `.json`, `.md`

Override in manifest:

```json
{
  "watch": ["*.py", "*.html", "*.vue", "templates/*.jinja"]
}
```

### Subprocess handling

- If the llming runs in a subprocess: the subprocess is killed
  and restarted with fresh code
- If the subprocess was running but the main server was down:
  detected on next startup via stale PID + file hash mismatch,
  subprocess is torn down and restarted fresh

### File hashing

Each llming's tracked files are hashed (SHA256) at startup.
The hash is stored in the vault. On every file change detection
or server restart, the hash is compared. Mismatch → reload.

## Offline Cards

Cards can work even when the server is down. The browser caches:

- The card HTML/JS/CSS (service worker or localStorage)
- Last known vault state
- Pending vault writes (synced when server reconnects)

The card shows stale data with a "disconnected" indicator until
the server comes back.

## Examples

### Weather card (HTML only, no Python)

```
weather/
  card.html
```

```html
<div class="q-pa-sm text-center">
  <q-icon name="wb_sunny" size="48px" color="amber" />
  <div class="text-h4">{{ temp }}°</div>
  <div class="text-caption text-grey">{{ city }}</div>
</div>

<script>
export default {
  data() {
    return { temp: '--', city: 'Loading...' };
  },
  async mounted() {
    const data = await this.$llming.vault.get('state');
    this.temp = data.temp || '--';
    this.city = data.city || 'Unknown';
  },
};
</script>
```

### CPU monitor (Python + HTML)

```
cpu_monitor/
  cpu_monitor.py
  card.html
```

```python
# cpu_monitor.py
from hort.llming import Llming, power, on

class CpuMonitor(Llming):
    @on("tick:1hz")
    async def poll(self, _data):
        """Poll CPU every second."""
        import psutil
        self.vault.set("state", {"cpu": psutil.cpu_percent()})
        await self.emit("cpu_update", {"cpu": psutil.cpu_percent()})

    @power("get_cpu", command=True)
    async def get_cpu(self) -> str:
        """Current CPU usage."""
        state = self.vault.get("state")
        return f"CPU: {state.get('cpu', '?')}%"
```

```html
<!-- card.html -->
<div class="q-pa-sm">
  <div class="text-overline">CPU</div>
  <div class="text-h3 text-weight-bold text-primary">{{ cpu }}%</div>
  <q-linear-progress :value="cpu / 100" color="primary" />
</div>

<script>
export default {
  data() { return { cpu: 0 }; },
  async mounted() {
    const s = await this.$llming.vault.get('state');
    this.cpu = s.cpu || 0;
    this.$llming.subscribe('cpu_update', d => { this.cpu = d.cpu; });
  },
};
</script>
```

## Migration from Legacy Cards

Old-style cards (canvas-based `renderThumbnail` in `cards.js`) continue
to work. To migrate to the new HTML card system:

1. Create `card.html` in the llming directory
2. Move rendering logic from `renderThumbnail()` to Vue template
3. Replace `_feedStore(data)` with `this.$llming.vault.get('state')`
4. Replace polling with `this.$llming.subscribe(channel, handler)`
5. Delete `cards.js` (or keep for backward compat)

The framework prefers `card.html` over `cards.js` if both exist.
