# Runbook 1 trang — Region chính down

Hướng dẫn cho trực ca (on-call) xử lý sự cố khi Region A bị sập.

| # | Bước | Lệnh chạy | Tín hiệu xong | Người làm |
|---|---|---|---|---|
| 1 | Xác nhận outage | `python3 chaos/kill_region.py status` | Trả về `a.alive=false` hoặc `a.ready=false` 3 lần liên tiếp ở `reports/health-events.jsonl:2` | Trực ca On-call |
| 2 | Mở incident + bấm giờ RTO | `python3 dr/runbook.py --primary a --target b --backend fs --auto` | Dòng log `step:2` xuất hiện ở `reports/runbook-run.jsonl:2` | Trưởng ca Incident Commander |
| 3 | Restore state ở region phụ | `python3 state/snapshot.py get --region b --backend fs` | Restore xong dữ liệu, logged `step:2_restore_snapshot` ở `reports/failover-events.jsonl:2` | Kỹ sư DR / Automation |
| 4 | Scale pool warm→full | `echo full > state/region-b/pool_state` | `/readyz` của Region B trả về HTTP 200, ghi ở `reports/failover-events.jsonl:4` | Kỹ sư Hạ tầng |
| 5 | DNS/LB cutover | `printf b > edge/active_region` | Đã đổi route sang b ở `reports/failover-events.jsonl:5` | Kỹ sư Mạng |
| 6 | Verify golden signals | `python3 dr/runbook.py --primary a --target b --backend fs --auto` | 10 request test chạy thành công, error rate = 0% ở `reports/runbook-run.jsonl:6` | Kỹ sư QA / Performance |
| 7 | Đo RTO + làm postmortem | `python3 tools/measure_rto.py --loadgen reports/drill-2-withdr.jsonl` | Kết quả trả về `rto_verdict = PASS`, RTO = 28.3s ở `reports/measure-drill-2.json` | Trưởng nhóm On-call |

## Quy trình Rollback (Chuyển luồng ngược về lại Region A)

**Điều kiện trigger rollback:**
1. Region A đã được sửa chữa và khởi động lại (`python3 chaos/kill_region.py restore --region a --backend bare`), `/healthz` và `/readyz` trả 200 liên tục trong 5 phút.
2. Dữ liệu mới từ Region B đã được sync đầy đủ về Region A.

**Người quyết định:** Trưởng ca Incident Commander và Trực ca hệ thống.

**Thao tác rollback:**
```bash
python3 state/snapshot.py put --region b --backend fs
python3 state/snapshot.py get --region a --backend fs
echo full > state/region-a/pool_state
printf a > edge/active_region
```
