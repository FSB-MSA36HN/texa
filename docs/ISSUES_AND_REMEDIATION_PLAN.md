# Texa — vấn đề còn lại và kế hoạch xử lý

Cập nhật 09/11/2026. Đây là tracker cho kiến trúc hiện tại; độ chính xác đánh giá dùng Baseline duy nhất được định nghĩa tại `PRODUCT_SCOPE.md`.

## Trạng thái đánh giá

Trên research-v3, Baseline đạt **356/400 (89,00%)** và Texa đạt **365/400 (91,25%)** trên 200 câu test, hai lần chạy. Chênh lệch 2,25 điểm phần trăm là quan sát exploratory, chưa đủ kết luận Texa vượt ổn định: bộ v3 chưa human-reviewed/sealed, dùng fixture tổng hợp và có family overlap. Baseline chỉ được chấm trên câu đơn. Hội thoại, clarification và ngoài scope được báo riêng; không gán số của các suite này cho Baseline.

Research-v4 có thiết kế family-disjoint và oracle từ CSV độc lập, nhưng CSV Cosmetics hiện có không khớp hash/đáp án đã đóng băng. Không dùng v4 để báo điểm cho đến khi dữ liệu được khôi phục hoặc bộ gold được tái tạo và kiểm định.

## Vấn đề và cách xử lý tận gốc

| Ưu tiên | Vấn đề / nguyên nhân | Hướng xử lý | Tiêu chí nghiệm thu |
|---|---|---|---|
| P0 | Raw enum và thuật ngữ nghiệp vụ khác nhau theo nguồn; nếu mapping không rõ, LLM chọn nhầm literal hoặc metric | Catalog quản lý source-specific field/value mapping, metric grain và khả năng hỗ trợ; validator từ chối mapping thiếu thay vì đoán | Unit + integration test theo từng source, giá trị thiếu phải được hỏi lại hoặc từ chối có lý do |
| P0 | Metric cùng tên nhưng khác grain/ý nghĩa giữa event, purchase, buyer và revenue | Mỗi metric có contract khai báo grain, numerator/denominator, filter, null policy, source applicability; compiler sinh SQL theo contract | Golden tests bao phủ sibling metrics, duplicate grain, null và counterexample |
| P1 | Memory hội thoại có thể kế thừa nhầm điều kiện cũ khi user đổi một slot | Lưu QuerySpec slots cùng provenance và explicit keep/set/clear; chỉ kế thừa slot không bị sửa; hỏi lại khi tham chiếu mơ hồ | Test chuỗi dài hơn 6 lượt, noise, filter đổi một phần, clear/set và ambiguous reference |
| P1 | Clarification phụ thuộc vào model tự nhận ra mơ hồ | Metric Resolver dùng required slots và ambiguity policy theo metric; hỏi field cụ thể, không suy đáp án từ gold | Đo hỏi đúng khi thiếu, không hỏi thừa khi đủ dữ kiện, độ đúng của bảng cuối |
| P1 | LLM có thể gợi ý SQL/insight vượt capability của nguồn hoặc trộn nguồn | Capability registry và source scope là contract bắt buộc; kiểm tra trước khi sinh và trước khi chạy | Unsupported/source-conflict tests, không chạy SQL khi capability không được khai báo |
| P1 | Chọn nguồn trên UI và nguồn user nói có thể mâu thuẫn | Resolver phát hiện conflict; yêu cầu xác nhận trước khi truy vấn, không âm thầm đổi scope | Source mismatch E2E và test API không tạo query trước khi xác nhận |
| P1 | Benchmark hiện tại chưa đủ bằng chứng độc lập | Giữ v3 để tái lập; sửa/khôi phục nguồn v4, review câu hỏi/gold độc lập, freeze holdout, ghi provenance | 2 reviewer, không lỗi validator, family-disjoint, đủ coverage trước khi gọi model |
| P1 | Runner có thể chậm hoặc mất tiến độ khi provider timeout/crash | Queue có checkpoint per case, bounded concurrency, retry transient error, stop khi auth/budget lỗi, atomic output | Resume không gọi lại case hoàn tất; budget global; không báo run complete khi thiếu IDs |
| P2 | Latency/cost khác nhau theo độ phức tạp câu hỏi và consistency calls | Trace latency/token theo từng bước, bật consistency theo risk trigger, giới hạn calls | Báo p50/p95/calls/cost theo task; profiling trước khi tối ưu cache/index |
| P2 | UI có thể nói quá mức độ chắc chắn hoặc tạo insight không truy nguyên được | Trả metric, kỳ, nguồn, filter và provenance; phân biệt dữ liệu quan sát với suy luận | Snapshot UI tests và manual usability review với PM/PO |

## Nguyên tắc thực hiện

1. Tái hiện lỗi và xác định boundary nơi sai lệch bắt đầu: resolver, semantic binding, compiler, database result hay presentation.
2. Sửa contract hoặc state transition tại boundary; không hardcode câu hỏi, literal hoặc output để làm test xanh.
3. Thêm regression case mô tả hiện tượng tổng quát, không sao chép riêng input của bug.
4. Chạy unit, integration và E2E phù hợp; benchmark model chỉ chạy sau khi gold, inputs và budget preflight đạt.
5. Giữ default thay đổi sau khi có bằng chứng, provenance và rollback path; nếu chưa có bằng chứng, mô tả giới hạn thay vì hứa chính xác tuyệt đối.

## Thứ tự ưu tiên

1. Khôi phục độ nhất quán catalog/schema và metric grain.
2. Hoàn thiện memory/clarification state transitions và source conflict handling.
3. Sửa và seal benchmark độc lập; dùng cùng Baseline và Texa trên test đóng băng.
4. Dùng runner resumable để đo latency/cost và scale concurrency.
5. Chốt trải nghiệm UI, caveat và classroom load test.
