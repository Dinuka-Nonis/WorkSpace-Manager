# WorkSpace Manager — Drag-to-Save Architecture

## What It Does

WorkSpace Manager lets you save your current working context — open apps, VS Code folders, Chrome tabs, File Explorer windows — into named sessions, and restore them later with one click.

**The old approach:** scanning all running processes every time you clicked "Save Snapshot" — unreliable, slow, and hard to control exactly what got saved.

**The new approach:** drag any window to the right edge of your screen (like Windows Snap, but for saving state). The wallet slides in, you release, it's saved. No scanning, no dialogs, completely intentional.

---

## How It Works: The Core Mechanism

### `SetWinEventHook` — The Same API Windows Uses

When you drag a window, Windows fires a system-wide event called `EVENT_SYSTEM_MOVESIZESTART`. This is a documented, official Win32 API — it's the same mechanism that powers PowerToys FancyZones and AquaSnap.

```
User grabs window titlebar
        ↓
Windows fires EVENT_SYSTEM_MOVESIZESTART
        ↓
DragWatcher receives: HWND of the dragged window
        ↓
Resolve: HWND → PID → exe path → app state
        ↓
Drop zone slides in from right edge of screen
        ↓
User releases window (EVENT_SYSTEM_MOVESIZEEND fires)
        ↓
Is cursor inside the drop zone?
  YES → save to DB, show confirmation, zone hides
  NO  → zone slides back out, nothing happens
```

The app being dragged is **never closed or disturbed**. It stays exactly where you drop it on your desktop. WorkSpace Manager only reads its state silently in the background.

---

## Architecture Overview

```
workspace-manager/
│
├── core/
│   ├── drag_watcher.py     ← NEW: SetWinEventHook thread
│   │                              Watches system-wide for window drags
│   │                              Resolves HWND → app state dict
│   │                              Emits Qt signals to the UI
│   │
│   ├── snapshot.py         ← KEPT: detection functions
│   │                              _get_vscode_workspaces()
│   │                              _get_file_explorer_windows()
│   │                              capture_running_apps()
│   │                              (called per-window, not bulk scan)
│   │
│   └── launcher.py         ← KEPT: restore logic (open_item, open_all)
│
├── ui/
│   ├── drop_zone.py        ← NEW: right-edge overlay
│   │                              Slides in during drags
│   │                              Dark wallet design
│   │                              Shows session cards + drop target
│   │
│   ├── wallet_panel.py     ← NEW: hotkey-toggled session viewer
│   │                              Notification-card style session list
│   │                              One-click restore per session
│   │
│   └── main_window.py      ← KEPT: full session management UI
│
├── main.py                 ← REPLACED: new entry point
│                                  Wires DragWatcher → DropZone
│                                  Sets up hotkeys + tray
│
├── db.py                   ← KEPT: SQLite sessions/items
└── restore.py              ← KEPT: session restore logic
```

---

## New Files Explained

### `core/drag_watcher.py`

The engine. Runs in its own `QThread` with a Windows message pump (`GetMessage` loop). This is required for `SetWinEventHook` to receive callbacks.

**Key signals:**

| Signal | When fired | Payload |
|--------|-----------|---------|
| `drag_started(dict)` | User begins dragging any window | `{label, type, path_or_url, hwnd, pid, exe}` |
| `dropped_in_zone(dict)` | Window released inside drop zone | Same as above |
| `drag_cancelled()` | Window released outside drop zone | — |

**What gets captured per app type:**

| App | What's saved | How to restore |
|-----|-------------|---------------|
| VS Code | exe path + open workspace folder | `code.exe /path/to/folder` |
| File Explorer | open folder path via Shell COM | `explorer.exe /path/to/folder` |
| Chrome | tabs via native host extension | `chrome.exe --profile-dir=X url` |
| UWP/Store apps | package exe path | Launch via `shell:AppsFolder\<AUMID>` |
| Everything else | exe path + window title | `subprocess.Popen([exe_path])` |

### `ui/drop_zone.py`

The visual drop target. A frameless, always-on-top `QWidget` positioned at the right edge of the primary screen.

