"""BƯỚC 3c — SINH VIÊN VIẾT. Tự động hoá runbook §4 "Runbook: Region Chính Down".

7 bước trên slide, mỗi bước 1 dòng log có ts. Log này CHÍNH LÀ timeline của postmortem.
  1 xac_nhan_outage          — probe cả 2 region, đừng tin 1 lần fail (dùng nhiều lần
                              hoặc gọi health_checker.probe nếu đã viết xong 3a)
  2 thong_bao_incident       — ts của dòng này là mốc "operator biết tin", LUÔN LUÔN
                              SAU t_outage trong chaos-events (không thể trùng — operator
                              không thể biết ngay giây outage xảy ra). Ghi cả 2 ts vào
                              log để postmortem tính được "độ trễ thông báo".
  3 scale_gpu_pool           — gọi HÀM `failover.failover(...)` MỘT LẦN DUY NHẤT. Hàm
                              đó tự làm đủ 5 bước con (verify/restore/scale/wait/cutover)
                              và tự ghi log riêng vào reports/failover-events.jsonl.
  4 verify_state_replica     — KHÔNG gọi lại failover — chỉ ĐỌC kết quả (vector count +
                              weights ở region phụ) từ dict mà bước 3 trả về, để log vào
                              runbook-run.jsonl cho postmortem đọc 1 chỗ duy nhất.
  5 dns_cutover              — cũng chỉ đọc lại: kết quả cutover có ok hay không.
  6 verify_golden_signals    — 10 request thật vào region phụ: p95 latency + error rate
  7 post_incident            — elapsed_s + lệnh đo RTO

BÁN TỰ ĐỘNG, KHÔNG FULL-AUTO (§4: "failover đầu tiên nên là bán tự động — alert +
1-click confirm — tránh flapping gây failover 2 chiều liên tục"). Mặc định phải hỏi
người vận hành confirm; --auto chỉ dùng trong CI/khi chấm điểm.

Chạy:  python dr/runbook.py --primary a --target b --backend fs
"""
import argparse
import json
import pathlib
import sys
import time

import httpx

sys.path.insert(0, ".")
from dr import failover as fo  # noqa: E402

LOG = pathlib.Path("reports/runbook-run.jsonl")
URL = {"a": "http://127.0.0.1:8001", "b": "http://127.0.0.1:8002"}


def step(n: int, name: str, **kw):
    """Append 1 dòng {ts, iso, step, name, ...} vào LOG và print ra stdout."""
    now = time.time()
    event = {
        "ts": now,
        "iso": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(now)),
        "step": n,
        "name": name,
        **kw,
    }
    LOG.parent.mkdir(parents=True, exist_ok=True)
    with open(LOG, "a") as f:
        f.write(json.dumps(event) + "\n")
    print(json.dumps(event))
    return event


def confirm(auto: bool, msg: str) -> bool:
    """If auto is True return True, else prompt user y/N."""
    if auto:
        return True
    ans = input(f"{msg} [y/N]: ")
    return ans.strip().lower() == "y"


def run(primary: str, target: str, backend: str, auto: bool) -> dict:
    """Run the 7-step automated runbook procedure."""
    t_start = time.time()

    # Step 1: xac_nhan_outage
    url_prim = f"{URL[primary]}/readyz"
    ready = False
    reason = "unknown"
    try:
        res = httpx.get(url_prim, timeout=2.0)
        ready = (res.status_code == 200) and res.json().get("ready", False)
        reason = "ok" if ready else ",".join(res.json().get("reasons", ["not_ready"]))
    except Exception as e:
        ready = False
        reason = f"error_{type(e).__name__}"

    step(1, "xac_nhan_outage", primary=primary, primary_ready=ready, reason=reason)

    if ready and not confirm(auto, f"Region {primary} is still ready. Continue failover anyway?"):
        step(1, "xac_nhan_outage_aborted", reason="Primary still healthy, operator aborted")
        return {"ok": False, "aborted": True}

    # Step 2: thong_bao_incident
    step(2, "thong_bao_incident", primary=primary, target=target, notice="DR failover initiated")

    if not confirm(auto, f"Execute failover cutover to region {target}?"):
        step(2, "thong_bao_incident_aborted", reason="Operator cancelled cutover")
        return {"ok": False, "aborted": True}

    # Step 3: scale_gpu_pool (calls failover.failover)
    step(3, "scale_gpu_pool", target=target)
    fo_res = fo.failover(target, backend, wait=60.0)

    # Step 4: verify_state_replica
    step(
        4,
        "verify_state_replica",
        target=target,
        rpo_seconds=fo_res.get("rpo_seconds"),
        docs_lost=fo_res.get("docs_lost"),
    )

    # Step 5: dns_cutover
    step(5, "dns_cutover", target=target, ok=fo_res.get("ok"))

    # Step 6: verify_golden_signals
    latencies = []
    errors = 0
    infer_url = f"{URL[target]}/v1/infer"
    for _ in range(10):
        t0 = time.time()
        try:
            r = httpx.get(infer_url, timeout=3.0)
            if r.status_code != 200 or "error" in r.json():
                errors += 1
        except Exception:
            errors += 1
        latencies.append((time.time() - t0) * 1000.0)
        time.sleep(0.05)

    latencies.sort()
    p95 = latencies[int(len(latencies) * 0.95)] if latencies else 0.0
    err_rate = round(errors / 10.0, 2)
    step(
        6,
        "verify_golden_signals",
        target=target,
        sample_count=10,
        error_rate=err_rate,
        p95_ms=round(p95, 2),
    )

    # Step 7: post_incident
    elapsed = time.time() - t_start
    step(
        7,
        "post_incident",
        total_elapsed_s=round(elapsed, 2),
        status="COMPLETED" if fo_res.get("ok") else "FAILED",
    )

    return fo_res


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--primary", default="a")
    p.add_argument("--target", default="b")
    p.add_argument("--backend", default="fs", choices=["fs", "minio"])
    p.add_argument("--auto", action="store_true")
    a = p.parse_args()
    print(json.dumps(run(a.primary, a.target, a.backend, a.auto), indent=2))

