# Kịch bản thuyết trình cuối — Texa

> Phạm vi và kiến trúc hiện tại. Benchmark v6 là một lần chạy trên candidate do nhóm xây dựng; test split chưa được thẩm định độc lập và khóa kín, nên chưa phải holdout xác nhận hay bằng chứng production.

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

**Lời nói:** Mỗi nguồn có adapter ETL riêng để đưa dữ liệu về dạng event rows. Catalog mô tả metric, trường, event tương ứng, mapping và độ bao phủ. Bộ đánh giá hiện có 60 câu đơn, 24 record clarification, 9 hội thoại và 12 diagnostic cases; fixture có ba worlds, gồm 120 dòng base và phần mở rộng synthetic nested cho Olist. Đây là bộ candidate được tách dev/test đã thấy, chưa phải holdout độc lập; 60 câu đơn/9 hội thoại còn dưới mục tiêu thiết kế 180/24. Khi một nguồn không có trường hoặc event cần thiết, hệ thống phải báo không hỗ trợ thay vì trả số 0 gây hiểu nhầm.

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

- Lưu truy vấn thành công dưới dạng QuerySpec và mã kết quả, không dựa vào cửa sổ cố định sáu lượt
- Follow-up chỉ sửa đúng nhóm filter được nêu; các filter khác được giữ nguyên
- Noise không nên ghi đè truy vấn; tham chiếu mơ hồ thì hỏi lại

**Lời nói:** Memory dựa trên truy vấn thành công có cấu trúc và mã kết quả, thay vì chỉ lấy một số lượt gần nhất. Khi người dùng yêu cầu đổi một điều kiện bằng ngôn ngữ tự nhiên, mô hình xác định trường và thao tác; server chỉ cập nhật điều kiện đó, giữ các filter còn lại và kiểm tra nguồn, kỳ, metric, kết quả trước khi chạy. Người dùng không cần biết cấu trúc nội bộ. Câu xã giao không nên đổi truy vấn; nếu không rõ đang tham chiếu kết quả nào thì Texa cần hỏi lại. Cơ chế này vẫn cần đánh giá thêm trên nhiều hội thoại thực tế.

## Slide 9 — So sánh công bằng thế nào? (1:00)

- Cùng `gpt-6-luna`, cùng câu hỏi và dữ liệu
- B0: câu hỏi + schema PostgreSQL vật lý + nguồn UI nếu đã chọn; không catalog, business definitions hay enum/source mappings
- B1: thêm lịch sử hội thoại và hỏi lại/thử lại trong kịch bản tương ứng
- Texa: semantic catalog, intent resolution, memory có cấu trúc, compiler và SQL checks

**Lời nói:** Nhóm giữ nguyên model, câu hỏi và dữ liệu. Baseline chính chỉ nhận câu hỏi và cấu trúc vật lý của database, không được đưa trước định nghĩa nghiệp vụ hay catalog. Texa có thêm lớp semantic được quản trị cùng workflow chuyển câu hỏi thành truy vấn. Do baseline không biết các nhãn nguồn và giá trị đã được catalog ánh xạ, kết quả đo lợi ích tổng hợp của thông tin semantic và workflow; đây không phải cuộc thi model hay phép đo riêng tác dụng của một component.

## Slide 10 — Metric và kết quả single-question (1:10)

Metric chính là tỷ lệ khớp **toàn bộ bảng kết quả**; khác alias được chấp nhận, nhưng không được thiếu/thừa cột, hàng hay giá trị. Strict contract được theo dõi riêng.

| Cấu hình | Dev / 30 | Test / 30 |
|---|---:|---:|
| B0 schema-only | 3 (10,0%) | 1 (3,3%) |
| B0R + ví dụ SQL | 11 (36,7%) | 16 (53,3%) |
| B1 + history | 2 (6,7%) | 1 (3,3%) |
| Texa T00 | 29 (96,7%) | 28 (93,3%) |
| Texa T10 · T01 | 29 · 29 | 27 · 27 |
| Texa T11 | 29 (96,7%) | 30 (100%) |

**Lời nói:** Trên 30 câu single test, B0 đúng một câu, T00 đúng 28 và T11 đúng cả 30. Đây là một lần chạy trên bộ candidate tổng hợp, không phải accuracy cho mọi tình huống thực tế. B0 chỉ có schema vật lý nên phần chênh lệch cũng phản ánh việc Texa có catalog và ánh xạ business value; không thể quy toàn bộ cho compiler hay workflow. Ở đối chứng cung cấp cùng nguồn đã chọn trên 30 câu dev, B0 đạt 13/30 (43,3%) và Texa 28/30 (93,3%); vẫn còn khác biệt tri thức catalog. B0R là đối chứng riêng có ví dụ SQL đã kiểm chứng, không gọi là baseline thuần.

## Slide 11 — Ablation, clarification và hội thoại (1:10)

