# Texa — kịch bản thuyết trình (12 slide, khoảng 17 phút)

Kịch bản tiếng Việt, đồng bộ với [OUTLINE.md](OUTLINE.md). Mỗi mục có nội dung chiếu và lời nói gợi ý. Số liệu được ghi rõ là dev/demo; không phải kết quả held-out.

## 1. Hỏi dữ liệu bằng ngôn ngữ tự nhiên · 1 phút

**Trên slide**

> “Tháng trước có bao nhiêu người mua?”

- Metric nào? Nguồn nào? “Tháng trước” tính đến ngày nào?
- Kết quả đến từ đâu, định nghĩa gì?

**Lời nói**

“Texa bắt đầu từ nhu cầu rất quen thuộc: người phụ trách sản phẩm muốn hỏi dữ liệu mà không phải viết SQL. Nhưng câu hỏi tự nhiên thường để ngỏ nhiều quyết định. ‘Người mua’ là số người duy nhất hay số dòng hàng? Nguồn nào? Dữ liệu kết thúc vào ngày nào? Nếu mô hình tự chọn và trả lời bằng một con số trôi chảy, người dùng khó biết nó đã hiểu sai ở đâu. Mục tiêu của chúng em là biến câu hỏi thành một yêu cầu có cấu trúc, thực thi được và giải thích được — đồng thời biết lúc nào cần hỏi lại hoặc từ chối.”

## 2. Phạm vi sản phẩm · 1 phút 30 giây

**Trên slide**

- PostgreSQL; hai nguồn cấu hình sẵn: Cosmetics và Olist
- Một nguồn cho mỗi truy vấn; 8 metric trong catalog
- Persona PM/PO là giả thuyết; chưa có user study
- Không có: gộp nguồn, FX, order/AOV, delivery/review, phân tích nhân quả

**Lời nói**

“Phạm vi hiện tại cố ý hẹp. Mỗi truy vấn chọn một dataset — Cosmetics hoặc Olist — chứ không cộng hai cửa hàng với nhau. Catalog có tám metric: events, users, sessions, viewers, buyers, purchases, revenue và buyer conversion rate. Những tên này có định nghĩa cụ thể trong catalog, không phải các khái niệm tùy ý do mô hình nghĩ ra.

Một số giới hạn quan trọng cần nói rõ: Olist không ghi nhận lượt xem sản phẩm hay session, nên Texa không trả số không cho các metric đó mà từ chối vì thiếu dữ liệu. Olist chỉ quan sát khách đã đặt hàng; buyer/user trong nguồn này không phải tỷ lệ chuyển đổi từ mọi khách truy cập. Purchases đếm dòng sản phẩm, không phải đơn hàng. Revenue Olist cộng giá item bằng BRL, không cộng payment hay freight. Hệ thống cũng chưa làm FX, AOV/order metrics, phân tích delivery/review hay tổng hợp đa nguồn.”

## 3. Hai nguồn, hai cách quan sát · 1 phút 30 giây

**Trên slide**

| Cosmetics | Olist |
|---|---|
| Event log: view, cart, purchase | Order lifecycle và item events |
| Có session, có product view | Không có session hay product view |
| Revenue theo event mua | Revenue theo item, BRL |

**Lời nói**

“Cosmetics là event stream với các hành động như xem, thêm giỏ, bỏ giỏ và mua; nguồn này có session. Olist bắt đầu từ các bảng thương mại điện tử quan hệ và được ETL thành các event lifecycle, trong đó có dòng item mua. Hai nguồn vì thế không tương đương về thứ được quan sát.

Texa dùng một bảng event chung để giúp compiler xử lý cùng một hợp đồng metric, nhưng chuẩn hóa hình dạng dữ liệu không làm cho dữ liệu nguồn giống nhau. Catalog vẫn cần ghi rõ nguồn nào hỗ trợ metric nào, đơn vị đo là gì và giới hạn ra sao. Ví dụ, số event mua không đồng nghĩa số đơn hàng. Sự phân biệt này quan trọng hơn việc SQL có chạy hay không.”

## 4. Bài học từ Text-to-SQL · 1 phút 30 giây

**Trên slide**

- Sinh SQL trực tiếp: linh hoạt, nhưng model tự quyết định schema và nghiệp vụ
- Một SQL hợp lệ vẫn có thể trả lời sai câu hỏi
- Cần baseline trực tiếp để so sánh trên cùng dữ liệu

**Lời nói**

“Các hướng Text-to-SQL trải từ parser và biểu diễn trung gian có kiểm soát đến LLM prompting sinh SQL trực tiếp. LLM trực tiếp có ưu thế về linh hoạt và ít cần huấn luyện riêng, nhưng nó có thể chọn sai bảng, thêm breakdown không được yêu cầu hoặc diễn giải sai định nghĩa metric. Khả năng chạy được không đồng nghĩa kết quả đúng.

