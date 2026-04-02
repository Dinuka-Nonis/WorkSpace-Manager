"""
native_host/host.py — Native Messaging Host for WorkSpace Manager.
Chrome extension communicates with this process via stdin/stdout.
Message format: 4-byte little-endian length prefix + UTF-8 JSON body.

Additional: polls a side-channel file for on-demand snapshot requests
from the Python UI (snapshot.py), so the extension can be triggered
without restarting the host process.
"""

import sys
import os
import json
import struct
import threading
import time
from pathlib import Path


# ── Frozen-safe project root resolution ───────────────────────────────────────
# When frozen as workspace_host.exe by PyInstaller, __file__ is inside the
# temporary extraction directory and the relative-path trick breaks.
# When frozen, db.py is already bundled and importable — nothing to add.
# When running from source, we walk up from native_host/ to the project root.

def _setup_path():
    if getattr(sys, "frozen", False):
        # Frozen EXE: all modules are bundled, sys.path is already correct.
        return
    # Source mode: add the project root (parent of native_host/) to sys.path.
    root = Path(__file__).parent.parent
    if str(root) not in sys.path:
        sys.path.insert(0, str(root))

_setup_path()


try:
    import db
    DB_AVAILABLE = True
except ImportError:
    DB_AVAILABLE = False

_appdata     = os.getenv("APPDATA") or str(Path.home() / "AppData" / "Roaming")
APPDATA      = Path(_appdata) / "WorkSpaceManager"
TAB_REQUEST_FILE  = APPDATA / "tab_request.json"
TAB_RESPONSE_FILE = APPDATA / "tab_response.json"


# ── Message I/O ───────────────────────────────────────────────────────────────

def read_message(stream) -> dict | None:
    try:
        raw_len = stream.buffer.read(4)
        if not raw_len or len(raw_len) < 4:
            return None
        msg_len = struct.unpack("<I", raw_len)[0]
        if msg_len == 0 or msg_len > 1_048_576:
            return None
        raw_msg = stream.buffer.read(msg_len)
        if len(raw_msg) < msg_len:
            return None
        return json.loads(raw_msg.decode("utf-8"))
    except Exception as e:
        log(f"read_message error: {e}")
        return None


_stdout_lock = threading.Lock()


def send_message(stream, data: dict):
    """Thread-safe message send."""
    try:
        encoded = json.dumps(data).encode("utf-8")
        with _stdout_lock:
            stream.buffer.write(struct.pack("<I", len(encoded)))
            stream.buffer.write(encoded)
            stream.buffer.flush()
    except Exception as e:
        log(f"send_message error: {e}")


def log(msg: str):
    print(f"[WorkSpace Host] {msg}", file=sys.stderr, flush=True)


def _load_local_state_names() -> dict[str, str]:
    """Return profile_dir → display_name from Chrome Local State."""
    local_appdata = os.getenv("LOCALAPPDATA", "")
    local_state   = os.path.join(local_appdata, "Google", "Chrome",
                                 "User Data", "Local State")
    if not os.path.exists(local_state):
        return {}
    try:
        data = json.loads(open(local_state, encoding="utf-8", errors="replace").read())
        return {
            d: info.get("name", d)
            for d, info in data.get("profile", {}).get("info_cache", {}).items()
        }
    except Exception:
        return {}


