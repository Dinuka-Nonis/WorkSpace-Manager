"""
native_host_patch.py
====================
These are the TWO changes you must make to your native host script
(the Python file registered as com.workspace.manager).

CHANGE 1 — Handle "resolve_profile" message
--------------------------------------------
Add this function and call it when msg["type"] == "resolve_profile".
It resolves the CORRECT Chrome profile dir for the extension instance
that sent the message, using the extension_id to find the right process.

CHANGE 2 — Add authorized:"drop_zone" to request_tabs
------------------------------------------------------
Wherever your native host sends { "type": "request_tabs" } to trigger
the extension to capture a tab AFTER a drop-zone save, add the field
"authorized": "drop_zone" to that message.  All other places in the host
that send request_tabs should be REMOVED or they will keep auto-adding tabs.
"""

import os
import sys
import json
import ctypes
import ctypes.wintypes


# ──────────────────────────────────────────────────────────────────────────────
# CHANGE 1: Profile resolution
# ──────────────────────────────────────────────────────────────────────────────

def resolve_chrome_profile_for_extension(extension_id: str) -> tuple[str, str]:
    """
    Find the Chrome profile directory that loaded the extension with the
    given extension_id.

    Strategy:
      1. Iterate all chrome.exe processes that are browser processes
         (no --type= flag in cmdline).
      2. For each, check if its --user-data-dir + any Profile*/Default folder
         contains Extensions/<extension_id>.
      3. The first match gives us the --profile-directory= value.

    Returns (profile_dir, profile_name) e.g. ("Profile 2", "Work Account")
    or ("", "") if not found.
    """
    try:
        import psutil
    except ImportError:
        return "", ""

    local_appdata = os.getenv("LOCALAPPDATA", "")
    default_user_data = os.path.join(local_appdata, "Google", "Chrome", "User Data")

    info_cache = _load_local_state_cache(default_user_data)

    def _is_browser_proc(p):
        try:
            if "chrome.exe" not in (p.exe() or "").lower():
                return False
            return not any(a.startswith("--type=") for a in (p.cmdline() or []))
        except Exception:
            return False

    def _profile_dir_from_cmdline(cmdline: list) -> str:
        for arg in cmdline:
            if arg.startswith("--profile-directory="):
                return arg.split("=", 1)[1].strip('"').strip("'")
        return ""

    def _user_data_dir_from_cmdline(cmdline: list) -> str:
        for arg in cmdline:
            if arg.startswith("--user-data-dir="):
                return arg.split("=", 1)[1].strip('"').strip("'")
        return default_user_data

    def _extension_exists_in_profile(user_data_dir: str, profile_dir: str) -> bool:
        """Check if Extensions/<extension_id> folder exists under this profile."""
        ext_path = os.path.join(user_data_dir, profile_dir, "Extensions", extension_id)
        return os.path.isdir(ext_path)

    try:
        for proc in psutil.process_iter(["exe", "cmdline"]):
            try:
                if not _is_browser_proc(proc):
                    continue
                cmdline = proc.cmdline() or []
                profile_dir  = _profile_dir_from_cmdline(cmdline)
                user_data_dir = _user_data_dir_from_cmdline(cmdline)

                if not profile_dir:
                    continue

                if _extension_exists_in_profile(user_data_dir, profile_dir):
                    profile_name = info_cache.get(profile_dir, {}).get("name", profile_dir)
                    print(f"[NativeHost] Resolved profile for ext {extension_id}: "
                          f"{profile_dir!r} ({profile_name})", file=sys.stderr)
                    return profile_dir, profile_name

            except Exception:
                continue
    except Exception as e:
        print(f"[NativeHost] resolve_chrome_profile error: {e}", file=sys.stderr)

    return "", ""


def _load_local_state_cache(user_data_dir: str) -> dict:
    local_state = os.path.join(user_data_dir, "Local State")
    if not os.path.exists(local_state):
        return {}
    try:
        data = json.loads(open(local_state, encoding="utf-8", errors="replace").read())
        return data.get("profile", {}).get("info_cache", {})
    except Exception:
        return {}


# ──────────────────────────────────────────────────────────────────────────────
# HOW TO USE CHANGE 1 IN YOUR NATIVE HOST MESSAGE LOOP
# ──────────────────────────────────────────────────────────────────────────────
#
# In your native host's message handling loop, add this case:
#
#   elif msg.get("type") == "resolve_profile":
#       extension_id = msg.get("extension_id", "")
#       profile_dir, profile_name = resolve_chrome_profile_for_extension(extension_id)
#       send_message({
#           "type":         "profile_confirmed",
#           "profile_dir":  profile_dir,
#           "profile_name": profile_name,
#       })
#
# ──────────────────────────────────────────────────────────────────────────────


# ──────────────────────────────────────────────────────────────────────────────
# CHANGE 2: request_tabs must include authorized:"drop_zone"
# ──────────────────────────────────────────────────────────────────────────────
#
# Find EVERY place in your native host where you send a request_tabs message
# to the extension.  There should be exactly ONE legitimate place: after a
# confirmed drop-zone save (when you need the active tab URL from the browser).
#
# Change that send from:
#   send_message({"type": "request_tabs", "session_id": sid, "all_tabs": False})
#
# To:
#   send_message({
#       "type":       "request_tabs",
#       "session_id": sid,
#       "all_tabs":   False,
#       "authorized": "drop_zone",   # ← THIS IS THE REQUIRED ADDITION
#   })
#
# DELETE or COMMENT OUT every other send of request_tabs in the host.
# In particular, do NOT send request_tabs:
#   - On startup / when handling get_active_session
#   - When handling set_active_session / session switch
#   - On any timer or periodic basis
#   - After sessions_list is sent
#
# Those were what caused every tab open to be auto-added to the session.
# ──────────────────────────────────────────────────────────────────────────────


# ──────────────────────────────────────────────────────────────────────────────
# CHANGE 3: save_chrome_tabs must use profile_dir, not guess
# ──────────────────────────────────────────────────────────────────────────────
#
# In your native host's handler for "tabs_snapshot", when you call
# db.save_chrome_tabs(session_id, tabs), make sure each tab dict has
# "profile_dir" set from the tab's own "profile_dir" field (sent by the
# extension), NOT from a host-side guess.
#
# The extension now sends profile_dir correctly (confirmed by the host itself
# via profile_confirmed). So in your tabs_snapshot handler:
#
#   def handle_tabs_snapshot(msg):
#       session_id = msg["session_id"]
#       tabs = msg.get("tabs", [])
#       # DO NOT override tab["profile_dir"] here with a host-side guess.
#       # The extension already set profile_dir correctly.
#       # Just pass tabs straight to db.save_chrome_tabs:
#       db.save_chrome_tabs(session_id, tabs)
#
# If your current code does something like:
#   for tab in tabs:
#       tab["profile_dir"] = _get_profile_from_process(...)  # DELETE THIS
# DELETE THAT. It was overwriting the correct extension-provided profile_dir
# with a wrong process-scan result.
# ──────────────────────────────────────────────────────────────────────────────