Vì vậy Texa không tuyên bố rằng mọi cách sinh SQL trực tiếp đều thất bại. Chúng em giữ baseline direct LLM-to-SQL dùng cùng model, schema và định nghĩa metric. Câu hỏi thực nghiệm là liệu ràng buộc bằng catalog và compiler có giúp trên workload cụ thể hay không, và cái giá về latency có chấp nhận được không.”

## 5. Semantic layer và QuerySpec · 1 phút 30 giây

**Trên slide**

```text
Câu hỏi → metric/dimension/filter trong catalog → QuerySpec → SQL
```

- LLM chọn ý định và ID đã khai báo
- Validator kiểm tra tổ hợp được hỗ trợ
- Compiler xác định phép tính và SQL

**Lời nói**

“Texa kết hợp lớp ngữ nghĩa với một biểu diễn trung gian. Catalog định nghĩa metric, dimension, từ đồng nghĩa và mapping theo nguồn. Mô hình chuyển câu hỏi thành QuerySpec — tức một yêu cầu có cấu trúc — chứ không tự viết SQL tùy ý. QuerySpec chỉ được tham chiếu ID mà catalog đã khai báo.

Đây không phải ý tưởng chưa từng có; semantic layer và intermediate representation đã xuất hiện trong các hệ thống trước. Phần chúng em xây và đánh giá là cách ghép các thành phần cho phạm vi dữ liệu này. Cấu trúc hợp lệ chỉ là một tầng kiểm soát: validator và dữ liệu vẫn phải xác nhận đúng ý định, đúng nguồn và đúng snapshot.”

## 6. Luồng thực thi · 2 phút

**Trên slide**

`intent → clarify → QuerySpec validator → deterministic SQL compiler → read-only PostgreSQL → facts → insight`

- Số liệu lấy từ kết quả truy vấn hoặc phép tính phía server
- Insight chỉ tham chiếu facts có định danh

**Lời nói**

“Đây là luồng thực tế của hệ thống. Trước hết, mô hình diễn giải ý định và tạo candidate có cấu trúc. Nếu thiếu lựa chọn quan trọng, hệ thống hỏi làm rõ. Sau đó validator đối chiếu QuerySpec với catalog, vocabulary, nguồn và các quy tắc hỗ trợ.

Khi yêu cầu hợp lệ, compiler tất định tạo SQL có tham số. Truy vấn chạy với quyền đọc PostgreSQL. Kết quả được chuyển thành facts; phép tính dẫn xuất được thực hiện phía server. Cuối cùng, mô hình viết phần diễn giải dựa trên các fact đã cấp, không tự bịa thêm số liệu. Nếu truy vấn không thể hỗ trợ câu hỏi thì hệ thống trả trạng thái phù hợp thay vì giả lập câu trả lời.

Tách vai trò như vậy giúp kiểm tra từng bước: ta có thể xem mô hình đã chọn metric nào, validator chấp nhận hay từ chối vì sao, SQL nào được biên dịch và fact nào làm căn cứ cho insight. Compiler vẫn có thể có lỗi, nên đây là thiết kế để kiểm soát và kiểm thử, không phải bảo đảm đúng tuyệt đối.”

## 7. Memory hội thoại an toàn · 1 phút 30 giây

**Trên slide**

- Structured memory: slots, câu hỏi và kết quả được phân biệt
- Tham chiếu “kết quả đó”, “câu thứ hai” cần được phân giải rõ
- Snapshot guard ngăn dùng lại kết quả từ dữ liệu/catalog khác

**Lời nói**

“Hỏi đáp nhiều lượt cần nhớ ngữ cảnh, nhưng nhớ hội thoại không có nghĩa là lấy đại một kết quả cũ. Texa lưu trạng thái có cấu trúc, phân biệt câu hỏi, slots đã xác định và các kết quả truy vấn. Các tham chiếu như ‘kết quả đó’ hay ‘câu thứ hai’ được giải quyết theo lịch sử tương ứng. Nếu tham chiếu mơ hồ hoặc không hợp lệ, hệ thống hỏi lại.

Snapshot guard ràng buộc việc tái sử dụng kết quả với dữ liệu và metadata phù hợp; kết quả thất bại hoặc từ snapshot cũ không được âm thầm thế chỗ. Đây là hành vi cần đánh giá ở cấp hội thoại, không chỉ chấm từng SQL riêng lẻ.”

## 8. Pipeline dữ liệu · 1 phút

**Trên slide**

`Cosmetics / Olist → ETL event rows → analytics.event_activity → catalog theo nguồn`

- Một hàng là một event; một query chọn một nguồn
- Nested path tối đa hai key; không expand arrays

**Lời nói**

“Pipeline đưa dữ liệu nguồn vào analytics.event_activity theo event grain đã định nghĩa. Catalog map các event khác tên về vai trò nghiệp vụ phù hợp, nhưng giữ được nguồn và giới hạn riêng. Với trường nested chỉ hỗ trợ đường dẫn scalar trong catalog tối đa hai key; hệ thống không bung arrays. Những giới hạn này làm phạm vi nhỏ hơn một hệ thống SQL tự do, nhưng giúp biết trước compiler có thể xử lý loại yêu cầu nào.”

