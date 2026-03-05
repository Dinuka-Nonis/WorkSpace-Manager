"""
restore.py — Session restore logic.

RestoreWorker runs in a QThread so the GUI never freezes.
open_all() marks each item as opened after a successful launch.
"""

import db
from core.launcher import open_item, icon_for_item, open_all as _open_all


def restore_session(session_id: int) -> dict:
    """
    Open all items saved in a session.
    Returns {total, opened, failed, errors}.

    BUG-FIX: previously called open_all() then looped open_item() again,
    launching every item twice. Now open_all() is the single launch path,
    and mark_item_opened() is called here for successes.
    """
    items = db.get_items(session_id)

    if not items:
        return {"total": 0, "opened": 0, "failed": 0, "errors": []}

    print(f"[Restore] Session {session_id}: opening {len(items)} items")
    for item in items:
        icon = icon_for_item(item)
        print(f"[Restore]   {icon}  [{item['type']}]  {item['label']}")

    results = {"total": len(items), "opened": 0, "failed": 0, "errors": []}

    import time
    for item in items:
        success, err = open_item(item)
        if success:
            results["opened"] += 1
            db.mark_item_opened(item["id"])
        else:
            results["failed"] += 1
            results["errors"].append(f"{item.get('label', '?')}: {err}")
        time.sleep(0.25)   # small delay so apps don't fight over focus

    print(
        f"[Restore] Done — {results['opened']}/{results['total']} opened, "
        f"{results['failed']} failed"
    )
    for err in results["errors"]:
        print(f"[Restore]   ✗ {err}")

    return results


def get_restore_preview(session_id: int) -> list[str]:
    """
    Returns human-readable strings describing what will be restored.
    Used by the UI to show a preview before the user confirms.
    """
    items = db.get_items(session_id)
    if not items:
        return ["(no items)"]
    return [f"{icon_for_item(item)}  {item['label']}" for item in items]


# ── QThread worker so the GUI stays responsive during restore ─────────────────

try:
    from PyQt6.QtCore import QObject, QThread, pyqtSignal

    class RestoreWorker(QObject):
        """
        Run restore_session() off the main thread.

        Usage:
            self._thread = QThread()
            self._worker = RestoreWorker(session_id)
            self._worker.moveToThread(self._thread)
            self._thread.started.connect(self._worker.run)
            self._worker.finished.connect(self._on_restore_done)
            self._worker.finished.connect(self._thread.quit)
            self._thread.start()
        """
        finished = pyqtSignal(dict)   # emits results dict
        progress = pyqtSignal(str)    # emits label of item being opened

        def __init__(self, session_id: int, parent=None):
            super().__init__(parent)
            self.session_id = session_id

        def run(self):
            items = db.get_items(self.session_id)
            results = {"total": len(items), "opened": 0, "failed": 0, "errors": []}

            if not items:
                self.finished.emit(results)
                return

            import time
            for item in items:
                self.progress.emit(item.get("label", "…"))
                success, err = open_item(item)
                if success:
                    results["opened"] += 1
                    db.mark_item_opened(item["id"])
                else:
                    results["failed"] += 1
                    results["errors"].append(f"{item.get('label', '?')}: {err}")
                time.sleep(0.25)

            self.finished.emit(results)

except ImportError:
    pass   # non-GUI context (e.g. CLI restore)