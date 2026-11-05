# Texa — dàn ý thuyết trình (12 slide, 15–20 phút)

**Luận điểm:** Texa giới hạn LLM ở việc hiểu ý định; catalog, validator và compiler giữ định nghĩa, phép tính và truy vấn có thể kiểm tra.

| # | Slide / thông điệp | Ý chính | Thời lượng |
|---|---|---|---:|
| 1 | Hỏi dữ liệu bằng ngôn ngữ tự nhiên | Một câu hỏi ngắn ẩn metric, nguồn, kỳ và cách tính | 1:00 |
| 2 | Phạm vi sản phẩm | Persona PM/PO là giả thuyết; Cosmetics và Olist; 8 metric; một nguồn/query | 1:30 |
| 3 | Dữ liệu khác nhau, ngữ nghĩa phải rõ | Event log và order lifecycle; Olist thiếu view/session | 1:30 |
| 4 | Bài học từ Text-to-SQL | Baseline trực tiếp linh hoạt; vẫn cần ràng buộc nghiệp vụ | 1:30 |
| 5 | Semantic layer + biểu diễn trung gian | Metric catalog và QuerySpec giới hạn lựa chọn | 1:30 |
| 6 | Kiến trúc thực thi Texa | intent → clarify → validate → deterministic SQL → facts → insight | 2:00 |
| 7 | Hội thoại có trạng thái an toàn | Structured memory, tham chiếu ngữ cảnh, snapshot guard | 1:30 |
| 8 | Vì sao chỉ dùng một nguồn mỗi truy vấn | ETL chuẩn hóa event rows; không trộn tiền tệ/nguồn | 1:00 |
| 9 | Đánh giá tách theo câu và hội thoại | Dataset v2 và ablation; live test chưa hoàn tất | 1:30 |
| 10 | Kết quả dev hiện có | So sánh ban đầu và kết quả sau tinh chỉnh; không tuyên bố thắng | 2:00 |
| 11 | Kiểm thử demo và giới hạn | E2E scripted; không phải model accuracy hay load test | 1:00 |
| 12 | Kết luận và demo | Trả lời, hỏi lại, từ chối ngoài phạm vi; bước tiếp theo là held-out test | 1:00 |

## Ghi chú dùng bài

- Tổng thời lượng mục tiêu khoảng 17 phút, gồm chuyển slide và demo ngắn. Script tương ứng nằm ở [PRESENTATION_SCRIPT.md](PRESENTATION_SCRIPT.md).
- Nêu kết quả theo split **dev** và đúng phiên bản chạy; kết quả sau tinh chỉnh không thay thế đánh giá test độc lập.
- Không đưa vào bài: tỷ lệ từ paper chưa xác minh, FX, AOV/order, delivery/review, cross-source totals hoặc tuyên bố causal.
- SVG trong thư mục này là hình minh họa độc lập; có thể chiếu các hình liên quan ở slides 3, 5–7, 9–10.
