# Postmortem — Báo cáo xử lý sự cố Lab 23

Báo cáo phân tích sự cố theo tinh thần Blameless (tập trung tìm lỗi quy trình và hệ thống để cải thiện, không đổ lỗi cá nhân).

## 1. Timeline sự cố (trích xuất từ log)

| Thời gian (ISO) | Sự kiện diễn ra | Evidence |
|---|---|---|
| `2026-08-25T09:40:33` | Bắt đầu sự cố (Region A bị netblock) | `chaos/chaos-events.jsonl:4` |
| `2026-08-25T09:40:33` | Người dùng gặp lỗi request đầu tiên | `reports/drill-2-withdr.jsonl:25` |
| `2026-08-25T09:40:52` | Health check phát hiện và đổi trạng thái Region A sang UNHEALTHY | `reports/health-events.jsonl:2` |
| `2026-08-25T09:40:57` | Thực hiện cutover đổi DNS sang Region B | `reports/failover-events.jsonl:5` |
| `2026-08-25T09:41:01` | Phục hồi hoàn tất (Request đầu tiên thành công từ Region B) | `reports/drill-2-withdr.jsonl:39` |

## 2. Kết quả RTO / RPO thực tế vs Mục tiêu (Gap analysis)

- RTO mục tiêu: 300s · Thực tế đo được: `28.3s` · Gap: Đạt mục tiêu (nhanh hơn 271.7s)
- RPO mục tiêu: 300s · Thực tế đo được: `6.01s` (mất 3 document) · Gap: Đạt mục tiêu (ít hơn 293.99s)
- **Bước tốn thời gian nhất:** Giai đoạn phát hiện của Health-check (tốn 15.0s, chiếm khoảng 53% tổng RTO). Nguyên nhân do phải đợi đủ 3 lần kiểm tra thất bại liên tiếp (mỗi lần 5s) để chắc chắn sự cố xảy ra thực sự, tránh việc báo động nhầm khi mạng chỉ chập chờn nhất thời.

## 3. Phân tích nguyên nhân gốc rễ (5 Whys)

1. *Tại sao người dùng bị lỗi:* Vì Region A bị chặn mạng (`netblock`), không thể phản hồi request.
2. *Tại sao hệ thống không chuyển vùng ngay:* Vì Health Check cần kiểm tra liên tục 3 lần ($5s \times 3 = 15s$) để tránh lỗi gián đoạn mạng ngắn (flapping).
3. *Tại sao Region B không nhận request ngay lập tức:* Vì Region B trước đó ở trạng thái chờ (warm) và chưa được nạp bản dữ liệu mới nhất từ Region A.
4. *Tại sao Region B cần 6.19s để ready:* Vì phải mất thời gian chạy GPU warm-up và tải dữ liệu SQLite vector DB vào bộ nhớ.
5. *Tại sao quy trình cutover phải qua 5 bước:* Để đảm bảo Region B thật sự sẵn sàng phục vụ trước khi chuyển DNS, tránh tình trạng người dùng nhận lỗi 503 từ cả 2 phía.

## 4. Action items cải tiến hệ thống

| # | Nhiệm vụ (Action Item) | Người làm | Hạn chót | Giảm RTO/RPO dự kiến |
|---|---|---|---|---|
| 1 | Hạ interval health check xuống 2s và threshold xuống 2 | Nam NV | 01/09/2026 | Giảm RTO khoảng 11s |
| 2 | Tăng tần suất replicate snapshot từ 30s lên 5s | Tuấn ĐA | 05/09/2026 | Giảm RPO còn dưới 2s |
| 3 | Khởi động trước mô hình ở Region B (warm-up trước) | Dung LT | 10/09/2026 | Giảm RTO thêm ~3s |

## 5. Trả lời 3 câu hỏi bắt buộc

1. **`interval × threshold` là bao nhiêu giây và chiếm bao nhiêu % RTO?**
   - Bộ đệm $5s \times 3 = 15.0s$, chiếm **53%** tổng RTO đo được (15.0s / 28.3s).
2. **Nếu hạ interval xuống 1s thì sao?**
   - RTO sẽ giảm khoảng 12s, nhưng hệ thống sẽ rất dễ bị báo động nhầm mỗi khi mạng giật lag nhẹ (flapping), làm chuyển vùng liên tục không cần thiết.
3. **Ý nghĩa của `docs_lost` đối với khách hàng:**
   - Số lượng 3 document bị mất tương ứng với các dữ liệu được ghi trong khoảng 6.01s trước khi sập mà chưa kịp đồng bộ sang Region B. Hệ thống phía trên sẽ cần phát hiện và gửi lại 3 bản ghi này.
