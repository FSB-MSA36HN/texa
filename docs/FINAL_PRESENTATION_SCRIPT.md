# Kịch bản thuyết trình cuối — Texa

> Phạm vi và kiến trúc hiện tại. Các kết quả benchmark bên dưới là diagnostic trên bộ regression đã nhìn thấy, không phải holdout độc lập hay bằng chứng production.

## Slide 1 — Texa: hỏi dữ liệu thương mại điện tử bằng ngôn ngữ tự nhiên (0:40)

- Trợ lý phân tích cho PM/PO và quản lý không chuyên SQL
- Hỏi bằng tiếng Việt/Anh, xem bảng và SQL có thể kiểm tra

**Lời nói:** Texa giúp người quản lý đặt câu hỏi về dữ liệu thương mại điện tử bằng ngôn ngữ tự nhiên. Hệ thống chuyển yêu cầu thành truy vấn trong phạm vi đã định nghĩa, trả kết quả cùng phạm vi và SQL để kiểm tra. Texa hỗ trợ quyết định, không thay chuyên viên dữ liệu và không cam kết LLM luôn đúng.

## Slide 2 — Vì sao câu hỏi đơn giản vẫn có thể sai? (0:55)

- “Doanh thu tháng trước” cần biết kỳ nào, nguồn nào và doanh thu được định nghĩa ra sao
- SQL chạy được chưa chắc đúng ý nghiệp vụ
- Không đủ thông tin thì cần hỏi lại hoặc giải thích giới hạn

**Lời nói:** Một câu hỏi ngắn có thể có nhiều cách hiểu. “Doanh thu” có thể là tiền hàng hay khoản thanh toán; “tháng trước” phải tính theo dữ liệu và thời điểm nào. Truy vấn hợp lệ về cú pháp vẫn có thể sai nghĩa. Vì vậy sản phẩm cần làm rõ yêu cầu và nói rõ khi dữ liệu không hỗ trợ.

## Slide 3 — Người dùng và mục tiêu sản phẩm (0:55)

- Định hướng: PM/PO, quản lý sản phẩm/kinh doanh không chuyên SQL
- Muốn xem nhanh chỉ số, lọc/chia nhóm, đổi kỳ và hỏi tiếp
- Persona mới là giả thuyết sản phẩm, cần kiểm chứng với người dùng thật

**Lời nói:** Texa được định hướng cho PM, PO và quản lý cần tự xem số liệu mà không phải viết SQL. Đây hiện là giả thuyết sản phẩm, chưa phải kết luận từ nghiên cứu người dùng. Mục tiêu là giúp họ tự xem các chỉ số cơ bản, đồng thời giữ định nghĩa và nguồn dữ liệu đủ rõ để kiểm tra.

## Slide 4 — Phạm vi có chủ đích (1:05)

- Một domain: event thương mại điện tử; một engine: PostgreSQL
- Hai nguồn cấu hình: Cosmetics Shop và Brazilian Olist; mỗi truy vấn dùng một nguồn
- Tám metric có định nghĩa riêng; nested scalar tối đa hai key, theo path được khai báo
- Không chuẩn hóa mọi database; không join hai nguồn, arrays, FX, order/AOV, delivery/review

**Lời nói:** Nhóm thu hẹp bài toán vào event thương mại điện tử trên PostgreSQL, với hai nguồn đã cấu hình là Cosmetics và Olist. Một truy vấn chỉ dùng một nguồn; hai nguồn không bị gộp vì khác cấu trúc và tiền tệ. Hệ thống hỗ trợ tám metric trong catalog, cùng các filter và breakdown được khai báo. Nested chỉ đọc scalar theo path đã biết, tối đa hai key; không bung arrays. Các phần như order/AOV, delivery/review hay quy đổi tiền tệ chưa thuộc phạm vi.

## Slide 5 — Tám metric nghĩa là gì? (1:00)

- Events, users, sessions, viewers, purchases, buyers, revenue, buyer conversion rate
- `purchases` là item lines, không phải số order
- Revenue theo tiền tệ nguồn: USD hoặc BRL; không cộng payment/freight Olist
- Olist không có visitor đầy đủ; thiếu metric là unavailable, không phải 0

**Lời nói:** Tám metric là tám phép đo đã định nghĩa, không phải chỉ có tám câu hỏi. Người dùng có thể phối hợp kỳ, filter và breakdown trong giới hạn catalog. Có lưu ý quan trọng: purchases đếm item lines chứ không phải số đơn; Olist revenue cộng giá trị item purchase theo BRL, không cộng payment hoặc freight. Olist không ghi nhận toàn bộ visitors nên buyer conversion không được diễn giải là conversion từ visitor.

## Slide 6 — Dữ liệu và lớp ngữ nghĩa (1:10)

