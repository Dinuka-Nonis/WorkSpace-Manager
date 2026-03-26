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


def send_message(stream, data: dict):
    try:
        encoded = json.dumps(data).encode("utf-8")
        stream.buffer.write(struct.pack("<I", len(encoded)))
        stream.buffer.write(encoded)
        stream.buffer.flush()
    except Exception as e:
        log(f"send_message error: {e}")


def log(msg: str):
    print(f"[WorkSpace Host] {msg}", file=sys.stderr, flush=True)


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

                if is_prewarm or sid == 0:
                    # Pre-warm ping — just stay alive, no snapshot needed
                    log("Pre-warm ping received — host is ready")
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
                         is_side_channel: bool = False):
    """Save tabs to the database."""
    if not DB_AVAILABLE:
        return
    try:
        db.save_chrome_tabs(session_id, tabs)
        log(f"Saved {len(tabs)} tabs for session {session_id}")

        if is_side_channel:
            # Write the result back so snapshot.py can confirm
            TAB_RESPONSE_FILE.write_text(
                json.dumps({"tabs": tabs, "session_id": session_id}),
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

    while True:
        # Check if there's a pending side-channel snapshot request first
        with _snapshot_lock:
            snap_sid = _pending_snapshot_session

        if snap_sid is not None and not _awaiting_side_channel_tabs:
            log(f"Sending request_tabs to extension for side-channel session {snap_sid}")
            send_message(sys.stdout, {
                "type":       "request_tabs",
                "session_id": snap_sid,
            })
            _awaiting_side_channel_tabs = True
            with _snapshot_lock:
                pass  # we'll clear _pending_snapshot_session when response arrives

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
                if session_id and tabs is not None:
                    is_sc = _awaiting_side_channel_tabs
                    handle_tabs_snapshot(session_id, tabs, is_side_channel=is_sc)
                    if is_sc:
                        _awaiting_side_channel_tabs = False
                        with _snapshot_lock:
                            pass
                        global _pending_snapshot_session
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
