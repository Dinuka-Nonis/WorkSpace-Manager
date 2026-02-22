# ⊞ WorkSpace Manager

> **Mac Continuity, built for Windows.**  
> Every virtual desktop gets a named session. Every app, Chrome tab, and file gets saved. One hotkey to see it all. One click to restore.

---

## What It Does

When you press `Ctrl+Win+D` to open a new Windows virtual desktop, WorkSpace immediately asks you to **name that context** (e.g. "OS Lab 3" or "Web Dev Auth Module"). From that moment on, it silently tracks:

- **Every open window** — VS Code, terminals, PDF viewers, Postman, etc.
- **Every Chrome tab** — via a lightweight Chrome Extension
- **Time spent** — how long each session has been active

When you restart your PC or want to pick up where you left off, just open WorkSpace and click **Restore** — everything relaunches exactly as you left it.

---

## Architecture

```
┌─────────────────────────────────────────────────────┐
│                  WorkSpace App                      │
│                                                     │
│  ┌─────────────┐    ┌──────────────┐               │
│  │  Spotlight  │    │  Floating    │               │
│  │  Prompt     │    │  HUD         │               │
│  │  (PyQt6)    │    │  (PyQt6)     │               │
│  └──────┬──────┘    └──────┬───────┘               │
│         │                  │                        │
│  ┌──────▼──────────────────▼───────┐               │
│  │         Core Daemon             │               │
│  │  - Virtual desktop poller       │               │
│  │    (pyvda, every 500ms)         │               │
│  │  - Window snapshot engine       │               │
│  │    (win32gui + psutil, 30s)     │               │
│  │  - Session time tracker         │               │
│  │  - Qt signal/slot wiring        │               │
│  └──────────────┬──────────────────┘               │
│                 │                                   │
│  ┌──────────────▼──────────────────┐               │
│  │         SQLite Database         │               │
│  │  sessions / windows / tabs      │               │
│  └─────────────────────────────────┘               │
│                                                     │
│  ┌─────────────────────────────────┐               │
│  │  Chrome Extension + Native Host │               │
│  │  (background.js → host.py)      │               │
│  └─────────────────────────────────┘               │
└─────────────────────────────────────────────────────┘
```

---

## Project Structure

```
workspace_manager/
├── main.py                  ← Entry point. Run this.
├── daemon.py                ← Core daemon (desktop poller + snapshotting)
├── db.py                    ← SQLite database layer
├── snapshot.py              ← Window enumeration (win32gui + pyvda)
├── restore.py               ← Session restore engine
├── setup.py                 ← One-time setup script
├── requirements.txt
│
├── ui/
│   ├── spotlight.py         ← Mac Spotlight-style naming prompt
│   ├── hud.py               ← Floating HUD (toggle with Win+`)
│   ├── main_window.py       ← Full session dashboard
│   └── styles.py            ← Dark theme QSS stylesheet
│
├── chrome_extension/
│   ├── manifest.json        ← Chrome extension manifest (MV3)
│   ├── background.js        ← Service worker (tab capture + native messaging)
│   └── popup.html           ← Extension popup UI
│
└── native_host/
    ├── host.py              ← Native messaging host (Chrome ↔ SQLite bridge)
    └── install_host.py      ← Registers host in Windows registry
```

---

## Installation

### 1. Prerequisites

- **Windows 10/11** (virtual desktop APIs are Windows-only)
- **Python 3.11+**
- **Google Chrome**

### 2. Quick Setup

```bash
# Clone or download the project
cd workspace_manager

# Run the setup script
python setup.py
```

The setup script will:
- Install all Python dependencies (`pip install -r requirements.txt`)
- Initialize the SQLite database
- Set up the Chrome Native Messaging Host
- Optionally add WorkSpace to Windows startup

### 3. Manual dependency install

```bash
pip install PyQt6 pywin32 pyvda psutil keyboard Pillow requests
```

> **Note:** `keyboard` requires running as Administrator for global hotkeys. Right-click `main.py` → "Run as administrator", or use the `Win+`` hotkey alternative.

