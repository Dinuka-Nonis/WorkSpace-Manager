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

sys.path.insert(0, str(Path(__file__).parent.parent))

try:
    import db
    DB_AVAILABLE = True
except ImportError:
    DB_AVAILABLE = False

APPDATA = Path(os.getenv("APPDATA", ".")) / "WorkSpaceManager"
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
    """Thread-safe message send — overrides the earlier definition."""
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


def _detect_chrome_profile(profile_email_hint: str = "") -> tuple[str, str]:
    """
    Detect the Chrome profile directory and display name.

    Priority order:
      1. If the extension sends a profile_email hint (from chrome.identity),
         cross-reference it against Local State profile email cache — this is
         the most accurate method because the extension itself knows which
         profile it is running in.
      2. Fall back to scanning running chrome.exe processes for
         --profile-directory= flags (least-count heuristic).
      3. If Chrome is running but no flag found, assume "Default".
      4. Return ("", "") if Chrome is not running at all.

    Returns (profile_dir, profile_name) e.g. ("Profile 3", "Work Account").
    """
    import json, os
    try:
        import psutil
    except ImportError:
        return "", ""

    local_appdata = os.getenv("LOCALAPPDATA", "")
    local_state   = os.path.join(local_appdata, "Google", "Chrome", "User Data", "Local State")

    # Build dir→name and dir→email maps from Local State
    profile_names:  dict[str, str] = {}
    profile_emails: dict[str, str] = {}   # dir → account email
    if os.path.exists(local_state):
        try:
            data = json.loads(open(local_state, encoding="utf-8", errors="replace").read())
            for dir_name, info in data.get("profile", {}).get("info_cache", {}).items():
                profile_names[dir_name]  = info.get("name", dir_name)
                # gaia_given_name / user_name / gaia_name differ by sync state
                email = (info.get("user_name") or info.get("gaia_given_name") or "").lower()
                if email:
                    profile_emails[dir_name] = email
        except Exception:
            pass

    # ── Strategy 1: match by email hint from extension ────────────────────────
    if profile_email_hint:
        hint_lower = profile_email_hint.lower()
        for dir_name, email in profile_emails.items():
            if email == hint_lower:
                log(f"Profile matched by email hint: {dir_name!r} ({profile_names.get(dir_name, dir_name)})")
                return dir_name, profile_names.get(dir_name, dir_name)
        # Email present but not found in cache (e.g. not signed in to Chrome sync)
        log(f"Profile email hint {profile_email_hint!r} not in Local State cache — falling back to process scan")

    # ── Strategy 2: process scan ──────────────────────────────────────────────
    chrome_running = False
    profile_counts: dict[str, int] = {}

    for proc in psutil.process_iter(["exe", "cmdline"]):
        try:
            exe = proc.info.get("exe") or ""
            if "chrome.exe" not in exe.lower():
                continue
            chrome_running = True
            for arg in (proc.info.get("cmdline") or []):
                if arg.startswith("--profile-directory="):
                    prof = arg.split("=", 1)[1].strip('"').strip("'")
                    profile_counts[prof] = profile_counts.get(prof, 0) + 1
        except Exception:
            continue

    if not chrome_running:
        return "", ""
    if not profile_counts:
        name = profile_names.get("Default", "Default")
        return "Default", name
    best = max(profile_counts, key=lambda k: profile_counts[k])
    return best, profile_names.get(best, best)


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
                payload = json.loads(TAB_REQUEST_FILE.read_text(encoding="utf-8"))
                sid = payload.get("session_id")
                is_prewarm = payload.get("prewarm", False)
                TAB_REQUEST_FILE.unlink(missing_ok=True)

                if is_prewarm:
                    # Explicit pre-warm ping — stay alive, nothing to do
                    log("Pre-warm ping received — host is ready")
                elif sid == 0:
                    # session_id=0 from picker scan — preview request.
                    # We still ask the extension for tabs, but handle_tabs_snapshot
                    # will skip the DB write (preview_only=True path).
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


def handle_tabs_snapshot(session_id: int, tabs: list[dict],
                         is_side_channel: bool = False,
                         preview_only: bool = False,
                         all_tabs: bool = True):
    """
    Enrich tabs with the active Chrome profile and optionally save to DB.

    all_tabs=False  (drag-drop capture): the extension already filtered to the
    single focused tab. We honour that and do NOT expand it.

    all_tabs=True   (explicit "Save tabs" by user): save everything sent.

    preview_only=True: write tab_response.json for the picker UI to read,
    but do NOT call db.save_chrome_tabs().  The picker saves tabs to the
    correct session only after the user confirms the target session.
    This prevents tabs being written into the wrong (MRU) session.

    Profile detection priority:
      1. profile_email field sent by the extension (most accurate — comes from
         chrome.identity running inside the actual profile).
      2. Process-scan fallback in _detect_chrome_profile().
    """
    if not DB_AVAILABLE:
        return
    try:
        # Extract the profile hint that the extension embedded in the tab objects.
        # All tabs from the same profile share the same hint, so grab the first one.
        profile_email_hint = ""
        if tabs:
            profile_email_hint = tabs[0].get("profile_email") or tabs[0].get("profile_hint") or ""

        profile_dir, profile_name = _detect_chrome_profile(profile_email_hint)
        log(f"Chrome profile: dir={profile_dir!r} name={profile_name!r} "
            f"hint={profile_email_hint!r} preview={preview_only} all_tabs={all_tabs}")

        enriched = []
        for t in tabs:
            enriched.append({
                **t,
                "profile_dir":  profile_dir,
                "profile_name": profile_name,
            })

        if not preview_only:
            db.save_chrome_tabs(session_id, enriched)
            log(f"Saved {len(enriched)} tabs for session {session_id} (profile: {profile_dir or 'none'})")
        else:
            log(f"Preview: {len(enriched)} tabs collected, skipping DB write")

        if is_side_channel:
            # Always write response so snapshot.py / picker can read it
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
            if msg_type == "get_active_session":
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
                all_tabs   = msg.get("all_tabs", True)   # extension sets False for drag-drop
                # IMPORTANT: use `is not None` checks — session_id=0 is valid
                # (preview request) and `if session_id` would skip it silently.
                if tabs is not None and session_id is not None:
                    is_sc      = _awaiting_side_channel_tabs
                    # preview_only when side-channel request had session_id=0
                    preview    = is_sc and (session_id == 0)
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
