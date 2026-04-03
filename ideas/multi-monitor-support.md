# Multi-Monitor Support

Screenshot and input tools currently use CGMainDisplayID() which
captures the primary display only. Need to support multiple monitors.

## What needs to change

- `list_windows` already reports window bounds across all screens
- `screenshot target=desktop` should accept a display index
- Desktop bounds should come from the specific display, not just main
- Input coordinates need to map to the correct display
- SOUL.md should teach the agent about multi-monitor layouts

## API additions

```
screenshot target=desktop display=2    ← second monitor
screenshot target=desktop display=all  ← all monitors stitched
get_display_info                       ← list all displays with bounds
```

## Priority

Low — single monitor covers 90% of use cases. But the architecture
should not make assumptions that block this later.