- **Hidden state:** only a 6px strip is visible at the very right edge
- **Drag detected:** animates in (320ms ease-out cubic)
- **Hover:** glows green — signals a valid drop target
- **Drop confirmed:** shows checkmark + app name for 2.2 seconds, then slides back out
- **Cancelled:** slides back out immediately

The wallet design shows stacked session cards. Click any card to change which session the next drop goes into.

### `ui/wallet_panel.py`

The manually-toggled session browser. Press `Ctrl+Alt+W` to show/hide.

Each session is displayed as a notification-style card (dark background, coloured icon square, name + item count + time ago). Hover any row to reveal a green **Restore** button.

---

## Hotkeys

| Hotkey | Action |
|--------|--------|
| `Ctrl+Alt+W` | Toggle the wallet/sessions panel |
| `Ctrl+Alt+Space` | Show the main WorkSpace Manager window |

Hotkeys require the `keyboard` package: `pip install keyboard`

---

## Installation

```bash
# Install Python dependencies
pip install PyQt6 psutil pywin32 keyboard

# Install and register the Chrome native messaging host
# (required for Chrome tab capture)
cd native_host
python install_host.py

# Run
python main.py
```

The app starts minimised to the system tray. Right-click the tray icon for options.

---

## What Was Removed

The following components from the old architecture have been deleted or emptied:

- **`SnapshotPickerDialog`** in `main_window.py` — the dialog that showed all running apps for you to tick checkboxes. Replaced by intentional drag-and-drop.
- **`_SnapshotScanWorker`** / `_SnapshotSaveWorker`** — background threads that scanned all running processes. No longer needed.
- **`scan_for_picker()`** in `snapshot.py` — bulk scan function. The individual detection functions (`_get_vscode_workspaces`, etc.) are kept and called on-demand per dragged window.
- **`_prewarm_native_host()`** startup call — was used to warm up Chrome extension communication before a snapshot. Now called only when a Chrome window is dropped.
- **`register_shutdown_hook()`** — auto-saved everything on shutdown. Replaced by intentional saving.
- **"Save Snapshot" tray menu item** — removed. Saving is now done by dragging.

---

## Chrome Tab Capture

Chrome tabs are still captured via the native messaging extension. When you drag a Chrome window onto the drop zone:

1. `DragWatcher` detects it's Chrome and skips the exe-based capture
2. It sends a request to the Chrome native host via a side-channel file
3. The Chrome extension responds with all open tabs + their profile
4. Tabs are saved as `chrome-profile:<profile_dir>|<url>` items
5. On restore, Chrome opens with the correct profile and URL

The native host must be installed: `cd native_host && python install_host.py`

---

## Database

Sessions and items are stored in SQLite at:
```
%APPDATA%\WorkSpaceManager\workspace.db
```

Schema:
```sql
sessions      (id, name, icon, description, created_at, updated_at, last_restored_at)
session_items (id, session_id, type, path_or_url, label, added_at, last_opened_at)
```

`type` is one of `app`, `url`, or `file`.

---

## Limitations

- **Windows only.** `SetWinEventHook` is a Win32 API. The drop zone and watcher will not activate on macOS or Linux (the rest of the app will still run).
- **Chrome window drag:** Chrome itself won't be "saved" — instead, a tab capture request fires. This requires the extension to be installed and Chrome running.
- **Window position not restored:** The app is relaunched but not necessarily at the same screen position or size. This requires OS-level window management APIs beyond the current scope.
- **App-internal state:** WorkSpace Manager can re-open VS Code at the right folder, but it cannot restore unsaved editor tabs or scroll position within the app. That's controlled by VS Code's own session restore.

---

## Contributing / Extending

To add support for a new app type, edit `core/drag_watcher.py` in the `_capture_window_info()` method. Match on `stem` (the exe filename without extension) and return a dict with `type`, `path_or_url`, and `label`.

To add a new restore strategy, edit `core/launcher.py` in `open_item()` — match on the `path_or_url` prefix and dispatch to your new function.
