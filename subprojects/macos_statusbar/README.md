# hort-statusbar

macOS status bar app for openhort. Sits in the menu bar and lets you start/stop the server, see connected viewers, prevent sleep, and more.

## Usage

```bash
python -m hort_statusbar
```

## Features

- Start/stop the openhort server from the menu bar
- Live viewer count — see who's connected
- Sleep prevention (IOPMAssertion) — keeps Mac awake while serving
- Viewer warning overlay — floating banner when someone is watching
- Auto-start on login (LaunchAgent)
- Permission checks (Screen Recording, Accessibility)
