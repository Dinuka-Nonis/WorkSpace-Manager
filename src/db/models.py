"""Database models - pure dataclasses."""

from __future__ import annotations
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Optional


class SessionStatus(str, Enum):
    ACTIVE = "active"
    PAUSED = "paused"
    IDLE = "idle"
    CLOSED = "closed"


class AppType(str, Enum):
    VSCODE = "vscode"
    CHROME = "chrome"
    FIREFOX = "firefox"
    PDF_VIEWER = "pdf_viewer"
    TERMINAL = "terminal"
    GENERIC = "generic"


@dataclass
class Session:
    id: Optional[int]
    name: str
    desktop_id: str
    status: SessionStatus
    created_at: datetime
    updated_at: datetime
    last_snapshot: Optional[datetime] = None
    total_duration: int = 0
    notes: str = ""


@dataclass
class CapturedWindow:
    id: Optional[int]
    session_id: int
    snapshot_id: int
    hwnd: int
    process_name: str
    window_title: str
    app_type: AppType
    exe_path: str
    working_dir: Optional[str] = None
    cmd_args: list[str] = field(default_factory=list)
    restore_cmd: Optional[str] = None


@dataclass
class ChromeTab:
    id: Optional[int]
    session_id: int
    snapshot_id: int
    window_id: int
    tab_id: str
    url: str
    title: str
    is_pinned: bool = False
    is_active: bool = False


@dataclass
class Snapshot:
    id: Optional[int]
    session_id: int
    captured_at: datetime
    window_count: int = 0
    tab_count: int = 0
    is_final: bool = False
