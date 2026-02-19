# WorkSpace Manager - Project Structure

```
workspace-manager/
│
├── .git/                       # Git repository
├── .gitignore                  # Git ignore rules
├── README.md                   # Project overview & quick start
├── requirements.txt            # Python dependencies
├── pyproject.toml              # Python project config & build settings
├── setup.py                    # Setup script (for pip install -e .)
├── main.py                     # Application entry point
│
├── config/                     # Configuration files
│   ├── default.toml            # Default settings (committed)
│   └── logging.toml            # Logging configuration
│   └── local.toml              # User overrides (gitignored, created at runtime)
│
├── src/                        # Source code
│   ├── __init__.py
│   │
│   ├── core/                   # Core business logic
│   │   ├── __init__.py
│   │   ├── daemon.py           # Main orchestrator - the brain
│   │   ├── desktop_watcher.py  # Monitors virtual desktop changes
│   │   ├── hotkeys.py          # Global hotkey registration
│   │   ├── window_capture.py   # Captures windows on virtual desktops
│   │   ├── chrome_capture.py   # Captures Chrome tabs via CDP
│   │   └── session_restore.py  # Restores saved sessions
│   │
│   ├── ui/                     # User interface
│   │   ├── __init__.py
│   │   ├── spotlight.py        # Mac-style naming prompt
│   │   ├── hud.py              # Floating HUD window
│   │   ├── main_window.py      # Main application window
│   │   ├── tray.py             # System tray icon
│   │   └── theme.py            # UI theme & styling constants
│   │
│   ├── db/                     # Database layer
│   │   ├── __init__.py
│   │   ├── database.py         # SQLite wrapper & all SQL
│   │   ├── models.py           # Data models (dataclasses)
│   │   └── migrations.py       # Schema migrations (future)
│   │
│   └── utils/                  # Utility functions
│       ├── __init__.py
│       ├── logger.py           # Logging setup
│       ├── config.py           # Config loader
│       ├── startup.py          # Windows startup registration
│       └── helpers.py          # General utilities
│
├── tests/                      # Test suite
│   ├── __init__.py
│   ├── unit/                   # Unit tests
│   │   ├── __init__.py
│   │   ├── test_window_capture.py
│   │   ├── test_database.py
│   │   └── test_session_restore.py
│   │
│   └── integration/            # Integration tests
│       ├── __init__.py
│       └── test_daemon.py
│
├── scripts/                    # Development & build scripts
│   ├── run_dev.py              # Run in dev mode
│   ├── install.py              # Install & setup
│   └── build.py                # Build standalone exe
│
├── docs/                       # Documentation
│   ├── ARCHITECTURE.md         # System architecture
│   ├── SETUP.md                # Setup instructions
│   └── CONTRIBUTING.md         # Contribution guide
│
└── assets/                     # Static assets
    └── icons/                  # Application icons
        └── workspace.ico       # Main icon (future)
```

## Module Responsibilities

### Core (`src/core/`)
The engine that does the actual work. No UI dependencies.

- **daemon.py** - Central orchestrator, owns all mutable state
- **desktop_watcher.py** - Polls pyvda every 1s for desktop changes
- **window_capture.py** - Captures windows using win32 APIs + pyvda
- **chrome_capture.py** - Captures Chrome tabs via DevTools Protocol
- **session_restore.py** - Reopens applications from saved snapshots
- **hotkeys.py** - Registers global keyboard shortcuts

### UI (`src/ui/`)
Presentation layer. Only talks to core via callbacks.

- **spotlight.py** - Naming prompt when new desktop detected
- **hud.py** - Floating always-on-top session list (Win + `)
- **main_window.py** - Full session management interface
- **tray.py** - System tray icon & menu
- **theme.py** - All colors, fonts, spacing in one place

### Database (`src/db/`)
Data persistence. No ORM, pure SQLite.

- **database.py** - All SQL queries live here
- **models.py** - Pure dataclasses (Session, CapturedWindow, etc.)
- **migrations.py** - Schema versioning (future feature)

### Utils (`src/utils/`)
Cross-cutting concerns.

- **logger.py** - Rotating file logs + console output
- **config.py** - TOML config loading with local overrides
- **startup.py** - Windows registry manipulation for startup
- **helpers.py** - Time formatting, path resolution, etc.

## Key Design Principles

1. **Separation of concerns** - UI knows nothing about capture logic
2. **Single source of truth** - Daemon owns all state
3. **Callback-based** - UI registers callbacks, daemon fires them
4. **No globals** - Everything passed explicitly
5. **Windows-only** - No cross-platform abstractions where unnecessary
