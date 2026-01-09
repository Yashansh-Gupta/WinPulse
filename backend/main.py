import psutil
import time
import platform
from datetime import datetime
from storage import init_db, insert_metrics

EXCLUDED_PIDS = {0, 4}

FRIENDLY_NAMES = {
    "Code.exe": "Visual Studio Code",
    "chrome.exe": "Google Chrome",
    "msedge.exe": "Microsoft Edge",
    "python.exe": "Python",
    "explorer.exe": "Windows Explorer"
}

def get_friendly_name(exe_name):
    return FRIENDLY_NAMES.get(exe_name, exe_name)

def get_system_snapshot():
    cpu_percent = psutil.cpu_percent(interval=1)

    memory = psutil.virtual_memory()
    memory_percent = memory.percent

    disk = psutil.disk_usage("C:\\")
    disk_percent = disk.percent

    battery = psutil.sensors_battery()
    if battery:
        battery_percent = battery.percent
        charging = battery.power_plugged
    else:
        battery_percent = None
        charging = None

    uptime_seconds = time.time() - psutil.boot_time()
    uptime_hours = int(uptime_seconds // 3600)
    uptime_minutes = int((uptime_seconds % 3600) // 60)

    return {
        "cpu": cpu_percent,
        "memory": memory_percent,
        "disk": disk_percent,
        "battery": battery_percent,
        "charging": charging,
        "uptime": f"{uptime_hours}h {uptime_minutes}m"
    }

def print_session_summary():
    from storage import get_connection

    conn = get_connection()
    cur = conn.cursor()

    cur.execute("SELECT COUNT(*) FROM system_metrics")
    total_samples = cur.fetchone()[0]

    if total_samples == 0:
        print("\nNo session data available.")
        conn.close()
        return

    cur.execute("SELECT MIN(timestamp), MAX(timestamp) FROM system_metrics")
    start_time, end_time = cur.fetchone()

    cur.execute("""
    SELECT
        AVG(cpu),
        MAX(cpu),
        AVG(memory),
        MAX(memory),
        AVG(download_kbps),
        MAX(download_kbps),
        AVG(upload_kbps),
        MAX(upload_kbps)
    FROM system_metrics
    """)

    (
    avg_cpu, max_cpu,
    avg_mem, max_mem,
    avg_down, max_down,
    avg_up, max_up
    ) = cur.fetchone()


    conn.close()

    print("\nSession Summary")
    print("-" * 40)
    print(f"Samples collected : {total_samples}")
    print(f"Session start     : {start_time}")
    print(f"Session end       : {end_time}")
    print(f"Avg CPU usage     : {avg_cpu:.2f}%")
    print(f"Peak CPU usage    : {max_cpu:.2f}%")
    print(f"Avg Memory usage  : {avg_mem:.2f}%")
    print(f"Peak Memory usage : {max_mem:.2f}%")
    print("-" * 40)
    print(f"Avg Download     : {avg_down:.2f} KB/s")
    print(f"Peak Download    : {max_down:.2f} KB/s")
    print(f"Avg Upload       : {avg_up:.2f} KB/s")
    print(f"Peak Upload      : {max_up:.2f} KB/s")

def compute_baseline():
    from storage import get_connection
    import math

    conn = get_connection()
    cur = conn.cursor()

    cur.execute("""
        SELECT
            cpu,
            memory,
            download_kbps,
            upload_kbps
        FROM system_metrics
        WHERE cpu IS NOT NULL
    """)

    rows = cur.fetchall()
    conn.close()

    if len(rows) < 10:
        print("\nNot enough data to compute baseline (need at least 10 samples).")
        return None

    def mean(values):
        return sum(values) / len(values)

    def stddev(values, avg):
        return math.sqrt(sum((x - avg) ** 2 for x in values) / len(values))

    cpu_vals = [r[0] for r in rows]
    mem_vals = [r[1] for r in rows]
    down_vals = [r[2] for r in rows]
    up_vals = [r[3] for r in rows]

    baseline = {
        "cpu": (mean(cpu_vals), stddev(cpu_vals, mean(cpu_vals))),
        "memory": (mean(mem_vals), stddev(mem_vals, mean(mem_vals))),
        "download": (mean(down_vals), stddev(down_vals, mean(down_vals))),
        "upload": (mean(up_vals), stddev(up_vals, mean(up_vals))),
    }

    return baseline

def print_baseline(baseline):
    if not baseline:
        return

    print("\nBaseline (Normal Behavior)")
    print("-" * 40)

    print(f"CPU Usage     : {baseline['cpu'][0]:.2f}% ± {baseline['cpu'][1]:.2f}")
    print(f"Memory Usage  : {baseline['memory'][0]:.2f}% ± {baseline['memory'][1]:.2f}")
    print(f"Download Rate : {baseline['download'][0]:.2f} KB/s ± {baseline['download'][1]:.2f}")
    print(f"Upload Rate   : {baseline['upload'][0]:.2f} KB/s ± {baseline['upload'][1]:.2f}")

    print("-" * 40)


def collect_and_store(interval=10):
    init_db()
    print(f"\nStarting lightweight monitoring (every {interval}s)")
    print("Press Ctrl+C to stop.\n")

    prev_net = None

    try:
        while True:
            snapshot = get_system_snapshot()
            prev_net, down_kbps, up_kbps = get_network_speed(prev_net, interval)

            insert_metrics(
                timestamp=datetime.now().isoformat(timespec="seconds"),
                cpu=snapshot["cpu"],
                memory=snapshot["memory"],
                disk=snapshot["disk"],
                battery=snapshot["battery"] if snapshot["battery"] is not None else -1,
                download_kbps=down_kbps,
                upload_kbps=up_kbps
            )

            time.sleep(interval)

    except KeyboardInterrupt:
        print("\nMonitoring stopped.")
        print_session_summary()

        baseline = compute_baseline()
        print_baseline(baseline)

        anomalies = detect_anomalies(baseline)
        print_anomalies(anomalies)








def get_top_cpu_processes(limit=3):
    core_count = psutil.cpu_count(logical=True)

    # Prime CPU counters
    for proc in psutil.process_iter():
        try:
            proc.cpu_percent(None)
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue

    time.sleep(1)

    processes = []

    for proc in psutil.process_iter(attrs=["pid", "name"]):
        try:
            if proc.pid in EXCLUDED_PIDS:
                continue

            cpu_raw = proc.cpu_percent(None)
            cpu = cpu_raw / core_count

            if cpu < 0.5:
                continue

            processes.append({
                "pid": proc.pid,
                "name": get_friendly_name(proc.name()),
                "cpu_percent": round(cpu, 1)
            })

        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue

    processes.sort(key=lambda p: p["cpu_percent"], reverse=True)
    return processes[:limit]

def get_top_memory_processes(limit=3):
    total_ram_mb = psutil.virtual_memory().total / (1024 * 1024)

    app_memory = {}
    mem_compression = None

    for proc in psutil.process_iter(attrs=["pid", "name", "memory_info"]):
        try:
            if proc.pid in EXCLUDED_PIDS:
                continue

            raw_name = proc.info["name"]
            name = get_friendly_name(raw_name)
            mem_mb = proc.info["memory_info"].rss / (1024 * 1024)

            if mem_mb < 20:
                continue

            # Handle MemCompression separately
            if raw_name == "MemCompression":
                mem_percent = (mem_mb / total_ram_mb) * 100
                mem_compression = {
                    "memory_mb": round(mem_mb, 1),
                    "memory_percent": round(mem_percent, 2)
                }
                continue

            if name not in app_memory:
                app_memory[name] = {
                    "memory_mb": 0.0,
                    "process_count": 0
                }

            app_memory[name]["memory_mb"] += mem_mb
            app_memory[name]["process_count"] += 1

        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue

    results = []
    for name, data in app_memory.items():
        mem_mb = data["memory_mb"]
        mem_percent = (mem_mb / total_ram_mb) * 100

        results.append({
            "name": name,
            "memory_mb": round(mem_mb, 1),
            "memory_percent": round(mem_percent, 2),
            "process_count": data["process_count"]
        })

    results.sort(key=lambda x: x["memory_mb"], reverse=True)
    return results[:limit], mem_compression

def get_network_speed(prev_counters, interval):
    current = psutil.net_io_counters()

    if prev_counters is None:
        return current, 0.0, 0.0

    bytes_sent = current.bytes_sent - prev_counters.bytes_sent
    bytes_recv = current.bytes_recv - prev_counters.bytes_recv

    upload_speed = bytes_sent / interval / 1024  # KB/s
    download_speed = bytes_recv / interval / 1024  # KB/s

    return current, round(download_speed, 2), round(upload_speed, 2)



def print_snapshot(snapshot, top_cpu, top_memory):
    now = datetime.now().strftime("%H:%M:%S")

    print("\nWinPulse – System Snapshot")
    print(f"Time: {now}")
    print(f"OS: {platform.system()} {platform.release()}")
    print("-" * 40)

    print(f"CPU Usage: {snapshot['cpu']}%")
    print(f"Memory Usage: {snapshot['memory']}%")
    print(f"Disk Usage (C:): {snapshot['disk']}%")

    if snapshot["battery"] is not None:
        status = "Charging" if snapshot["charging"] else "Discharging"
        print(f"Battery: {snapshot['battery']}% ({status})")
    else:
        print("Battery: Not available")

    print(f"System Uptime: {snapshot['uptime']}")
    print("\nTop CPU Processes:")
    for p in top_cpu:
        print(f"  {p['name']} (PID {p['pid']}) – {p['cpu_percent']}%")

    print("-" * 40)

    print("\nTop Memory Applications:")
    for p in top_memory:
        print(
        f"  {p['name']} "
        f"({p['process_count']} processes) – "
        f"{p['memory_mb']} MB ({p['memory_percent']}%)"
    )

    if mem_compression:
        print("\nSystem Memory:")
        print(
        f"  Compressed Memory – "
        f"{mem_compression['memory_mb']} MB "
        f"({mem_compression['memory_percent']}%)"
    )

def detect_anomalies(baseline):
    from storage import get_connection

    if not baseline:
        return

    conn = get_connection()
    cur = conn.cursor()

    cur.execute("""
        SELECT cpu, memory, download_kbps, upload_kbps
        FROM system_metrics
        ORDER BY timestamp
    """)
    rows = cur.fetchall()
    conn.close()

    if not rows:
        return

    cpu_mean, cpu_std = baseline["cpu"]
    mem_mean, mem_std = baseline["memory"]
    down_mean, down_std = baseline["download"]
    up_mean, up_std = baseline["upload"]

    thresholds = {
        "cpu": cpu_mean + 2 * cpu_std,
        "memory": mem_mean + 2 * mem_std,
        "download": down_mean + 2 * down_std,
        "upload": up_mean + 2 * up_std
    }

    required_consecutive = {
        "cpu": 3,
        "memory": 3,
        "download": 5,
        "upload": 5
    }

    counters = {
        "cpu": 0,
        "memory": 0,
        "download": 0,
        "upload": 0
    }

    anomalies = {
        "cpu": False,
        "memory": False,
        "download": False,
        "upload": False
    }

    for cpu, mem, down, up in rows:
        # CPU
        counters["cpu"] = counters["cpu"] + 1 if cpu > thresholds["cpu"] else 0
        if counters["cpu"] >= required_consecutive["cpu"]:
            anomalies["cpu"] = True

        # Memory
        counters["memory"] = counters["memory"] + 1 if mem > thresholds["memory"] else 0
        if counters["memory"] >= required_consecutive["memory"]:
            anomalies["memory"] = True

        # Download
        counters["download"] = counters["download"] + 1 if down > thresholds["download"] else 0
        if counters["download"] >= required_consecutive["download"]:
            anomalies["download"] = True

        # Upload
        counters["upload"] = counters["upload"] + 1 if up > thresholds["upload"] else 0
        if counters["upload"] >= required_consecutive["upload"]:
            anomalies["upload"] = True

    return anomalies


def print_anomalies(anomalies):
    if not anomalies:
        return

    print("\nAnomaly Flags")
    print("-" * 40)

    if not any(anomalies.values()):
        print("No anomalies detected. System behavior was within normal range.")
    else:
        if anomalies["cpu"]:
            print("⚠ CPU usage exceeded normal range for this system.")
        if anomalies["memory"]:
            print("⚠ Memory usage exceeded normal range for this system.")
        if anomalies["download"]:
            print("⚠ Unusual download activity detected.")
        if anomalies["upload"]:
            print("⚠ Unusual upload activity detected.")

    print("-" * 40)



if __name__ == "__main__":
    snapshot = get_system_snapshot()
    top_cpu = get_top_cpu_processes()
    top_memory, mem_compression = get_top_memory_processes()

    print_snapshot(snapshot, top_cpu, top_memory)

    choice = input("\nStart lightweight monitoring? (y/n): ").lower()
    if choice == "y":
        collect_and_store(interval=10)

