# 🗂 WorkSpace — Windows Session Manager

> Pick up exactly where you left off. Every app, every tab, every file — captured automatically across virtual desktops.

WorkSpace is a Mac-inspired session manager for Windows. It silently tracks everything open on each virtual desktop and lets you restore it all after a reboot — no more hibernating just to preserve your work state.

---

## How It Works

| Action | What Happens |
|---|---|
| `Ctrl + Win + D` | New virtual desktop opens → Spotlight prompt appears to name the session |
| Type a name + `Enter` | Session starts recording: windows, tabs, files |
| `Esc` | Cancel — desktop not tracked |
| `Win + `` ` | Toggle floating HUD showing all sessions |
| Restart PC | Boot normally, open WorkSpace → see all previous sessions → click Restore |

## Features

- **Spotlight-style naming prompt** — appears the moment a new desktop is created
- **Floating HUD** — minimal always-on-top widget, hidden by default
- **Automatic background capture** — snapshots every 5 seconds, silently
- **Chrome tab capture** — all open tabs saved via Chrome DevTools Protocol
- **VS Code workspace detection** — knows which folder you had open
- **Terminal working directory** — restores your terminal in the right folder
- **System tray** — lives quietly in the tray, zero UI clutter
- **SQLite storage** — fast, portable, single-file database in `%APPDATA%\WorkSpace`
- **Startup registration** — optional, runs at login via Windows registry

See [docs/SETUP.md](docs/SETUP.md) for full setup including Chrome tab capture.

## Architecture

See [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) for the full system design.

**Stack:** Python 3.11 · tkinter · SQLite · pyvda · pywin32 · psutil · Chrome DevTools Protocol

## Project Structure

```
src/core/       — daemon, desktop watcher, window/chrome capture, restore
src/ui/         — spotlight, hud, main window, tray, theme
src/db/         — SQLite database, models
src/utils/      — logger, config, startup registration, helpers
```
