"""
restore.py — Session restore entry point.

Thin wrapper around core/launcher.py. Loads items from DB and opens them all.
No window detection, no title parsing, no file searching — we have exact paths.
"""

import db
from core.launcher import open_all_tracked, open_item, icon_for_item


def restore_session(session_id: int) -> dict:
    """
    Open all items saved in a session.
    Returns a result summary dict.
    """
    items = db.get_items(session_id)

    if not items:
        return {"total": 0, "opened": 0, "failed": 0, "errors": []}

    print(f"[Restore] Session {session_id}: opening {len(items)} items")
    for item in items:
        icon = icon_for_item(item)
        print(f"[Restore]   {icon}  [{item['type']}]  {item['label']}")

    # open_all_tracked returns per-item success so we match on ID, not label text.
    # This avoids the bug where labels containing ":" (e.g. "Meeting: Q1") would
    # be split and fail to match, marking a failed item as successfully opened.
    results, failed_ids = open_all_tracked(items)

    for item in items:
        if item["id"] not in failed_ids:
            db.mark_item_opened(item["id"])

    print(f"[Restore] Done — {results['opened']}/{results['total']} opened, "
          f"{results['failed']} failed")
    if results["errors"]:
        for err in results["errors"]:
            print(f"[Restore]   ✗ {err}")

    return results


def get_restore_preview(session_id: int) -> list[str]:
    """
    Returns a list of human-readable strings describing what will be restored.
    Used in the UI to show a preview before the user confirms.
    """
    items = db.get_items(session_id)
    if not items:
        return ["(no items)"]

    lines = []
    for item in items:
        icon = icon_for_item(item)
        lines.append(f"{icon}  {item['label']}")
    return lines