- Adapter riêng đưa từng nguồn về event rows trong PostgreSQL
- Catalog quản lý metric, event role, field, mapping và coverage
- Một semantic contract dùng chung cho xử lý, kiểm tra khả năng và giải thích kết quả

**Lời nói:** Mỗi nguồn có adapter ETL riêng để đưa dữ liệu về dạng event rows. Catalog mô tả metric, trường, event tương ứng, mapping và độ bao phủ. Đây không phải cơ chế biến kiến trúc của mọi công ty thành một schema chung; Texa chỉ xử lý các nguồn đã cấu hình. Khi một nguồn không có trường hoặc event cần thiết, hệ thống phải báo không hỗ trợ thay vì trả số 0 gây hiểu nhầm.

## Slide 7 — Từ câu hỏi đến kết quả có thể kiểm tra (1:20)

```text
Câu hỏi + nguồn
 → LLM đề xuất intent/reference có cấu trúc
 → semantic binder + clarification + memory
 → QuerySpec và kiểm tra capability
 → Python compiler sinh SQL tham số hóa
 → PostgreSQL read-only → facts có provenance → câu trả lời/bảng
```

**Lời nói:** Trong pipeline sản phẩm, mô hình không tự viết SQL cuối cùng. Mô hình đề xuất ý định có cấu trúc; binder ánh xạ khái niệm và giá trị theo catalog. Nếu thiếu kỳ, xung đột nguồn hoặc mơ hồ thì Texa hỏi lại. QuerySpec được kiểm tra capability rồi compiler Python sinh SQL tham số hóa để chạy read-only trên PostgreSQL. Kết quả được gắn nguồn gốc trước khi hiển thị bảng và nhận xét.

## Slide 8 — Memory hội thoại (1:00)

- Lưu truy vấn thành công dưới dạng QuerySpec và mã kết quả, không chỉ giữ sáu lượt gần nhất
- Câu tiếp theo có thể tham chiếu kết quả trước; server kiểm tra target và snapshot trước khi kế thừa
- Noise không nên ghi đè truy vấn; tham chiếu mơ hồ thì hỏi lại

**Lời nói:** Memory hiện dựa trên các truy vấn thành công có cấu trúc và mã kết quả, không phải quy tắc cố định lấy sáu lượt gần nhất. Khi người dùng nói “kết quả thứ hai”, server tìm trong registry kết quả và kiểm tra nguồn, kỳ, catalog trước khi kế thừa. Câu xã giao không nên làm đổi truy vấn. Nếu không xác định chắc đang nói tới kết quả nào, Texa cần hỏi lại. Một chuỗi demo thành công chưa chứng minh mọi cách diễn đạt đều được hiểu đúng.

## Slide 9 — Cách đánh giá (1:10)

- Cùng model `gpt-6-luna`, cùng câu hỏi và dữ liệu
- B0: model sinh SQL trực tiếp từ câu hỏi/schema/định nghĩa metric
- Texa: cùng model qua binder, hỏi lại, memory, kiểm tra catalog và compiler
- Chấm bảng kết quả SQL với đáp án chuẩn; không so chuỗi SQL

**Lời nói:** Để xem phần logic hệ thống có giúp ích không, nhóm giữ cùng model, câu hỏi và dữ liệu. Baseline B0 yêu cầu model sinh SQL trực tiếp. Texa dùng cùng model nhưng thêm bước hiểu intent, ánh xạ semantic, hỏi lại khi cần, kiểm tra phạm vi và biên dịch truy vấn. Metric chính là tỷ lệ truy vấn trả đúng bảng đáp án theo hợp đồng đã định nghĩa; SQL khác nhau vẫn có thể đúng nếu kết quả tương đương.

## Slide 10 — Benchmark hiện có: chưa thể nói Texa tốt hơn (1:30)

| Cấu hình | Đúng | Tỷ lệ |
|---|---:|---:|
| B0 — LLM sinh SQL trực tiếp | 41/48 | 85,4% |
| Texa — pipeline hiện tại | 35/48 | 72,9% |

- Bộ regression v3 đã được xem trong quá trình sửa; kết quả mang tính mô tả
- B0 cao hơn 6/48 câu (12,5 điểm %); chưa có holdout độc lập
- Không dùng kết quả này để tuyên bố hiệu quả tổng quát

**Lời nói:** Trên lượt regression hiện tại, B0 đúng 41 trên 48 câu, còn Texa đúng 35 trên 48. Vì vậy ở bộ câu hỏi này baseline cao hơn 12,5 điểm phần trăm. Đây là bộ regression đã được nhóm xem trong quá trình sửa, nên chỉ dùng để tìm lỗi và theo dõi hồi quy; không phải holdout độc lập. Kết quả chưa chứng minh Texa tốt hơn. Bước tiếp theo là đóng băng code và protocol, thẩm định đáp án độc lập, rồi đánh giá trên bộ holdout mới.