def _resolve_profile_for_extension(extension_id: str) -> tuple[str, str]:
    """
    Find the Chrome profile that loaded this specific extension instance.

    Method: iterate all chrome.exe browser processes (no --type= flag),
    read --user-data-dir and --profile-directory from each, then check
    whether <user_data_dir>/<profile_dir>/Extensions/<extension_id> exists
    on disk. The first match is the correct profile.

    Returns (profile_dir, profile_name) or ("", "").
    """
    try:
        import psutil
    except ImportError:
        return "", ""

    local_appdata     = os.getenv("LOCALAPPDATA", "")
    default_user_data = os.path.join(local_appdata, "Google", "Chrome", "User Data")
    names             = _load_local_state_names()

    def _is_browser(proc) -> bool:
        try:
            if "chrome.exe" not in (proc.exe() or "").lower():
                return False
            return not any(a.startswith("--type=") for a in (proc.cmdline() or []))
        except Exception:
            return False

    def _arg(cmdline, prefix) -> str:
        for a in cmdline:
            if a.startswith(prefix):
                return a.split("=", 1)[1].strip('"').strip("'")
        return ""

    try:
        for proc in psutil.process_iter(["exe", "cmdline"]):
            try:
                if not _is_browser(proc):
                    continue
                cmdline      = proc.cmdline() or []
                profile_dir  = _arg(cmdline, "--profile-directory=")
                user_data    = _arg(cmdline, "--user-data-dir=") or default_user_data
                if not profile_dir:
                    continue
                ext_path = os.path.join(user_data, profile_dir, "Extensions", extension_id)
                if os.path.isdir(ext_path):
                    name = names.get(profile_dir, profile_dir)
                    log(f"Profile resolved for ext {extension_id}: {profile_dir!r} ({name})")
                    return profile_dir, name
            except Exception:
                continue
    except Exception as e:
        log(f"_resolve_profile_for_extension error: {e}")

    return "", ""


def _detect_chrome_profile(profile_email_hint: str = "") -> tuple[str, str]:
    """
    Legacy fallback used only by handle_tabs_snapshot when the extension
    did NOT send a confirmed profile_dir.

    Priority:
      1. Match email hint against Local State cache.
      2. Process scan — pick the profile_dir seen most often across all
         chrome.exe browser processes (catches single-profile setups).
      3. Return ("", "") — never guess "Default" for multi-profile setups.
    """
    try:
        import psutil
    except ImportError:
        return "", ""

    local_appdata = os.getenv("LOCALAPPDATA", "")
    local_state   = os.path.join(local_appdata, "Google", "Chrome",
                                 "User Data", "Local State")

    profile_names:  dict[str, str] = {}
    profile_emails: dict[str, str] = {}
    if os.path.exists(local_state):
        try:
            data = json.loads(open(local_state, encoding="utf-8", errors="replace").read())
            for dir_name, info in data.get("profile", {}).get("info_cache", {}).items():
                profile_names[dir_name] = info.get("name", dir_name)
                email = (info.get("user_name") or info.get("gaia_given_name") or "").lower()
                if email:
                    profile_emails[dir_name] = email
        except Exception:
            pass

    # Strategy 1: email hint
    if profile_email_hint:
        hint_lower = profile_email_hint.lower()
        for dir_name, email in profile_emails.items():
            if email == hint_lower:
                log(f"Profile matched by email: {dir_name!r}")
                return dir_name, profile_names.get(dir_name, dir_name)
        log(f"Email hint {profile_email_hint!r} not in Local State — falling back to process scan")

    # Strategy 2: process scan
    profile_counts: dict[str, int] = {}
    chrome_running = False
    try:
        for proc in psutil.process_iter(["exe", "cmdline"]):
            try:
                if "chrome.exe" not in (proc.info.get("exe") or "").lower():
                    continue
                chrome_running = True
                cmdline = proc.info.get("cmdline") or []
                if any(a.startswith("--type=") for a in cmdline):
                    continue
                for arg in cmdline:
                    if arg.startswith("--profile-directory="):
                        prof = arg.split("=", 1)[1].strip('"').strip("'")
                        profile_counts[prof] = profile_counts.get(prof, 0) + 1
            except Exception:
                continue
    except Exception:
        pass

    if not chrome_running:
        return "", ""
    if len(profile_counts) == 1:
        best = next(iter(profile_counts))
        return best, profile_names.get(best, best)
    log("Multiple Chrome profiles running and no email hint — cannot determine profile")
    return "", ""


# ── Side-channel poller ───────────────────────────────────────────────────────
# The Python UI writes a tab_request.json file when it wants a snapshot.
# We detect it here, send a request_tabs to the extension, and write the
# response back to tab_response.json.