---

## Chrome Extension Setup

1. Open **chrome://extensions/**
2. Enable **Developer Mode** (top-right toggle)
3. Click **Load Unpacked** → select the `chrome_extension/` folder
4. **Copy the Extension ID** shown under "WorkSpace Manager"
5. Open `AppData\Roaming\WorkSpaceManager\native_host\com.workspace.manager.json`
6. Replace `REPLACE_WITH_EXTENSION_ID` with your actual extension ID
7. Run: `python native_host/install_host.py` again

---

## Usage

### Starting WorkSpace

```bash
python main.py
```

WorkSpace runs in the **system tray** (bottom-right of taskbar). Double-click the tray icon to open the dashboard.

### Hotkeys

| Hotkey | Action |
|--------|--------|
| `Ctrl + Win + D` | Create new virtual desktop → triggers session naming |
| `Win + `` ` | Toggle floating HUD |
| `Win + Shift + S` | Force snapshot of current desktop |
| `Esc` | Close Spotlight / HUD |
| `Enter` | Confirm session name in Spotlight |

### Workflow

1. Press `Ctrl+Win+D` to open a new virtual desktop
2. A **Spotlight prompt** appears — type your session name (e.g. "OS Lab 3 — Scheduling")
3. Press `Enter` to start tracking, `Esc` to cancel
4. Work normally — WorkSpace quietly snapshots your windows every 30 seconds
5. Press `Win+`` ` anytime to see the **floating HUD** with all your sessions
6. After a restart, open the dashboard and click **Restore** to relaunch everything

---

## Restore Capabilities

| What | Restored | Method |
|------|----------|--------|
| Chrome tabs | ✅ Full | Reopen all saved URLs |
| VS Code | ✅ Full | `code /path/to/folder` |
| Terminals | ✅ Full | Reopen Windows Terminal / cmd |
| PDF viewers | ⚠️ File path | Reopen file (not scroll position) |
| Other apps | ⚠️ Best-effort | Relaunch `.exe` |

---

## Configuration

Database is stored at:
```
%APPDATA%\WorkSpaceManager\workspace.db
```

Snapshot interval: edit `SNAPSHOT_INTERVAL_MS` in `daemon.py` (default: 30,000ms)  
Desktop poll rate: edit `DESKTOP_POLL_MS` in `daemon.py` (default: 500ms)

---

## Known Limitations

- **`Ctrl+Win+D` cannot be intercepted** — Windows handles this at kernel level before any user app. WorkSpace detects new desktops by polling the desktop count every 500ms, which adds a ~0–500ms delay before the Spotlight prompt appears.
- **`keyboard` library needs admin** for global hotkeys on some systems. Alternatively, you can add a system tray shortcut to toggle the HUD.
- **App restore is best-effort** — apps that don't support command-line arguments for reopening specific files (e.g. custom tools) will just relaunch to their default state.

---

## Troubleshooting

**Spotlight doesn't appear when I create a new desktop:**  
→ The poller runs every 500ms. Wait a second after pressing `Ctrl+Win+D`. If it still doesn't appear, check that pyvda is installed: `pip install pyvda`

**"keyboard" hotkeys not working:**  
→ Run `main.py` as Administrator. Or use the tray icon menu instead.

**Chrome tabs not saving:**  
→ Ensure the extension is loaded in Chrome and the native host is installed. Check `chrome://extensions/` and verify the Extension ID matches in the host manifest.

**`pyvda` import error:**  
→ `pip install pyvda`. This requires Windows 10 1903 or later.

---

## Tech Stack

| Component | Library |
|-----------|---------|
| UI | PyQt6 |
| Virtual Desktops | pyvda |
| Window Enumeration | pywin32 (win32gui) |
| Process Info | psutil |
| Global Hotkeys | keyboard |
| Database | SQLite (built-in) |
| Chrome Integration | Native Messaging API |

---

## License

MIT — build on it, share it, make it better.
