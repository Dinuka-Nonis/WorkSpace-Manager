"""
native_host/host.py — Native Messaging Host for WorkSpace Manager.
Chrome extension communicates with this process via stdin/stdout.
Message format: 4-byte little-endian length prefix + UTF-8 JSON body.

This host:
  - Receives tab snapshots from Chrome extension
  - Writes them to the WorkSpace SQLite database
  - Sends the currently active session back to Chrome
"""

import sys
import os
import json
import struct
import threading
import time
from pathlib import Path

# Add parent directory to path so we can import db.py
sys.path.insert(0, str(Path(__file__).parent.parent))

try:
    import db
    DB_AVAILABLE = True
except ImportError:
    DB_AVAILABLE = False

# ── Message I/O ───────────────────────────────────────────────────────────────

def read_message(stream) -> dict | None:
    """Read one native message from stream. Returns None on EOF/error."""
    try:
        raw_len = stream.buffer.read(4)
        if not raw_len or len(raw_len) < 4:
            return None
        msg_len = struct.unpack("<I", raw_len)[0]
        if msg_len == 0 or msg_len > 1_048_576:  # 1MB max
            return None
        raw_msg = stream.buffer.read(msg_len)
        if len(raw_msg) < msg_len:
            return None
        return json.loads(raw_msg.decode("utf-8"))
    except Exception as e:
        log(f"read_message error: {e}")
        return None


def send_message(stream, data: dict):
    """Write one native message to stream."""
    try:
        encoded = json.dumps(data).encode("utf-8")
        stream.buffer.write(struct.pack("<I", len(encoded)))
        stream.buffer.write(encoded)
        stream.buffer.flush()
    except Exception as e:
        log(f"send_message error: {e}")


def log(msg: str):
    """Log to stderr (doesn't interfere with stdout messaging protocol)."""
    print(f"[WorkSpace Host] {msg}", file=sys.stderr, flush=True)


# ── Session helpers ───────────────────────────────────────────────────────────

def get_active_session() -> dict | None:
    """Return the currently active session from DB."""
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


def handle_tabs_snapshot(session_id: int, tabs: list[dict]):
    """Save tabs to the database."""
    if not DB_AVAILABLE:
        return
    try:
        db.save_chrome_tabs(session_id, tabs)
        log(f"Saved {len(tabs)} tabs for session {session_id}")
    except Exception as e:
        log(f"handle_tabs_snapshot error: {e}")


def handle_get_sessions() -> list[dict]:
    """Return all sessions for the popup."""
    if not DB_AVAILABLE:
        return []
    try:
        db.init_db()
        return db.get_all_sessions()
    except Exception:
        return []


# ── Main loop ─────────────────────────────────────────────────────────────────

def main():
    log("WorkSpace Native Host started")

    if DB_AVAILABLE:
        db.init_db()

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
                        "type": "session_active",
                        "session_id": session["id"],
                        "session_name": session["name"],
                    })
                else:
                    send_message(sys.stdout, {"type": "session_none"})

            elif msg_type == "tabs_snapshot":
                session_id = msg.get("session_id")
                tabs = msg.get("tabs", [])
                if session_id and tabs is not None:
                    handle_tabs_snapshot(session_id, tabs)
                    send_message(sys.stdout, {
                        "type": "tabs_ack",
                        "count": len(tabs),
                        "session_id": session_id,
                    })

            elif msg_type == "get_sessions":
                sessions = handle_get_sessions()
                send_message(sys.stdout, {
                    "type": "sessions_list",
                    "sessions": sessions,
                })

            elif msg_type == "set_active_session":
                session_id = msg.get("session_id")
                if session_id:
                    db.update_session_status(session_id, "active")
                    send_message(sys.stdout, {
                        "type": "session_active",
                        "session_id": session_id,
                    })

            else:
                send_message(sys.stdout, {
                    "type": "error",
                    "message": f"Unknown message type: {msg_type}"
                })

        except Exception as e:
            log(f"Handler error: {e}")
            send_message(sys.stdout, {
                "type": "error",
                "message": str(e)
            })


if __name__ == "__main__":
    main()
