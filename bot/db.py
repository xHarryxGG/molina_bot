import sqlite3
from pathlib import Path

DB_PATH = Path(__file__).parent / "data.db"

def init_db() -> None:
    conn = sqlite3.connect(DB_PATH)
    try:
        cur = conn.cursor()
        cur.execute("CREATE TABLE IF NOT EXISTS kv (key TEXT PRIMARY KEY, value TEXT)")
        conn.commit()
    finally:
        conn.close()

def set_last_pdf(path: str) -> None:
    set_kv("last_pdf", path)

def get_last_pdf() -> str | None:
    return get_kv("last_pdf")

def set_kv(key: str, value: str) -> None:
    init_db()
    conn = sqlite3.connect(DB_PATH)
    try:
        cur = conn.cursor()
        cur.execute("REPLACE INTO kv (key, value) VALUES (?, ?)", (key, value))
        conn.commit()
    finally:
        conn.close()

def get_kv(key: str) -> str | None:
    init_db()
    conn = sqlite3.connect(DB_PATH)
    try:
        cur = conn.cursor()
        cur.execute("SELECT value FROM kv WHERE key = ?", (key,))
        row = cur.fetchone()
        return row[0] if row else None
    finally:
        conn.close()
