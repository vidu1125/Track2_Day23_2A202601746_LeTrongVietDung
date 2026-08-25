# RTO/RPO Evidence — Lab 23

Bảng tổng hợp số liệu đo đạc thực tế từ log của hệ thống qua 2 đợt diễn tập (Drill).

## 1. Drill 1 — Baseline (chưa cấu hình DR)

| Chỉ số | Giá trị | Cách đo | Evidence |
|---|---|---|---|
| t_outage | `2026-08-25T09:37:09` | Lệnh kill từ chaos script | `chaos/chaos-events.jsonl:1` |
| Request fail đầu tiên | `+0.0s` | Dòng `ok:false` đầu tiên sau khi kill | `reports/drill-1-nodr.jsonl:17` |
| Request thành công sau đó | Không có | Không có request nào thành công sau outage | `reports/measure-drill-1.json` |
| RTO | `NO_RECOVERY` | Đo từ `tools/measure_rto.py` | `reports/measure-drill-1.json` |

## 2. Drill 2 — Có DR automation

| Mốc | +giây từ t_outage | Cách đo | Evidence |
|---|---|---|---|
| t_outage (mốc 0) | 0s | Thời điểm nhận sự kiện kill | `chaos/chaos-events.jsonl:4` |
| User thấy lỗi đầu tiên | 0.1s | Request đầu tiên trả lỗi | `reports/drill-2-withdr.jsonl:25` |
| Health check phát hiện | 19.2s | Cảnh báo `UNHEALTHY` cho region a | `reports/health-events.jsonl:2` |
| Snapshot restore xong | 18.4s | Hoàn thành restore dữ liệu sang b | `reports/failover-events.jsonl:2` |
| Region phụ ready | 24.6s | Region b qua giai đoạn warm-up | `reports/failover-events.jsonl:4` |
| DNS cutover | 24.6s | Chuyển `active_region` sang b | `reports/failover-events.jsonl:5` |
| **RTO đo được** | 28.3s | Request thành công đầu tiên từ region b | `reports/drill-2-withdr.jsonl:39` |

| Chỉ số | Đo được | Mục tiêu | Kết quả |
|---|---|---|---|
| RTO — Inference API | `28.3s` | 300s | PASS |
| RPO — Vector DB | `6.01s` / `3` doc | 300s | PASS |

## 3. Phân tích các thành phần cấu thành RTO

| Thành phần | Thời gian (s) | Nguồn gốc con số | Cách tối ưu / Giảm thời gian |
|---|---|---|---|
| Health-check detect floor | 15.0s | `interval_s × threshold` trong `reports/health-events.jsonl:2` | Hạ `interval_s` xuống 2s hoặc `threshold` xuống 2 (cần chấp nhận rủi ro bị flapping khi mạng chập chờn). |
| Snapshot restore | 0.0s | Khoảng giữa `2_restore` và `3_scale` trong `reports/failover-events.jsonl:2` | Đọc dữ liệu từ đĩa SSD NVMe cục bộ hoặc dùng cơ chế nhân bản dữ liệu active-active. |
| GPU pool warm-up | 6.19s | Trường `waited_s` ở `reports/failover-events.jsonl:4` | Bật sẵn instance ở region phụ hoặc nạp trước weights vào VRAM để không mất thời gian nạp mô hình. |
| DNS/LB TTL cache | 3.7s | Hiệu số `t_recovered - t_cutover` từ `reports/drill-2-withdr.jsonl:39` | Giảm DNS TTL về 1s hoặc dùng hệ thống định tuyến Client-side load balancing / Anycast IP. |