_pending_snapshot_session: int | None = None
_snapshot_lock = threading.Lock()


def _poll_side_channel():
    """Background thread: check for tab_request.json every 500ms."""
    global _pending_snapshot_session
    APPDATA.mkdir(parents=True, exist_ok=True)
    while True:
        try:
            if TAB_REQUEST_FILE.exists():
                payload    = json.loads(TAB_REQUEST_FILE.read_text(encoding="utf-8"))
                sid        = payload.get("session_id")
                is_prewarm = payload.get("prewarm", False)
                TAB_REQUEST_FILE.unlink(missing_ok=True)

                if is_prewarm:
                    log("Pre-warm ping received — host is ready")
                elif sid == 0:
                    log("Preview tab request received — will respond without saving to DB")
                    with _snapshot_lock:
                        _pending_snapshot_session = 0
                elif sid:
                    log(f"Side-channel snapshot request for session {sid}")
                    with _snapshot_lock:
                        _pending_snapshot_session = int(sid)
        except Exception as e:
            log(f"Side-channel poll error: {e}")
        time.sleep(0.5)


# ── Session helpers ───────────────────────────────────────────────────────────

def get_active_session() -> dict | None:
    if not DB_AVAILABLE:
        return None
    try:
        db.init_db()
        sessions = db.get_all_sessions()
        for s in sessions:
            if s.get("status") == "active":
                return s
    except Exception as e:
        log(f"get_active_session error: {e}")
    return None


def handle_resolve_profile(extension_id: str):
    """
    Called when the extension sends { type: "resolve_profile", extension_id: ... }.
    Finds the exact Chrome profile that loaded this extension by checking
    the Extensions folder on disk, then sends back profile_confirmed.
    """
    profile_dir, profile_name = _resolve_profile_for_extension(extension_id)
    send_message(sys.stdout, {
        "type":         "profile_confirmed",
        "profile_dir":  profile_dir,
        "profile_name": profile_name,
    })
    if profile_dir:
        log(f"Sent profile_confirmed: {profile_dir!r} ({profile_name})")
    else:
        log("Could not resolve profile — sent empty profile_confirmed")


def handle_tabs_snapshot(session_id: int, tabs: list[dict],
                         is_side_channel: bool = False,
                         preview_only: bool = False,
                         all_tabs: bool = True):
    """
    Save tabs to DB, enriched with the correct Chrome profile.

    Profile resolution order (most → least reliable):
      1. tab["profile_dir"] set by the extension (confirmed via resolve_profile
         handshake at connect time) — use this directly, no host-side guessing.
      2. tab["profile_email"] hint — try Local State email lookup.
      3. Process scan fallback (_detect_chrome_profile).

    all_tabs=False (drag-drop): extension already filtered to one tab.
    preview_only=True: write tab_response.json but skip DB write.
    """
    if not DB_AVAILABLE:
        return
    try:
        ext_profile_dir  = ""
        ext_profile_name = ""
        email_hint       = ""
        if tabs:
            ext_profile_dir  = (tabs[0].get("profile_dir")  or "").strip()
            ext_profile_name = (tabs[0].get("profile_name") or "").strip()
            email_hint       = (tabs[0].get("profile_email") or
                                tabs[0].get("profile_hint")  or "").strip()

        if ext_profile_dir:
            profile_dir  = ext_profile_dir
            profile_name = (ext_profile_name or
                            _load_local_state_names().get(ext_profile_dir, ext_profile_dir))
            log(f"Using extension-confirmed profile: {profile_dir!r} ({profile_name})")
        else:
            profile_dir, profile_name = _detect_chrome_profile(email_hint)
            if profile_dir:
                log(f"Profile via fallback detection: {profile_dir!r} ({profile_name})")
            else:
                log("Profile unknown — tabs will be saved without profile tag")

        enriched = [
            {**t, "profile_dir": profile_dir, "profile_name": profile_name}
            for t in tabs
        ]

        if not preview_only:
            db.save_chrome_tabs(session_id, enriched)
            log(f"Saved {len(enriched)} tab(s) → session {session_id} "
                f"(profile: {profile_dir or 'none'})")
        else:
            log(f"Preview: {len(enriched)} tab(s) collected, skipping DB write")

        if is_side_channel:
            TAB_RESPONSE_FILE.write_text(
                json.dumps({"tabs": enriched, "session_id": session_id}),
                encoding="utf-8",
            )
    except Exception as e:
        log(f"handle_tabs_snapshot error: {e}")


