# Kịch bản thuyết trình cuối — Texa

> Phạm vi và kiến trúc hiện tại. Kết quả benchmark là exploratory trên một repeat của bộ dev đã thấy; không phải sealed human holdout hay bằng chứng production.

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

**Lời nói:** Mỗi nguồn có adapter ETL riêng để đưa dữ liệu về dạng event rows. Catalog mô tả metric, trường, event tương ứng, mapping và độ bao phủ. Bộ đánh giá hiện có 60 câu đơn, 24 record clarification, 9 hội thoại và 12 diagnostic cases; fixture có ba worlds, gồm 120 dòng base và phần mở rộng synthetic nested cho Olist. Đây là candidate dev, không phải dữ liệu holdout độc lập. Khi một nguồn không có trường hoặc event cần thiết, hệ thống phải báo không hỗ trợ thay vì trả số 0 gây hiểu nhầm.

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

## Slide 9 — Cách đánh giá và các đối chứng (1:10)

- Cùng model `gpt-6-luna`, cùng câu hỏi và dữ liệu
- B0: cùng model sinh SQL trực tiếp; B0R thêm ví dụ đã SQL-verify
- B1: baseline history văn bản thuần; T00/T10/T01/T11 bật/tắt retrieval và self-consistency
- Chấm strict business contract; world check alias-insensitive full values là metric phụ

**Lời nói:** Nhóm giữ cùng model, câu hỏi và dữ liệu. B0 sinh SQL trực tiếp; B0R thêm retrieval ví dụ SQL đã xác minh. B1 là baseline dùng history văn bản thuần, không có đường QuerySpec/compiler của Texa. Với Texa, T00 tắt retrieval và consistency; T10 bật retrieval, T01 bật self-consistency, T11 bật cả hai. Bank có 45 ví dụ, 42 được agent duyệt; trong đó 7 có SQL được thực thi kiểm chứng độc lập; cùng tập 7 được dùng để so sánh retrieval. Self-consistency lấy tối đa ba mẫu, có giới hạn và không đoán khi thiếu thông tin. Điểm chính chấm strict business contract; kiểm tra world bổ sung so sánh full values nhưng bỏ qua alias output. Hai cách chấm không được gộp.

## Slide 10 — Single-dev: diagnostic, chưa kết luận hiệu quả (1:30)

| Cấu hình | Strict business / 30 | Full values / 30* |
|---|---:|---:|
| B0 | 29 | 29 |
| B0R | 29 | 29 |
| B1 | 25 | 25 |
| T00 · T10 · T01 · T11 | 27 · 26 · 28 · 27 | 29 · 28 · 29 · 28 |

- Một repeat trên candidate dev; C19 score dùng annotation erratum hash-pinned
- *Full values là posthoc alias-insensitive; các count trên giống nhau ở cả ba fixture worlds
- Không có cải thiện nào được chứng minh; feature toggles vẫn là thử nghiệm

**Lời nói:** Trên 30 single-dev cases, bảng đối chiếu strict business và world check full values cho thấy các cấu hình có thể khác nhau khi bỏ qua alias. Full values là metric bổ sung, không thay score chính; ba fixture worlds cho cùng counts. C19 được sửa bằng annotation erratum tường minh, hash-pinned, chỉ tính lại từ raw full-result correctness. Đây là một repeat trên dev đã thấy, chưa có reviewer độc lập hay sealed human holdout. Các số này không chứng minh retrieval hay consistency cải thiện kết quả.

## Slide 11 — Retrieval và self-consistency: chưa chứng minh lợi ích (1:05)

- T10 chỉ bật retrieval; T01 chỉ bật consistency; T11 bật cả hai
- Bank 45 ví dụ; 7 ví dụ có SQL được kiểm chứng độc lập là tập đối chứng chung
- Consistency tối đa ba mẫu, bounded; không suy đoán khi thiếu thông tin

