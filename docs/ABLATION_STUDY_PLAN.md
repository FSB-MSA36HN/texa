# Kế hoạch còn lại: controlled ablation

Công cụ/runtime và suite đã được triển khai. Xem [trạng thái đánh giá canonical](EVALUATION.md), [kết quả dev](CLASS_DEMO_CHECKS.md), và [hướng dẫn chạy/protocol](../backend/eval/ABLATION_README.md). Tài liệu này thay kế hoạch triển khai cũ; chỉ liệt kê thí nghiệm và review còn lại.

## Phạm vi và câu hỏi

Đối chiếu Texa đầy đủ (F) với từng thay đổi riêng: M6 (cửa sổ 6 lượt), M0 (không đọc lịch sử/không tái dùng kết quả), C0 (không hỏi lại trong các trigger hỗ trợ). B0 là baseline hệ thống riêng—LLM sinh SQL trực tiếp—không phải ablation compiler. Giữ QuerySpec, compiler, validation và an toàn thực thi như cũ. C0 chỉ kích hoạt đúng các form một trường `time_range` hoặc `recipe`; ghi nhận trigger không kích hoạt, không loại khỏi mẫu số.

Product scope cấu hình: Cosmetics + Olist, một source cho mỗi truy vấn, tám metric, nested scalar tối đa hai cấp khóa. Các benchmark pilot/v2/ablation ở đây dùng fixture **synthetic**, không phải dữ liệu Olist và không đo accuracy trên Olist. V2 có 41 dev và 63 test; ablation suite riêng có 24 dialogue (12/12) và 20 ambiguous/control pairs. Test đã được xem trong quá trình phát triển dataset, nên không gọi là holdout pristine.

## Còn phải làm

1. Trên dev, kiểm tra trigger/oracle, fixture, phiên bản model/provider và budget; chỉ sửa implementation hoặc prompt trên dev. Ghi các vòng riêng biệt—kết quả đã có trên dev là exploratory, không gộp các phiên bản.
2. Chốt reviewer nghiệp vụ nếu có thể, commit/prompt/catalog/dataset, DSN fixture đúng, cấu hình model/generation/retry/timeout và call budget. Dùng lệnh `--freeze-protocol` trong run guide; không đổi cấu hình sau khi xem test.
3. Chạy holdout single-turn v2 (63 câu) và ablation suites F/M6/M0, F/C0 trên test theo ma trận/repeats đã freeze. Chạy mỗi variant/repeat process riêng, thứ tự xen kẽ, hội thoại độc lập; giữ tất cả lỗi/timeout/không trả lời trong mẫu số. Lưu mỗi lần chạy vào output mới.
4. Dùng reporter để đối chiếu cùng scenario/repeat. Báo Execution Accuracy, scenario success, kết quả cuối C0, trigger/clarification, nhóm hiện tượng, p50/p95, calls/token; paired cluster CI và biến thiên repeats. Không xem repeats là mẫu độc lập, không gán B0–F cho riêng compiler.
5. Cập nhật kết quả và giới hạn tại `docs/EVALUATION.md` / `docs/ABLATION_STUDY_RESULTS.md`, giữ artifacts/log và ghi rõ phiên bản. Nếu test được dùng để sửa hệ thống, đánh dấu vòng mới thay vì giữ nhãn kết quả đã khóa.

## Diễn giải và giới hạn

M6 có thể trả lời đúng nhưng không có metadata `context.references`; đây là chẩn đoán chứ không phải tiêu chí bắt buộc. C0 so hỏi để lấy thêm thông tin với tự suy đoán, vì vậy phải báo cả kết quả cuối và số lượt tương tác. Tách nhóm câu cần memory/clarification khỏi câu đơn giản; kết quả synthetic không chứng minh hiệu quả production hay trên mọi database. Mọi cách mở rộng scope, thêm component bị tắt, hoặc sửa gold cần version mới và review riêng.
