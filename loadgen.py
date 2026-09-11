#!/usr/bin/env python3
import sys
import time
import threading
import urllib.request

TARGET_URL = sys.argv[1] if len(sys.argv) > 1 else "http://192.168.139.2/api/trigger"
TARGET_RATE = float(sys.argv[2]) if len(sys.argv) > 2 else 90.0  # requests per second

stats = {
    "total_sent": 0,
    "total_ok": 0,
    "total_err": 0,
    "interval_sent": 0,
    "interval_ok": 0,
    "interval_err": 0,
}
lock = threading.Lock()
stop_event = threading.Event()

def send_request():
    try:
        req = urllib.request.Request(TARGET_URL, headers={"User-Agent": f"LoadGen/{int(TARGET_RATE)}rps"})
        with urllib.request.urlopen(req, timeout=8) as res:
            with lock:
                stats["total_sent"] += 1
                stats["interval_sent"] += 1
                if 200 <= res.status < 400:
                    stats["total_ok"] += 1
                    stats["interval_ok"] += 1
                else:
                    stats["total_err"] += 1
                    stats["interval_err"] += 1
    except Exception:
        with lock:
            stats["total_sent"] += 1
            stats["interval_sent"] += 1
            stats["total_err"] += 1
            stats["interval_err"] += 1

def reporter():
    last_time = time.time()
    while not stop_event.is_set():
        time.sleep(5.0)
        now = time.time()
        elapsed = now - last_time
        last_time = now
        with lock:
            sent = stats["interval_sent"]
            ok = stats["interval_ok"]
            err = stats["interval_err"]
            total = stats["total_sent"]
            total_ok = stats["total_ok"]
            stats["interval_sent"] = 0
            stats["interval_ok"] = 0
            stats["interval_err"] = 0

        actual_rps = sent / elapsed if elapsed > 0 else 0
        print(
            f"[{time.strftime('%H:%M:%S')}] Rate: {actual_rps:5.1f} req/s | "
            f"Last 5s: {sent} (OK: {ok}, Err: {err}) | "
            f"Total Sent: {total} (OK: {total_ok})"
        )
        sys.stdout.flush()

def main():
    print("🔥 Continuous Load Generator Started")
    print(f"🎯 Target: {TARGET_URL}")
    print(f"⚡ Target Rate: {TARGET_RATE} req/s")
    print("⏹️ Running continuously in background.\n")
    sys.stdout.flush()

    rep_thread = threading.Thread(target=reporter, daemon=True)
    rep_thread.start()

    interval = 1.0 / TARGET_RATE
    next_time = time.time()

    try:
        while not stop_event.is_set():
            now = time.time()
            if now < next_time:
                sleep_time = next_time - now
                if sleep_time > 0.001:
                    time.sleep(sleep_time)
            else:
                if now - next_time > 0.2:
                    next_time = now

            threading.Thread(target=send_request, daemon=True).start()
            next_time += interval
    except KeyboardInterrupt:
        pass
    finally:
        stop_event.set()

if __name__ == "__main__":
    main()