## 9. Thiết kế đánh giá · 1 phút 30 giây

**Trên slide**

- Dataset v2: 96 events, 104 câu hỏi — 41 dev / 63 test
- Dialogue: 24 hội thoại
- Clarification: 20 câu mơ hồ + 20 câu đối chứng
- Live ablation với repeats theo protocol: chưa hoàn tất

**Lời nói**

“Đánh giá tách câu hỏi đơn khỏi hành vi hội thoại. Dataset v2 có 96 event và 104 câu: 41 câu dev, 63 câu test. Bộ hội thoại memory có 24 tình huống; bộ clarification có 20 câu mơ hồ và 20 câu đối chứng để nhận ra hỏi lại không cần thiết.

Các biến thể F, M6, M0 và C0 được định nghĩa trong protocol ablation để so sánh thành phần memory và clarification. Tuy nhiên, live ablation theo protocol với các repeats cần thiết hiện chưa hoàn tất, nên không có kết luận ablation để báo cáo. Metric truy vấn đúng kết quả và scenario success của cả hội thoại là hai chỉ số khác nhau; không gộp chúng thành một tỷ lệ.”

## 10. Kết quả dev đến hiện tại · 2 phút

**Trên slide**

| Lượt chạy | Direct SQL | Texa |
|---|---:|---:|
| Ban đầu, 41 câu dev | 40/41 | 37/41 |
| Sau tinh chỉnh, dev | — | 41/41 câu đơn; 6/6 hội thoại |

*Sau tinh chỉnh là development check, không phải held-out comparison.*

**Lời nói**

“Trong lượt ban đầu trên 41 câu dev, cùng gpt-6-luna và cùng fixture, direct LLM-to-SQL đạt 40 trên 41 câu đúng kết quả; Texa trước điều chỉnh prompt đạt 37 trên 41. SQL của cả hai chạy được ở 41 trên 41 câu — khác biệt nằm ở cấu trúc kết quả và cách hiểu yêu cầu, không phải lỗi cú pháp. Lượt đầu này không cho thấy Texa tốt hơn baseline.

Sau đó chúng em bổ sung hướng dẫn chung để phân biệt điều kiện lọc với breakdown, rồi sửa xử lý ngày và memory. Các development check tiếp theo đạt 41 trên 41 câu đơn và 6 trên 6 hội thoại, gồm 19 trên 19 lượt đạt tiêu chí. Đây là kết quả dev đã dùng để tinh chỉnh, không phải test độc lập; cũng không thay thế phép so sánh ban đầu hay chứng minh cải thiện do riêng một thay đổi. Muốn kết luận cần đóng băng phiên bản, chạy tập test chưa xem và ablation theo protocol.”

## 11. Kiểm thử demo · 1 phút

**Trên slide**

- Playwright E2E: 11/11 đạt; provider scripted
- 8 browser sessions đồng thời: smoke test
- Không phải model accuracy hoặc load test production

**Lời nói**

“Về độ ổn định demo, 11 trên 11 kiểm tra Playwright đạt, gồm luồng câu hỏi đến kết quả, hỏi làm rõ, retry, hủy và tách lịch sử giữa browser. Có smoke test cho tám browser session hỏi đồng thời. UI, API, SSE, compiler và PostgreSQL là thật; provider được scripted. Vì thế kết quả này xác nhận luồng ứng dụng hoạt động trong kịch bản, không chứng minh độ chính xác của model thật hay năng lực chịu tải production.”

## 12. Kết luận và demo · 1 phút

**Trên slide**

- LLM hiểu ý định, compiler dựng SQL: giới hạn và truy vết được
- Demo: một câu trả lời, một câu cần làm rõ, một câu ngoài phạm vi
- Tiếp theo: held-out test và live ablation

**Lời nói**

“Tóm lại, đóng góp kỹ thuật hiện tại là một luồng hỏi dữ liệu có catalog, QuerySpec, kiểm tra và SQL do compiler tất định tạo ra; mô hình tập trung vào hiểu ý định và diễn giải. Facts đầu ra có thể truy vết. Đổi lại, Texa chỉ trả lời được trong phạm vi catalog, và định nghĩa nghiệp vụ phải được xây dựng, bảo trì.

Trong demo, em sẽ lần lượt hỏi một câu có thể trả lời, một câu thiếu thông tin để hệ thống hỏi lại, và một câu hỏi metric không có ở Olist để thấy hành vi từ chối. Bước đánh giá tiếp theo là giữ nguyên phiên bản, chạy test chưa xem và hoàn tất ablation. Khi đó mới có cơ sở để nói thành phần nào tạo khác biệt. Em xin dừng ở đây và sẵn sàng nhận câu hỏi.”
