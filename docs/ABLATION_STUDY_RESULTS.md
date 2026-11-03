# Trạng thái triển khai và kết quả ablation

Ngày cập nhật: 03/11/2026.

**Đã triển khai công cụ, dữ liệu và kiểm thử offline. Chưa có kết quả thực nghiệm với model thật.** Chưa chọn model/version và ngân sách live, chưa đóng băng một cấu hình provider để thu kết quả test. Không dùng các số pass của gold/unit test làm Accuracy của Texa.

## Các thành phần đã hoàn thành

- F/M6/M0/C0 trong runtime; giữ hành vi mặc định F, QuerySpec/compiler/validation và giới hạn dữ liệu.
- Suite memory 24 hội thoại (12 dev / 12 test), sáu nhóm hiện tượng, dài đến 12 lượt.
- Suite clarification 20 câu mơ hồ (10 dev / 10 test), kèm 20 câu đối chứng cùng split/cluster.
- Fixture 96 event trải 50 ngày; source digest đối chiếu dữ liệu thực trong DB và checksum khóa bộ câu hỏi/gold.
- Runner dry-run/gold/live, oracle theo hành động thực tế, subprocess riêng cho variant/repeat, khóa protocol trước test.
- Reporter tổng hợp nhiều repeat, Execution Accuracy và scenario success riêng, CI theo cụm và thống kê chi phí/usage không đầy đủ.

## Kiểm chứng offline

Gold SQL đã được đối chiếu literal reference trên PostgreSQL 16.2 riêng: 38/38 lượt SQL memory dev, 39/39 memory test và 40/40 tương tác/đối chứng. Tất cả dùng fixture ablation; không có provider call.

Kiểm thử runtime và PostgreSQL dùng model giả xác nhận: F hỏi rồi nhận lựa chọn; C0 chọn từ phương án hợp lệ và vẫn đi qua resolver/compiler; M0 không đọc lịch sử; M6 chỉ thấy sáu lượt và không có đường chọn tham chiếu vượt cửa sổ. Các kiểm thử runner/report xác nhận không rò oracle, không bỏ lỗi khỏi mẫu số, không ép M6 tạo metadata riêng của F, và không xem repeats là những tình huống độc lập.

Kiểm tra backend trên fixture pilot với metadata/product integration: **139 passed, 23 skipped**. Bốn bài ablation integration được chạy riêng trên fixture ablation: **4 passed**. Các skip còn lại cần warehouse gốc hoặc fixture/opt-in khác; không tính là passed. Sau khi thêm kiểm tra tổng hợp activation, suite report riêng: **7 passed**.

## Bảng thực nghiệm — chưa chạy

| Nhóm | So sánh | Accuracy | Chênh lệch / CI95% | Thời gian / token |
|---|---|---|---|---|
| Memory | F với M6 (chính) | Chưa chạy | Chưa có | Chưa có |
| Memory | F với M0 | Chưa chạy | Chưa có | Chưa có |
| Clarification | F với C0 | Chưa chạy | Chưa có | Chưa có |
| Câu đơn v2 | F với B0 | Chưa chạy | Chưa có | Chưa có |

## Giới hạn còn lại

Dataset synthetic do nhóm tạo, chưa có PM/PO bên ngoài duyệt gold. Dev/test giữ lại scenario nhưng vẫn chia sẻ loại câu hỏi; không chứng minh tổng quát sang mọi database/người dùng. Trigger metric mơ hồ phụ thuộc vào cách LLM hiểu câu: phải kiểm tra trên dev và báo tỷ lệ component thực sự kích hoạt, không loại bỏ câu không kích hoạt khỏi mẫu số.

Ablation C0 so việc hỏi để nhận thêm thông tin với tự suy đoán; hai bên không có cùng lượng thông tin người dùng ở cuối. Báo cáo số lượt hỏi lại và kết quả cuối để thể hiện đánh đổi. Số kịch bản nhỏ có thể cho CI rộng. Không kết luận component hữu ích chỉ từ một lần chạy hoặc khi CI chưa đủ bằng chứng.

## Bước thu thập số liệu tiếp theo

1. Chọn model/provider cụ thể và giới hạn call/ngân sách.
2. Pilot trên dev, review oracle/trigger và dữ liệu; chốt rồi commit cấu hình.
3. Freeze protocol, chạy ba repeats trên test bằng matrix.
4. Sinh JSON/Markdown bằng reporter, đọc lỗi tiêu biểu rồi điền kết quả thực vào báo cáo này.

Hướng dẫn lệnh: `backend/eval/ABLATION_README.md`. Kế hoạch gốc: `docs/ABLATION_STUDY_PLAN.md`.
