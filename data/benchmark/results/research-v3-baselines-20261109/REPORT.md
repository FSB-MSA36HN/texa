# Baseline trên research-v3 — 09/11/2026

**Baseline đạt 356/400 (89,00%)** trên 200 câu test, chạy hai lần với `gpt-6-luna`, base world. Texa đạt 365/400 (91,25%). Baseline thấp hơn Texa 9 câu, tương đương 2,25 điểm phần trăm. Đây là kết quả exploratory; bộ v3 chưa được review độc lập hoặc sealed.

Baseline nhận câu hỏi, schema PostgreSQL và định nghĩa nghiệp vụ dạng văn bản. Nếu SQL lỗi khi thực thi, LLM được một lần thử sửa từ loại lỗi an toàn. Cấu hình này không có QuerySpec, compiler, validator hay memory của Texa. Đáp án được chấm theo bảng kết quả chuẩn; không so chuỗi SQL.

| Hệ thống | Kết quả | Basic | Compositional | Semantic |
|---|---:|---:|---:|---:|
| **Baseline** | **356/400 (89,00%)** | **71/80** | **192/200** | **93/120** |
| **Texa** | **365/400 (91,25%)** | **80/80** | **177/200** | **108/120** |

Hai lần chạy Baseline lần lượt đạt 178/200 và 178/200. Median latency là 6,27 giây, p95 9,97 giây; chi phí ước tính $0,2076 cho 400 lượt, với 402 lần gọi model do SQL repair. Texa median latency 13,79 giây, chi phí ước tính $0,4014/400 lượt. Chi phí là ước tính theo token, không phải hóa đơn provider.

Kết quả có thể kiểm toán trong sáu JSONL và `summary.json` cùng thư mục. Các artifact đã qua official `read_run`; 200 case IDs, model và hash catalog, example bank, context, schema đều khớp với lần đo Texa. Baseline câu đơn không được chấm ở hội thoại, clarification hay ngoài phạm vi.

Giới hạn: v3 dùng fixture tổng hợp, có overlap giữa family dev/test, test labels đã lộ với nhóm phát triển và chưa có review độc lập. Hai repeats thể hiện biến động khi gọi model, không tăng số intent độc lập. Không suy rộng kết quả thành độ chính xác production.