| Suite test | B1 | T00 | T10 | T01 | T11 |
|---|---:|---:|---:|---:|---:|
| Clarification / 12 | 1 (8,3%) | 12 (100%) | 11 (91,7%) | 11 (91,7%) | 11 (91,7%) |
| Conversation / 24 lượt | 1 (4,2%) | 22 (91,7%) | 19 (79,2%) | 20 (83,3%) | 22 (91,7%) |

- T00 tắt retrieval/consistency; T10 bật retrieval; T01 bật adaptive consistency; T11 bật cả hai
- T11 đạt 30/30 single test trong một repeat; không phải overall accuracy
- Consistency được gọi ở 1/30 câu test của T01; retrieval và consistency vẫn tắt mặc định

**Lời nói:** Ablation kiểm tra từng thành phần nhưng chưa đủ để tuyên bố retrieval hay consistency luôn làm hệ thống tốt hơn. T00 tốt hơn một số toggle ở clarification hoặc hội thoại; T11 cao nhất ở single test. Adaptive consistency chỉ được kích hoạt một lần trong 30 câu T01, nên đây là chính sách gọi có điều kiện, không phải ba lần gọi cho mọi câu. Các feature vẫn để mặc định tắt cho đến khi có thêm lần chạy và holdout độc lập.

## Slide 12 — Chi phí, độ trễ và kiểm thử sản phẩm (1:15)

- Median latency single test: B0 **8,1 giây**; Texa T00 **12,8 giây**
- Chi phí ước tính/30 câu: B0 **$0,0062**; Texa T00 **$0,0263**
- Backend **383 passed, 36 skipped**; DB integration **30 passed**; Playwright **15 passed** với provider giả lập
- Browser thật: 5/6 câu khớp; view count trả 12 thay vì 24
- Browser regression benchmark riêng: T00 15/15 single, 18/19 lượt hội thoại; không phải holdout/UI E2E

**Lời nói:** Texa cho kết quả đúng hơn trong bộ single test này, nhưng median chậm hơn khoảng năm giây và chi phí ước tính cao hơn. Kiểm thử backend, database và Playwright xác nhận luồng phần mềm bằng provider giả lập; chúng không đo chất lượng model thật. Trên giao diện thật, chuỗi filter cho ra 62, sau khi bỏ mobile vẫn giữ paid là 204, rồi đổi sang desktop và vẫn giữ paid là 61; unique viewers là 12 và Olist revenue là 432 BRL, khớp CSV. Một truy vấn đếm views vẫn sai 12 so với chuẩn 24. Các bài browser là kịch bản hồi quy nhỏ, không đại diện cho tải lớp học.

## Slide 13 — Kết luận và giới hạn (0:45)

- Texa tập trung vào PM/PO hỏi dữ liệu event e-commerce đã định nghĩa trên PostgreSQL
- Benchmark v6 cho tín hiệu mạnh trên candidate, nhưng chưa tách riêng giá trị workflow khỏi semantic knowledge
- Cần review đáp án độc lập, khóa holdout mới, lặp lại benchmark và kiểm tải trước khi mở rộng

**Lời nói:** Kết quả v6 cho thấy Texa vượt baseline schema-only rõ rệt trên bộ câu hỏi hiện tại. Tuy nhiên baseline không được cung cấp enum hay business mapping, nên chênh lệch gồm cả lợi ích tri thức catalog; ta chưa thể khẳng định riêng kiến trúc workflow tạo ra toàn bộ phần tăng. Bộ test còn nhỏ, test split chưa được thẩm định độc lập và chưa khóa, và giao diện thật còn một lỗi đếm views. Bước tiếp theo là review gold độc lập, tạo holdout mới, lặp lại phép đo và thử tải nhiều người dùng trước khi kết luận khả năng triển khai rộng.

### Ghi chú cho người trình bày

- B0/B1/Texa đều dùng cùng model và fixtures; baseline không có catalog, định nghĩa business hay source-value mapping. Đây là so sánh hệ thống với thông tin đầu vào khác nhau, không phải model ranking.
- Candidate gồm 60 câu đơn (30 dev/30 test), 24 clarification records (12 cặp query/control), 9 hội thoại (8 lượt dev/24 lượt test), 12 diagnostic; tổng hợp và chưa có holdout sealed/human-reviewed.
- Browser parity (T00 15/15 câu đơn; 18/19 lượt hội thoại) là replay trên câu đã biết. Browser UI có một lỗi thực: event views trả 12 thay vì 24.
- T11 đạt 30/30 test single ở một repeat; không gộp suite thành overall accuracy. Retrieval/consistency mặc định vẫn off.
- Source-selected control: B0 13/30 (43,3%), T00 28/30 (93,3%); khoảng cách còn chịu ảnh hưởng của catalog/business mappings.
- Frozen SQL replay trên ba fixture worlds không phải ba repeat độc lập; số đúng mỗi cấu hình lần lượt B0 1/30, B0R 16/30, B1 1/30, T00 28/30, T10/T01 27/30, T11 30/30.
- Persona PM/PO chưa được xác nhận qua user study; không suy rộng hai nguồn hiện tại sang mọi doanh nghiệp.
