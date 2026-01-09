import sys
import sqlite3
from pathlib import Path
from PyQt6.QtWidgets import (
    QApplication,
    QWidget,
    QLabel,
    QVBoxLayout,
    QGroupBox
)

BASE_DIR = Path(__file__).resolve().parent.parent
DB_PATH = BASE_DIR / "winpulse.db"


def get_connection():
    return sqlite3.connect(DB_PATH)

def format_speed(kbps):
    if kbps is None:
        return "N/A"
    if kbps < 1024:
        return f"{kbps:.2f} KB/s"
    return f"{kbps / 1024:.2f} MB/s"



def get_latest_snapshot():
    conn = get_connection()
    cur = conn.cursor()

    cur.execute("""
        SELECT timestamp, cpu, memory, disk, battery,
               download_kbps, upload_kbps
        FROM system_metrics
        ORDER BY timestamp DESC
        LIMIT 1
    """)

    row = cur.fetchone()
    conn.close()
    return row


def get_session_summary():
    conn = get_connection()
    cur = conn.cursor()

    cur.execute("SELECT COUNT(*) FROM system_metrics")
    samples = cur.fetchone()[0]

    if samples == 0:
        conn.close()
        return None

    cur.execute("SELECT MIN(timestamp), MAX(timestamp) FROM system_metrics")
    start, end = cur.fetchone()

    cur.execute("""
        SELECT
            AVG(cpu), MAX(cpu),
            AVG(memory), MAX(memory),
            AVG(download_kbps), MAX(download_kbps),
            AVG(upload_kbps), MAX(upload_kbps)
        FROM system_metrics
    """)

    stats = cur.fetchone()
    conn.close()

    return samples, start, end, stats


def interpret_value(avg, peak, label):
    if peak > avg * 3:
        return f"{label}: High peaks detected (burst activity)"
    if avg > 80:
        return f"{label}: Sustained high usage"
    return f"{label}: Within normal range"



def get_baseline():
    conn = get_connection()
    cur = conn.cursor()

    cur.execute("""
        SELECT cpu, memory, download_kbps, upload_kbps
        FROM system_metrics
    """)

    rows = cur.fetchall()
    conn.close()

    if len(rows) < 10:
        return None

    import math

    def mean(v): return sum(v) / len(v)
    def std(v, m): return math.sqrt(sum((x - m) ** 2 for x in v) / len(v))

    cpu = [r[0] for r in rows]
    mem = [r[1] for r in rows]
    down = [r[2] for r in rows]
    up = [r[3] for r in rows]

    return {
        "cpu": (mean(cpu), std(cpu, mean(cpu))),
        "memory": (mean(mem), std(mem, mean(mem))),
        "download": (mean(down), std(down, mean(down))),
        "upload": (mean(up), std(up, mean(up)))
    }


def infer_anomalies(avg_cpu, max_cpu, avg_mem, max_mem):
    flags = []
    if max_cpu > 90:
        flags.append("CPU spike detected")
    if max_mem > 90:
        flags.append("High memory pressure detected")
    return flags



class WinPulseViewer(QWidget):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("WinPulse – Viewer")
        self.setMinimumWidth(400)

        layout = QVBoxLayout()

        layout.addWidget(self.snapshot_box())
        layout.addWidget(self.session_box())
        layout.addWidget(self.baseline_box())
        layout.addWidget(self.anomaly_box())

        self.setLayout(layout)

    def anomaly_box(self):
        box = QGroupBox("Anomaly Summary")
        layout = QVBoxLayout()

        summary = get_session_summary()
        if not summary:
            layout.addWidget(QLabel("No data available."))
        else:
            _, _, _, stats = summary
            avg_cpu, max_cpu, avg_mem, max_mem, _, _, _, _ = stats
            anomalies = infer_anomalies(avg_cpu, max_cpu, avg_mem, max_mem)

        if not anomalies:
            layout.addWidget(QLabel("No significant anomalies detected."))
        else:
            for a in anomalies:
                layout.addWidget(QLabel(f"⚠ {a}"))

        box.setLayout(layout)
        return box



    def snapshot_box(self):
        box = QGroupBox("Latest Snapshot")
        layout = QVBoxLayout()

        snap = get_latest_snapshot()
        if not snap:
            layout.addWidget(QLabel("No data available."))
        else:
            ts, cpu, mem, disk, bat, down, up = snap
            layout.addWidget(QLabel(f"Time: {ts}"))
            layout.addWidget(QLabel(f"CPU: {cpu:.2f}%"))
            layout.addWidget(QLabel(f"Memory: {mem:.2f}%"))
            layout.addWidget(QLabel(f"Disk: {disk:.2f}%"))
            layout.addWidget(QLabel(f"Battery: {bat}%"))
            layout.addWidget(QLabel(f"Download: {down:.2f} KB/s"))
            layout.addWidget(QLabel(f"Upload: {up:.2f} KB/s"))

        box.setLayout(layout)
        return box


    def session_box(self):
        box = QGroupBox("Session Summary")
        layout = QVBoxLayout()

        summary = get_session_summary()
        if not summary:
            layout.addWidget(QLabel("No session data."))
        else:
            samples, start, end, stats = summary
            (
                avg_cpu, max_cpu,
                avg_mem, max_mem,
                avg_down, max_down,
                avg_up, max_up
            ) = stats

            layout.addWidget(QLabel(f"Samples: {samples}"))
            layout.addWidget(QLabel(f"Start: {start}"))
            layout.addWidget(QLabel(f"End: {end}"))
            layout.addWidget(QLabel(f"Avg CPU: {avg_cpu:.2f}% | Peak: {max_cpu:.2f}%"))
            layout.addWidget(QLabel(f"Avg Memory: {avg_mem:.2f}% | Peak: {max_mem:.2f}%"))
            layout.addWidget(QLabel(f"Avg Download: {format_speed(avg_down)} | Peak: {format_speed(max_down)}"))
            layout.addWidget(QLabel(f"Avg Upload: {format_speed(avg_up)} | Peak: {format_speed(max_up)}"))
            layout.addWidget(QLabel(interpret_value(avg_cpu, max_cpu, "CPU")))
            layout.addWidget(QLabel(interpret_value(avg_mem, max_mem, "Memory")))

        box.setLayout(layout)
        return box


    def baseline_box(self):
        box = QGroupBox("Baseline (Normal Behavior)")
        layout = QVBoxLayout()

        baseline = get_baseline()
        if not baseline:
            layout.addWidget(QLabel("Not enough data for baseline."))
        else:
            layout.addWidget(QLabel(
                f"CPU: {baseline['cpu'][0]:.2f}% ± {baseline['cpu'][1]:.2f}"
            ))
            layout.addWidget(QLabel(
                f"Memory: {baseline['memory'][0]:.2f}% ± {baseline['memory'][1]:.2f}"
            ))
            layout.addWidget(QLabel(
                f"Download: {baseline['download'][0]:.2f} KB/s ± {baseline['download'][1]:.2f}"
            ))
            layout.addWidget(QLabel(
                f"Upload: {baseline['upload'][0]:.2f} KB/s ± {baseline['upload'][1]:.2f}"
            ))

        box.setLayout(layout)
        return box


if __name__ == "__main__":
    app = QApplication(sys.argv)
    window = WinPulseViewer()
    window.show()
    sys.exit(app.exec())