## Slide 11 — Ablation study: kết quả ban đầu và giới hạn (1:05)

- Ablation tắt/bật một thành phần để xem nó đóng góp gì
- Memory: phép so sánh hiện tại có câu hỏi discussion chưa có cách chấm SQL-result; không hợp lệ để kết luận hiệu quả
- Clarification protocol v4: F 6/6, tắt hỏi lại C0 1/6; chỉ hai tình huống × ba lần, đã nhìn thấy

**Lời nói:** Ablation là so sánh Texa đầy đủ với phiên bản bỏ một thành phần, ví dụ bỏ memory hoặc bỏ hỏi lại. Nhưng không phải cứ có con số là kết luận được. Bộ memory hiện có một câu trả lời thảo luận từ bảng trước mà chưa định nghĩa hợp đồng chấm đúng; vì vậy phép so sánh memory không hợp lệ để kết luận hiệu quả. Bộ clarification v3 thiếu oracle kỳ báo cáo nên được giữ nguyên và đánh dấu không hợp lệ. Protocol v4 đã khai báo đủ ý định người dùng và chỉ trả lời trường hệ thống hỏi: Texa đúng 6/6 lượt, còn bản tắt hỏi lại đúng 1/6. Hai tình huống lặp ba lần cho thấy ích lợi trên các ca này, chưa chứng minh hiệu quả tổng quát.

## Slide 12 — Kiểm thử sản phẩm và giới hạn bằng chứng (1:15)

- Backend 261 test đạt, 12 skip; Playwright 15/15 với provider mô phỏng.
- Một chuỗi model thật: sau 12 kết quả, “kết quả thứ hai” chọn đúng Olist tháng 01/2018
- 31 dòng revenue theo ngày khớp SQL độc lập trong lần kiểm tra đó
- Đây là kiểm tra kịch bản, không phải tỷ lệ chính xác chung hay kiểm thử tải lớp học
- Cần kiểm holdout mới, nhiều hội thoại/paraphrase và tải đồng thời thực tế

**Lời nói:** Trong một chuỗi kiểm thử model thật, sau khi tạo 12 kết quả, Texa chọn đúng kết quả Olist tháng 1/2018 khi được hỏi “kết quả thứ hai”; 31 dòng doanh thu theo ngày khớp với SQL độc lập. Đây là bằng chứng cho đúng kịch bản đó, không thể suy ra memory luôn đúng. Kiểm thử nhiều phiên hiện tại cũng chưa xác định sức chứa cho cả lớp. Cần thêm holdout mới, hội thoại độc lập và kiểm thử tải sát cách lớp sẽ dùng.

## Slide 13 — Kết luận (0:45)

- Texa là trợ lý hỏi dữ liệu có phạm vi và định nghĩa được kiểm soát
- Điểm mạnh cần chứng minh bằng đánh giá độc lập, không bằng demo đơn lẻ
- Ưu tiên tiếp: sửa protocol đánh giá, tạo holdout, đo lại B0/Texa và ablation

**Lời nói:** Texa tập trung vào một bài toán hẹp: giúp PM/PO hỏi dữ liệu event thương mại điện tử trong phạm vi đã khai báo. Hệ thống có các bước kiểm soát để làm rõ câu hỏi và tạo truy vấn có thể kiểm tra, nhưng điều đó không bảo đảm kết quả luôn đúng. Benchmark hiện tại chưa cho thấy Texa hơn baseline; memory ablation chưa đủ điều kiện kết luận; clarification mới có bằng chứng trên hai tình huống. Việc tiếp theo là hoàn thiện protocol, thẩm định gold và đánh giá lại trên dữ liệu holdout độc lập. Xin cảm ơn.

### Ghi chú cho người trình bày

- Số liệu B0 41/48 (85,4%) và Texa 35/48 (72,9%) là kết quả regression diagnostic v3 đã nhìn thấy; gọi là kết quả mô tả, không gọi là accuracy tổng quát hay kết quả holdout.
- Không công bố hiệu quả memory ablation vì thiếu contract discussion. Clarification v4 là 6/6 so với 1/6 trên hai tình huống × ba lần; không gọi là sáu tình huống độc lập, không gộp với điểm câu đơn.
- E2E 12-result/31-row là một scripted real-model check. Không suy rộng thành đảm bảo chung hoặc capacity cho demo đông người.
- Persona PM/PO là định hướng sản phẩm chưa được xác nhận qua user study.
- Dữ liệu hai nguồn giữ nguyên tiền tệ và ngữ nghĩa riêng; không cộng hai nguồn.
