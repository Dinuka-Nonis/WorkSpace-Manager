"""WorkSpace Manager - Full Application."""

import sys
import logging
from pathlib import Path
import tkinter as tk

from src.utils.logger import setup_logging
from src.utils.config import load_config, resolve_path
from src.db.database import Database
from src.core.daemon import WorkSpaceDaemon
from src.ui.spotlight import SpotlightPrompt

logger = logging.getLogger("workspace.main")


def main():
    # Setup logging
    log_dir = Path.home() / "AppData" / "Roaming" / "WorkSpace" / "logs"
    setup_logging(log_dir, level="INFO")
    logger.info("WorkSpace starting")

    # Load config
    config = load_config()

    # Database
    data_dir = Path(resolve_path(config.get("app", {}).get("data_dir", "%APPDATA%/WorkSpace")))
    db_path = data_dir / config.get("db", {}).get("filename", "sessions.db")
    db = Database(db_path)
    db.connect()

    # Daemon
    daemon = WorkSpaceDaemon(db, config)

    # Simple UI for testing
    root = tk.Tk()
    root.title("WorkSpace Manager")
    root.geometry("400x300")

    tk.Label(root, text="🗂 WorkSpace", font=("Arial", 20, "bold")).pack(pady=20)
    tk.Label(root, text="Session Manager Running", font=("Arial", 12)).pack()
    tk.Label(root, text="Press Ctrl+Win+D on a new desktop", font=("Arial", 9), fg="gray").pack()
    
    sessions_label = tk.Label(root, text="Sessions: 0", font=("Arial", 10))
    sessions_label.pack(pady=10)
    
    # List of session names
    sessions_list = tk.Text(root, height=8, width=50, font=("Arial", 9))
    sessions_list.pack(pady=10, padx=20)

    def update_sessions():
        sessions = daemon.get_all_sessions()
        sessions_label.config(text=f"Sessions: {len(sessions)}")
        
        # Update list
        sessions_list.delete("1.0", tk.END)
        for s in sessions:
            sessions_list.insert(tk.END, f"• {s.name} ({s.status.value})\n")
        
        root.after(2000, update_sessions)

    def on_new_desktop(desktop_id: str):
        def show_prompt():
            SpotlightPrompt(
                desktop_id=desktop_id,
                on_confirm=lambda name, did: daemon.create_session(name, did),
                on_cancel=lambda did: daemon.cancel_session(did)
            )
        root.after(0, show_prompt)

    daemon.on_new_desktop_detected(on_new_desktop)
    daemon.start()
    update_sessions()

    def shutdown():
        daemon.stop()
        db.close()
        root.quit()

    root.protocol("WM_DELETE_WINDOW", shutdown)
    
    logger.info("UI ready - press Ctrl+Win+D to create a session")
    root.mainloop()


if __name__ == "__main__":
    main()