**Lời nói:** Đây là toggle factorial: T10 chỉ bật retrieval, T01 chỉ bật consistency, T11 bật cả hai. Retrieval dùng bank 45 ví dụ, trong đó tập bảy ví dụ có SQL được kiểm chứng độc lập là tập so sánh chung. Consistency chỉ lấy tối đa ba mẫu, bị giới hạn và không đoán thông tin thiếu. Một lượt dev chưa đủ để kết luận tính năng nào giúp ích; trong các số hiện tại T00 đạt 27, T10 26, T01 28, T11 27 trên 30 câu. Các toggle vẫn tắt mặc định cho đến khi có đánh giá độc lập lặp lại.

## Slide 12 — Hội thoại, kiểm thử sản phẩm và giới hạn (1:15)

- Hỏi lại: B1 9/12; Texa T00 10/12, T10 12/12, T01 11/12, T11 10/12
- Bốn hội thoại ngắn chạy lại: B1 7/8; T00/T10/T01 8/8; T11 7/8
- Backend **323 passed, 36 skipped**; Playwright **15/15** với provider mô phỏng
- Browser model thật: **19/21** bảng đúng; hai câu view/viewers bị từ chối sai
- Sau 13 kết quả + noise, tham chiếu kết quả thứ hai chọn đúng Olist và chia tháng đúng

**Lời nói:** Bộ hỏi lại và bốn hội thoại ngắn có tín hiệu tích cực, nhưng chỉ là một lượt trên dev đã thấy. Trong kiểm tra trình duyệt, nhóm dùng sản phẩm trực tiếp, thử hai nguồn, SQL/CSV, hỏi lại, nguồn xung đột, lọc và xóa filter, hủy/thử lại và tải lại lịch sử. Có 19 trên 21 câu chấm bằng bảng khớp SQL viết độc lập; hai câu bị từ chối sai dù dữ liệu hỗ trợ. Memory quay lại đúng kết quả thứ hai sau 13 kết quả thành công và câu nhiễu. Diagnostic cũng phát hiện một lượt retrieval trả lời AOV bằng chỉ số khác; vì vậy tính năng mới chưa bật mặc định. Các số này phản ánh kịch bản synthetic đã thử, chưa bảo đảm độ đúng chung hay tải cả lớp.

## Slide 13 — Kết luận (0:45)

- Texa là trợ lý hỏi dữ liệu có phạm vi và định nghĩa được kiểm soát
- Điểm mạnh cần chứng minh bằng đánh giá độc lập, không bằng demo đơn lẻ
- Ưu tiên tiếp: xử lý lỗi semantic còn lại, thẩm định gold độc lập, rồi đo lại trên holdout mới

**Lời nói:** Texa tập trung vào một bài toán hẹp: giúp PM/PO hỏi dữ liệu event thương mại điện tử trong phạm vi đã khai báo. Hệ thống có bước làm rõ, kiểm tra semantic và tạo truy vấn có thể kiểm tra, nhưng điều đó không bảo đảm kết quả luôn đúng. Trên candidate dev hiện tại, baseline cao hơn hoặc tương đương một số toggle; chưa có cải thiện nào được chứng minh. Việc tiếp theo là xử lý các lỗi semantic còn lại, thẩm định gold độc lập và đánh giá trên holdout mới. Xin cảm ơn.

### Ghi chú cho người trình bày

- Số single-dev mới là một repeat trên 30 cases đã thấy; annotation erratum C19 được hash-pin và chỉ thay score từ raw result correctness. World values là metric phụ, alias-insensitive.
- Hội thoại repaired dùng số ở slide 12; raw conversation comparison đầu không hợp lệ do lỗi adapter B1. Diagnostic action là mức khớp rubric, không phải SQL accuracy.
- Cũ protocol v3/v4 chỉ giữ trong kết quả lịch sử, không đưa lên headline hoặc gộp với current single-dev.
- Persona PM/PO là định hướng sản phẩm chưa được xác nhận qua user study.
- Dữ liệu hai nguồn giữ nguyên tiền tệ và ngữ nghĩa riêng; không cộng hai nguồn.
