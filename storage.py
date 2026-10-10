import os
import sys
import sqlite3
import datetime
from pathlib import Path
from typing import Optional, Dict, Any
from config import DB_PATH, LOCK_FILE_PATH

def init_db() -> None:
    """Initialize SQLite database with required tables."""
    conn = sqlite3.connect(DB_PATH)
    try:
        cursor = conn.cursor()
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS processed_jobcards (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                loco_no TEXT NOT NULL,
                jobcard_no TEXT NOT NULL,
                schedule TEXT,
                section_jobcard_id TEXT,
                action_taken TEXT NOT NULL,
                status_before TEXT,
                status_after TEXT,
                screenshot_path TEXT,
                telegram_delivered INTEGER DEFAULT 0,
                telegram_message_id TEXT,
                created_at TEXT NOT NULL,
                UNIQUE(loco_no, jobcard_no)
            )
        """)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS audit_logs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                event_time TEXT NOT NULL,
                level TEXT NOT NULL,
                event_type TEXT NOT NULL,
                loco_no TEXT,
                jobcard_no TEXT,
                details TEXT
            )
        """)
        conn.commit()
    finally:
        conn.close()

def is_jobcard_already_processed(
    loco_no: str,
    jobcard_no: str,
    section_jobcard_id: str = ""
) -> bool:
    """Return True only for an already ACKNOWLEDGED SectionJobCardId."""
    conn = sqlite3.connect(DB_PATH)
    try:
        cursor = conn.cursor()
        sid = (section_jobcard_id or "").strip()
        if sid:
            cursor.execute(
                "SELECT 1 FROM processed_jobcards "
                "WHERE section_jobcard_id = ? AND action_taken = 'ACKNOWLEDGED' LIMIT 1",
                (sid,),
            )
        else:
            cursor.execute(
                "SELECT 1 FROM processed_jobcards "
                "WHERE loco_no = ? AND jobcard_no = ? "
                "AND action_taken = 'ACKNOWLEDGED' LIMIT 1",
                (loco_no.strip(), jobcard_no.strip()),
            )
        return cursor.fetchone() is not None
    finally:
        conn.close()

def record_processed_jobcard(
    loco_no: str,
    jobcard_no: str,
    schedule: str,
    section_jobcard_id: str,
    action_taken: str,
    status_before: str,
    status_after: str,
    screenshot_path: Optional[str] = None,
    telegram_delivered: bool = False,
    telegram_message_id: Optional[str] = None
) -> None:
    """Inserts or updates a processed jobcard record."""
    conn = sqlite3.connect(DB_PATH)
    now_str = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    try:
        cursor = conn.cursor()
        # Only a confirmed live acknowledgement is a processed jobcard.
        if action_taken != "ACKNOWLEDGED":
            return

        sid = (section_jobcard_id or "").strip()
        if sid:
            cursor.execute(
                "DELETE FROM processed_jobcards WHERE section_jobcard_id = ?",
                (sid,),
            )
        else:
            cursor.execute(
                "DELETE FROM processed_jobcards "
                "WHERE loco_no = ? AND jobcard_no = ? AND section_jobcard_id = ''",
                (loco_no.strip(), jobcard_no.strip()),
            )

        cursor.execute(
            """INSERT INTO processed_jobcards (
                loco_no, jobcard_no, schedule, section_jobcard_id,
                action_taken, status_before, status_after,
                screenshot_path, telegram_delivered, telegram_message_id, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                loco_no.strip(),
                jobcard_no.strip(),
                schedule.strip() if schedule else "",
                sid,
                action_taken,
                status_before,
                status_after,
                screenshot_path or "",
                1 if telegram_delivered else 0,
                telegram_message_id or "",
                now_str,
            ),
        )
        conn.commit()
    finally:
        conn.close()

def update_telegram_delivery(loco_no: str, jobcard_no: str, delivered: bool, message_id: Optional[str] = None) -> None:
    """Updates Telegram delivery status for an existing jobcard record."""
    conn = sqlite3.connect(DB_PATH)
    try:
        cursor = conn.cursor()
        cursor.execute("""
            UPDATE processed_jobcards
            SET telegram_delivered = ?, telegram_message_id = ?
            WHERE loco_no = ? AND jobcard_no = ?
        """, (1 if delivered else 0, message_id or "", loco_no.strip(), jobcard_no.strip()))
        conn.commit()
    finally:
        conn.close()

def log_audit(level: str, event_type: str, loco_no: str = "", jobcard_no: str = "", details: str = "") -> None:
    """Logs an audit event to the SQLite database without storing sensitive tokens or passwords."""
    # Ensure sensitive tokens are stripped just in case
    sanitized_details = details.replace(os.getenv("TELEGRAM_BOT_TOKEN", "XYZ"), "[REDACTED]")
    now_str = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    
    conn = sqlite3.connect(DB_PATH)
    try:
        cursor = conn.cursor()
        cursor.execute("""
            INSERT INTO audit_logs (event_time, level, event_type, loco_no, jobcard_no, details)
            VALUES (?, ?, ?, ?, ?, ?)
        """, (now_str, level.upper(), event_type, loco_no.strip(), jobcard_no.strip(), sanitized_details))
        conn.commit()
    finally:
        conn.close()

class SingleInstanceLock:
    """Ensures only one instance of the automation runs at any given time."""
    def __init__(self, lock_file: Path = LOCK_FILE_PATH):
        self.lock_file = lock_file
        self.acquired = False

    def acquire(self) -> bool:
        if self.lock_file.exists():
            try:
                content = self.lock_file.read_text(encoding="utf-8").strip()
                if content:
                    pid = int(content.split(":")[0])
                    # Check if process is still active on Windows
                    import ctypes
                    kernel32 = ctypes.windll.kernel32
                    SYNCHRONIZE = 0x00100000
                    process = kernel32.OpenProcess(SYNCHRONIZE, False, pid)
                    if process != 0:
                        kernel32.CloseHandle(process)
                        return False  # Active process exists
            except Exception:
                pass  # Stale lock file
        
        current_pid = os.getpid()
        now_str = datetime.datetime.now().isoformat()
        self.lock_file.write_text(f"{current_pid}:{now_str}", encoding="utf-8")
        self.acquired = True
        return True

    def release(self) -> None:
        if self.acquired and self.lock_file.exists():
            try:
                self.lock_file.unlink()
            except Exception:
                pass
            self.acquired = False

    def __enter__(self):
        if not self.acquire():
            raise RuntimeError(f"Another instance of RailwayBot is currently running (Lock: {self.lock_file}).")
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.release()

# Auto-initialize DB on import
init_db()