def handle_get_sessions() -> list[dict]:
    if not DB_AVAILABLE:
        return []
    try:
        db.init_db()
        return db.get_all_sessions()
    except Exception:
        return []


# ── Main loop ─────────────────────────────────────────────────────────────────

_awaiting_side_channel_tabs = False


def main():
    global _awaiting_side_channel_tabs

    log("WorkSpace Native Host started")

    if DB_AVAILABLE:
        db.init_db()

    # Start side-channel poller
    t = threading.Thread(target=_poll_side_channel, daemon=True)
    t.start()

    # Background thread that watches for side-channel requests and sends
    # request_tabs to the extension without being blocked by read_message().
    def _side_channel_sender():
        global _awaiting_side_channel_tabs, _pending_snapshot_session
        while True:
            time.sleep(0.3)
            with _snapshot_lock:
                snap_sid = _pending_snapshot_session
            if snap_sid is not None and not _awaiting_side_channel_tabs:
                log(f"Sending request_tabs to extension for session {snap_sid}")
                send_message(sys.stdout, {
                    "type":       "request_tabs",
                    "session_id": snap_sid,
                    "all_tabs":   False,
                    "authorized": "drop_zone",
                })
                _awaiting_side_channel_tabs = True

    sender_thread = threading.Thread(target=_side_channel_sender, daemon=True)
    sender_thread.start()

    while True:
        msg = read_message(sys.stdin)
        if msg is None:
            log("EOF received — exiting")
            break

        msg_type = msg.get("type", "")
        log(f"Received: {msg_type}")

        try:
            if msg_type == "resolve_profile":
                extension_id = msg.get("extension_id", "")
                handle_resolve_profile(extension_id)

            elif msg_type == "get_active_session":
                session = get_active_session()
                if session:
                    send_message(sys.stdout, {
                        "type":         "session_active",
                        "session_id":   session["id"],
                        "session_name": session["name"],
                    })
                else:
                    send_message(sys.stdout, {"type": "session_none"})

            elif msg_type == "tabs_snapshot":
                session_id = msg.get("session_id")
                tabs       = msg.get("tabs", [])
                all_tabs   = msg.get("all_tabs", True)
                # IMPORTANT: use `is not None` — session_id=0 is valid
                if tabs is not None and session_id is not None:
                    is_sc   = _awaiting_side_channel_tabs
                    preview = is_sc and (session_id == 0)
                    handle_tabs_snapshot(
                        session_id, tabs,
                        is_side_channel=is_sc,
                        preview_only=preview,
                        all_tabs=all_tabs,
                    )
                    if is_sc:
                        _awaiting_side_channel_tabs = False
                        with _snapshot_lock:
                            _pending_snapshot_session = None
                    send_message(sys.stdout, {
                        "type":       "tabs_ack",
                        "count":      len(tabs),
                        "session_id": session_id,
                    })

            elif msg_type == "get_sessions":
                sessions = handle_get_sessions()
                send_message(sys.stdout, {
                    "type":     "sessions_list",
                    "sessions": sessions,
                })

            elif msg_type == "set_active_session":
                session_id = msg.get("session_id")
                if session_id:
                    db.update_session_status(session_id, "active")
                    send_message(sys.stdout, {
                        "type":       "session_active",
                        "session_id": session_id,
                    })

            else:
                send_message(sys.stdout, {
                    "type":    "error",
                    "message": f"Unknown message type: {msg_type}",
                })

        except Exception as e:
            log(f"Handler error: {e}")
            send_message(sys.stdout, {"type": "error", "message": str(e)})


if __name__ == "__main__":
    main()