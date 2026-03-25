"""
restore.py — Session restore entry point.
"""

import db
from core.launcher import open_all_tracked, open_item, icon_for_item


def restore_session(session_id: int) -> dict:
    """
    Open all items saved in a session.
    Records last_restored_at timestamp on success.
    Returns a result summary dict.
    """
    items = db.get_items(session_id)

    if not items:
        return {"total": 0, "opened": 0, "failed": 0, "errors": []}

    print(f"[Restore] Session {session_id}: opening {len(items)} items")
    for item in items:
        icon = icon_for_item(item)
        print(f"[Restore]   {icon}  [{item['type']}]  {item['label']}")

    results, failed_ids = open_all_tracked(items)

    for item in items:
        if item["id"] not in failed_ids:
            db.mark_item_opened(item["id"])

    # Record restore timestamp
    db.touch_session_restored(session_id)

    print(f"[Restore] Done — {results['opened']}/{results['total']} opened, "
          f"{results['failed']} failed")
    if results["errors"]:
        for err in results["errors"]:
            print(f"[Restore]   ✗ {err}")

    return results


def get_restore_preview(session_id: int) -> list[str]:
    items = db.get_items(session_id)
    if not items:
        return ["(no items)"]
    return [f"{icon_for_item(item)}  {item['label']}" for item in items]
