"""BƯỚC 3a — SINH VIÊN VIẾT. Health checker cho 2 region.

Yêu cầu (đọc §4 "Kiến Trúc Health-Check-Based Failover" + §2 "DNS Failover"):
  1. Poll /readyz của CẢ HAI region mỗi `interval` giây (mặc định 5s).
     Dùng /readyz, KHÔNG dùng /healthz. /healthz chỉ nói "process còn sống" —
     region có process sống nhưng vector DB rỗng thì vẫn không serve được.
  2. Chỉ đổi trạng thái sau `threshold` lần fail LIÊN TIẾP (mặc định 3).
     Một lần fail không phải outage. Đây là chống flapping (§4 Anti-Patterns).
  3. Ghi 1 dòng JSONL MỖI LẦN ĐỔI TRẠNG THÁI (không ghi mỗi lần poll — log sẽ ngập).
     Dòng bắt buộc có: ts, region, to (HEALTHY|UNHEALTHY), reason,
     interval_s, threshold. Thiếu interval_s/threshold thì tools/measure_rto.py
     không tính được detect floor -> mất điểm.

Chạy:  python dr/health_checker.py --interval 5 --threshold 3 --duration 300 \
              --out reports/health-events.jsonl

CÂU HỎI PHẢI TRẢ LỜI TRƯỚC KHI VIẾT (ghi câu trả lời vào reports/postmortem.md):
  interval=5s, threshold=3 -> sớm nhất bạn có thể phát hiện outage là bao nhiêu giây?
  Con số đó nằm TRONG RTO của bạn. Muốn RTO 5 phút thì được phép chọn interval bao nhiêu?
"""
import argparse
import json
import pathlib
import time

import httpx

URL = {"a": "http://127.0.0.1:8001", "b": "http://127.0.0.1:8002"}


def probe(region: str, timeout: float) -> tuple[bool, str]:
    """Probe /readyz of a given region. Returns (ready, reason)."""
    url = f"{URL[region]}/readyz"
    try:
        res = httpx.get(url, timeout=timeout)
        if res.status_code == 200:
            return True, "ok"
        try:
            data = res.json()
            reasons = data.get("reasons", [f"status_{res.status_code}"])
            return False, ",".join(reasons)
        except Exception:
            return False, f"status_{res.status_code}"
    except Exception as e:
        return False, f"error_{type(e).__name__}"


def run(interval: float, timeout: float, threshold: int, duration: float, out: pathlib.Path):
    """Loop probing both regions, detect state transitions, and emit JSONL events on change."""
    out.parent.mkdir(parents=True, exist_ok=True)
    states = {"a": "HEALTHY", "b": "HEALTHY"}
    consecutive_fails = {"a": 0, "b": 0}
    start_time = time.time()

    while time.time() - start_time < duration:
        for region in ["a", "b"]:
            ready, reason = probe(region, timeout)
            if ready:
                consecutive_fails[region] = 0
                if states[region] == "UNHEALTHY":
                    states[region] = "HEALTHY"
                    now = time.time()
                    event = {
                        "ts": now,
                        "iso": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(now)),
                        "event": "state_change",
                        "region": region,
                        "to": "HEALTHY",
                        "reason": reason,
                        "consecutive_fails": 0,
                        "interval_s": interval,
                        "threshold": threshold,
                    }
                    with open(out, "a") as f:
                        f.write(json.dumps(event) + "\n")
                    print(json.dumps(event))
            else:
                consecutive_fails[region] += 1
                if consecutive_fails[region] >= threshold and states[region] == "HEALTHY":
                    states[region] = "UNHEALTHY"
                    now = time.time()
                    event = {
                        "ts": now,
                        "iso": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(now)),
                        "event": "state_change",
                        "region": region,
                        "to": "UNHEALTHY",
                        "reason": reason,
                        "consecutive_fails": consecutive_fails[region],
                        "interval_s": interval,
                        "threshold": threshold,
                    }
                    with open(out, "a") as f:
                        f.write(json.dumps(event) + "\n")
                    print(json.dumps(event))

        time.sleep(interval)


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--interval", type=float, default=5.0)
    p.add_argument("--timeout", type=float, default=2.0)
    p.add_argument("--threshold", type=int, default=3)
    p.add_argument("--duration", type=float, default=300)
    p.add_argument("--out", default="reports/health-events.jsonl")
    a = p.parse_args()
    run(a.interval, a.timeout, a.threshold, a.duration, pathlib.Path(a.out))

