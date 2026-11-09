# Texa — kế hoạch đánh giá và cải thiện độ chính xác

Cập nhật 09/11/2026. Tài liệu này mô tả cấu hình sản phẩm và phép đánh giá hiện hành.

## Mục tiêu

Texa phục vụ PM, PO và cấp quản lý cần câu trả lời phân tích có thể kiểm tra căn cứ. Phạm vi hiện tại giới hạn ở dữ liệu event e-commerce trên PostgreSQL; metric và phép tổng hợp do semantic catalog định nghĩa. Không tuyên bố hỗ trợ mọi doanh nghiệp, mọi schema hoặc mọi database.

## Kiến trúc hiện tại

```text
Câu hỏi + nguồn đã chọn → truy hồi ví dụ đã xác minh
→ LLM đề xuất ý định/tham chiếu + consistency khi cần
→ binder/clarification → QuerySpec + kiểm tra capability/ngữ nghĩa
→ compiler Python sinh SQL tham số hóa → PostgreSQL chỉ đọc
→ facts có provenance → câu trả lời có metric, nguồn, kỳ và cách tính
```

Consistency chỉ chạy với câu có tín hiệu rủi ro, tạo thêm tối đa hai cách hiểu; lựa chọn phải dựa trên QuerySpec hợp lệ và kiểm tra ngữ nghĩa, không chỉ bỏ phiếu trên chuỗi SQL. Memory lưu slot truy vấn có cấu trúc (kỳ, metric, filter, breakdown, nguồn) cùng provenance; thay đổi slot phải được ghi nhận rõ.

## Baseline và kết quả hiện hành

**Baseline** dùng cùng model, câu hỏi, schema và định nghĩa nghiệp vụ như Texa. LLM sinh SQL trực tiếp; nếu SQL lỗi khi thực thi, được một lần thử sửa với loại lỗi an toàn. Baseline không dùng QuerySpec, compiler, validator hay memory của Texa.

Trên research-v3, 200 câu test × hai lần chạy: Baseline đạt **356/400 (89,00%)**, Texa đạt **365/400 (91,25%)**. Đây là exploratory result: test chưa được review độc lập/sealed, fixture tổng hợp và có family overlap. Baseline câu đơn không đại diện cho hội thoại, clarification hay từ chối ngoài phạm vi; các suite này cần metric riêng và không gán điểm single-query cho chúng.

## Protocol chấm

- Chạy cùng model, prompt inputs đã đóng băng, test IDs, database fixture và giới hạn gọi.
- Đúng khi toàn bộ bảng kết quả khớp bảng chuẩn: cột/role, số hàng, giá trị, NULL, duplicate, tolerance số và ordering cho top-k. Alias không cần giống nhau.
- SQL lỗi, từ chối sai hoặc không có kết quả được tính là không đúng trong mẫu số; không bỏ case lỗi.
- Báo accuracy cùng latency, token/cost; báo riêng theo nguồn và nhóm độ khó. Bootstrap theo family là phân tích exploratory, không biến số lần gọi thành mẫu độc lập.
- Lưu hash dataset, catalog, code, prompt policy và model cùng raw JSONL. Một lần chạy không được trộn artifact có provenance khác.

## Nâng chất lượng benchmark

Giữ v3 để tái lập kết quả hiện tại. Trước khi dùng v4, phải khôi phục đúng CSV Cosmetics khớp manifest hoặc tái tạo bộ câu hỏi/đáp án từ file hiện có rồi kiểm định toàn bộ gold; không dùng đáp án đang lệch dữ liệu. Sau đó cần hai reviewer độc lập, tách family dev/test, kiểm tra câu hỏi paraphrase tự nhiên và khóa test trước khi chạy model. Có thể giữ một challenge set có counterexample cho grain, metric và filter; báo riêng nó với test phân bố từ người dùng.

## Thứ tự công việc

1. Khóa catalog, metric contract, model và fixture cho mỗi lần đo.
2. Kiểm tra gold độc lập và structural gates trước khi gọi LLM.
3. Chạy Baseline và Texa trên cùng test, giới hạn concurrency và ngân sách; checkpoint từng case, retry lỗi tạm thời, không lặp case đã hoàn thành.
4. Tính accuracy từ raw outputs bằng scorer cố định; lưu báo cáo và provenance.
5. Chỉ thay đổi một component mỗi ablation; so với Texa đầy đủ trên cùng IDs và cùng rubric. Không chọn baseline hay dataset theo mục tiêu làm Texa thắng.
6. Chỉ tuyên bố cải thiện khi paired analysis và review dữ liệu hỗ trợ kết luận; nếu chưa đủ, trình bày chênh lệch như quan sát.
