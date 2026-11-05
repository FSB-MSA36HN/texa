# Đánh giá Texa

Cập nhật 05/11/2026. Câu hỏi cần trả lời: **các bước xử lý của Texa giúp trả lời đúng hơn hay có đánh đổi gì so với gọi LLM trực tiếp?** Nhóm đề xuất một hệ thống, không huấn luyện một model nền tảng mới.

## Baseline và điều kiện so sánh

B0 là cùng LLM nhận câu hỏi, schema và định nghĩa nghiệp vụ rồi sinh SQL trực tiếp. Texa dùng cùng LLM nhưng có thêm semantic catalog, resolver/hỏi lại, structured memory, QuerySpec validation và SQL compiler. Baseline không bị giấu schema hay định nghĩa metric. Cùng snapshot dữ liệu, model/provider và điều kiện tài nguyên đã khai báo.

Vòng thăm dò đã dùng `gpt-6-luna`; lựa chọn này giúp cố định một model và kiểm tra kiến trúc trong ngân sách, không chứng minh đây là model tốt nhất thị trường. Nếu đổi model, phải báo một cấu hình/thí nghiệm riêng. Latency Texa gồm viết insight trong khi B0 chỉ sinh SQL; cần nói rõ khác biệt khi so tốc độ/token.

## Metric chính

**Execution Accuracy = số yêu cầu có kết quả truy vấn khớp đáp án chuẩn / tổng yêu cầu cần trả lời.** Chạy SQL trên PostgreSQL, so tên/cấu trúc cột và giá trị theo scorer, thứ tự khi bài yêu cầu, xử lý NULL/kiểu số theo quy tắc evaluator. Không yêu cầu chuỗi SQL giống nhau. SQL lỗi, timeout, sai schema kết quả hoặc từ chối sai vẫn nằm trong mẫu số.

Ví dụ minh họa: gold trả một tổng doanh thu; hệ thống trả tổng theo từng ngày thì sai dù các số ngày cộng lại đúng. QuerySpec đúng các trường được khai báo chỉ là metric chẩn đoán; không thay thế kết quả thực thi.

Hội thoại đo thêm action đúng (answer/clarify/refuse/conversation), các slot được gán nhãn, tham chiếu đúng, hỏi lại thiếu/thừa và **scenario success**: toàn bộ yêu cầu bắt buộc của hội thoại đạt. Không gọi scenario success là tỷ lệ memory đúng thuần túy. Báo latency, tokens, tỷ lệ thực thi được và chi phí như metric phụ. Chấm kết quả SQL chưa chấm toàn bộ chất lượng văn phong/nhận xét hay tính hữu ích với PM/PO.

## Dataset

| Bộ | Nội dung | Mục đích |
|---|---|---|
| [Pilot](../data/benchmark/README.md) | Fixture 12 events, 24 câu đơn | Regression/E2E nhỏ, không thay v2 |
| [v2](../data/benchmark/v2/README.md) | 96 synthetic events; 104 câu đơn (41 dev/63 test); 12 hội thoại | So B0–Texa, chẩn đoán hội thoại |
| [Ablation v1](../data/benchmark/ablation_v1/README.md) | 96 events trên 50 ngày; 24 hội thoại/77 answer turns; 20 câu mơ hồ + 20 control | Tách ảnh hưởng memory và hỏi lại |

Gold gồm SQL và bảng kết quả literal, có reference aggregator Python tách khỏi compiler Texa. Validate gold khớp DB chỉ xác nhận fixture/annotation, không đo model. Dataset tự xây có thiên lệch và pattern overlap; cần review độc lập. Synthetic benchmark không đo trực tiếp accuracy trên Olist hoặc Cosmetics, dù sản phẩm hỗ trợ cả hai nguồn.

Giữ nguyên file/hashes đã freeze; không sửa gold theo output model. Dev dùng tinh chỉnh; test giữ cho đánh giá sau freeze. Không nạp chồng pilot/v2/ablation khi một runner khác đang chạy; cả ba dùng partition `event_benchmark` của DB riêng `texa_benchmark`.

## Ablation study

| So sánh | Thay đổi kiểm soát | Điều muốn kiểm tra |
|---|---|---|
| F–M6 | Structured memory so với sáu lượt gần nhất | Truy hồi xa, noise và quay lại chủ đề |
| F–M0 | Có memory so với không đọc lịch sử | Đóng góp ngữ cảnh hội thoại |
| F–C0 | Hỏi lại so với tự chọn/đoán một lần khi form thuộc phạm vi | Giá trị thông tin làm rõ và chi phí tương tác |
| F–B0 | Full pipeline so với direct LLM SQL | Toàn hệ thống; không cô lập riêng compiler |

F vẫn validate/compiler. M6/M0 không tắt kiểm tra SQL. C0 chỉ xử lý form một trường metric hoặc time_range theo protocol; không được thấy oracle/gold. Chỉ cấp oracle khi F hỏi đúng trường/lựa chọn; báo activation và trường hợp ngoài phạm vi, không bỏ case xấu khỏi mẫu số.

Chốt code/model/prompt/config trên dev, commit và freeze protocol; chạy test nhiều repeats trong process riêng, cùng tập scenario, báo mean/sd, chênh lệch và CI theo whole-scenario cluster. Xem [kế hoạch](ABLATION_STUDY_PLAN.md) và [lệnh chạy](../backend/eval/ABLATION_README.md). Không quy cải thiện cho component chỉ từ một lần chạy sau chỉnh prompt.

## Kết quả có thể trình bày

Ngày 04/11/2026, cùng model trên v2 dev: B0 **40/41**, Texa ban đầu **37/41**; sau chỉnh hướng dẫn filter Texa **41/41**. Hội thoại dev ban đầu **1/6**, sau chẩn đoán/sửa date và memory **6/6**. Đây là các vòng phát triển riêng; không phải A/B trên test chưa xem, không phải ablation và không phải kết quả model trên Olist mới bật lại ngày 05/11. Chi tiết latency/cost và artifact ở [demo checks](CLASS_DEMO_CHECKS.md).

Chưa có kết quả test 63 câu độc lập hoặc matrix ablation nhiều repeats. Câu trả lời phù hợp khi bảo vệ: “Nhóm đã kiểm tra được pipeline và sửa lỗi trên dev. Nhóm sẽ freeze cấu hình rồi so baseline và ablation trên test; hiện chưa kết luận Texa tốt hơn baseline.”

## Công cụ cũ

`backend/eval/run_golden.py`/`golden.yaml` chấm trạng thái và một số trường đã khai báo cho catalog/workload cũ. Nó là regression bổ sung; không phải execution accuracy và không phải bộ đánh giá chính của scope hiện tại. Không trộn số lượng case golden cũ với 63 câu test của v2.
