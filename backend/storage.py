import sqlite3
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
DB_PATH = BASE_DIR / "winpulse.db"


def get_connection():
    return sqlite3.connect(DB_PATH)


def init_db():
    conn = get_connection()
    cur = conn.cursor()

    cur.execute("""
    CREATE TABLE IF NOT EXISTS system_metrics (
        timestamp TEXT,
        cpu REAL,
        memory REAL,
        disk REAL,
        battery REAL,
        download_kbps REAL,
        upload_kbps REAL
    )
""")


    conn.commit()
    conn.close()


def insert_metrics(timestamp, cpu, memory, disk, battery, download_kbps, upload_kbps):
    conn = get_connection()
    cur = conn.cursor()

    cur.execute("""
        INSERT INTO system_metrics
        VALUES (?, ?, ?, ?, ?, ?, ?)
    """, (
        timestamp,
        cpu,
        memory,
        disk,
        battery,
        download_kbps,
        upload_kbps
    ))

    conn.commit()
    conn.close()

