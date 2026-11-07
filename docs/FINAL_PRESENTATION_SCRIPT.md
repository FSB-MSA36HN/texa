# Kịch bản thuyết trình cuối — Texa

> Benchmark research-v3: hai lần chạy cùng model và fixture. Bộ test do nhóm xây dựng, còn family overlap, chưa human-review/sealed; kết quả exploratory, chưa phải holdout độc lập hay bằng chứng production.

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

**Lời nói:** Mỗi nguồn có adapter ETL riêng để đưa dữ liệu về dạng event rows. Catalog mô tả metric, trường, event tương ứng, mapping và độ bao phủ. Bộ đánh giá gồm 300 câu đơn (100 dev/200 test), 60 tình huống clarification, 40 hội thoại dài 6–12 lượt (355 lượt; 308 answer slots) và 40 câu ngoài phạm vi. Cosmetics/Olist và nested extensions là synthetic. Gold SQL qua 2.004 kiểm tra trên ba fixture worlds; model chỉ chạy trên world base, không phải ba lần benchmark. Khi một nguồn không có trường hoặc event cần thiết, hệ thống phải báo không hỗ trợ thay vì trả số 0 gây hiểu nhầm.

## Slide 7 — Từ câu hỏi đến kết quả có thể kiểm tra (1:20)

```text
Câu hỏi + nguồn
 → Truy hồi ví dụ SQL đã xác minh
 → LLM đề xuất intent/reference + adaptive consistency khi cần
 → semantic binder + clarification + memory
 → QuerySpec và kiểm tra capability
 → Python compiler sinh SQL tham số hóa
 → PostgreSQL read-only → facts có provenance → câu trả lời/bảng
```

**Lời nói:** Trong pipeline sản phẩm, mô hình không tự viết SQL cuối cùng. Texa truy hồi ví dụ liên quan đã xác minh, rồi mô hình đề xuất ý định có cấu trúc. Khi cần, adaptive consistency lấy thêm mẫu cùng model và so các phương án đã chuẩn hóa; không bỏ qua guard hoặc đoán thông tin thiếu. Binder ánh xạ khái niệm và giá trị theo catalog. Nếu thiếu kỳ, xung đột nguồn hoặc mơ hồ thì Texa hỏi lại. QuerySpec được kiểm tra capability rồi compiler Python sinh SQL tham số hóa để chạy read-only trên PostgreSQL. Kết quả được gắn nguồn gốc trước khi hiển thị bảng và nhận xét.

## Slide 8 — Memory hội thoại (1:00)

- Lưu truy vấn thành công dưới dạng QuerySpec và mã kết quả, không dựa vào cửa sổ cố định sáu lượt
- Follow-up chỉ sửa đúng nhóm filter được nêu; các filter khác được giữ nguyên
- Noise không nên ghi đè truy vấn; tham chiếu mơ hồ thì hỏi lại

**Lời nói:** Memory dựa trên truy vấn thành công có cấu trúc và mã kết quả, thay vì chỉ lấy một số lượt gần nhất. Khi người dùng yêu cầu đổi một điều kiện bằng ngôn ngữ tự nhiên, mô hình xác định trường và thao tác; server chỉ cập nhật điều kiện đó, giữ các filter còn lại và kiểm tra nguồn, kỳ, metric, kết quả trước khi chạy. Người dùng không cần biết cấu trúc nội bộ. Câu xã giao không nên đổi truy vấn; nếu không rõ đang tham chiếu kết quả nào thì Texa cần hỏi lại. Cơ chế này vẫn cần đánh giá thêm trên nhiều hội thoại thực tế.

## Slide 9 — So sánh công bằng thế nào? (1:00)

- Cùng `gpt-6-luna`, cùng câu hỏi và dữ liệu
- LLM chỉ nhận schema: câu hỏi + schema PostgreSQL vật lý + nguồn UI nếu đã chọn; không catalog, business definitions hay enum/source mappings
- LLM có lịch sử chat: thêm lịch sử hội thoại và hỏi lại/thử lại trong kịch bản tương ứng
- Texa: semantic catalog, intent resolution, memory có cấu trúc, compiler và SQL checks

**Lời nói:** Nhóm giữ nguyên model, câu hỏi và dữ liệu. Baseline chính chỉ nhận câu hỏi và cấu trúc vật lý của database, không được đưa trước định nghĩa nghiệp vụ hay catalog. Texa có thêm lớp semantic được quản trị cùng workflow chuyển câu hỏi thành truy vấn. Do baseline không biết các nhãn nguồn và giá trị đã được catalog ánh xạ, kết quả đo lợi ích tổng hợp của thông tin semantic và workflow; đây không phải cuộc thi model hay phép đo riêng tác dụng của một component.

## Slide 10 — Metric và kết quả single-question (1:10)

Metric chính là tỷ lệ khớp **toàn bộ bảng kết quả**; khác alias được chấp nhận, nhưng không được thiếu/thừa cột, hàng hay giá trị. Strict contract được theo dõi riêng.

| Cấu hình | Single test, 200 câu × 2 lần |
|---|---:|---:|
| LLM chỉ nhận schema | 90/400 (22,5%) |
| Texa without retrieval and consistency | 350/400 (87,5%) |
| Texa with only consistency | 348/400 (87,0%) |
| Texa with only retrieval | 361/400 (90,25%) |
| **Texa** | 365/400 (91,25%) |

**Lời nói:** Mỗi cấu hình được đánh giá trên 200 câu test độc lập hai lần, tức 400 answer executions. Baseline schema-only đạt 22,5%; Texa đạt 91,25%. Ablation cho thấy Texa with only retrieval đạt 90,25%, Texa with only consistency 87%, và Texa without retrieval and consistency 87,5%. Vì baseline không có catalog hay mapping nghiệp vụ mà Texa có, khoảng cách đo cả tri thức semantic lẫn workflow; không thể kết luận toàn bộ mức tăng đến từ kiến trúc xử lý.

## Slide 11 — Ablation, clarification và hội thoại (1:10)

| Suite | LLM có lịch sử chat | Texa without retrieval and consistency | Texa with only retrieval | Texa with only consistency | **Texa** |
|---|---:|---:|---:|---:|---:|
| Clarification cuối, 60 case × 2 | 27,5% | 99,2% | 99,2% | 100% | 100% |
| Hội thoại, 308 answer slots × 2 | 91/616 (14,8%) | 563/616 (91,4%) | 592/616 (96,1%) | 567/616 (92,0%) | 584/616 (94,8%) |
| Ngoài phạm vi, action accuracy (40 × 2) | 5,0% | 83,75% | 86,25% | 93,75% | 95,0% |

- Bộ clarification thay thế: final-table accuracy baseline 27,5%; Texa 100%; ablations 99,2–100%. Hỏi lại đúng: baseline 67,5%; Texa without retrieval and consistency và Texa with only consistency 100%; Texa with only retrieval 99,2%; Texa 100%.
- Hội thoại chấm theo bảng chuẩn từng answer slot, không dùng legacy scenario-success.

**Lời nói:** Kết quả hội thoại khác câu hỏi đơn: Texa with only retrieval đạt 96,1%, cao nhất suite này, còn Texa đạt 94,8%. Clarification mới có final-table accuracy 100% cho Texa; baseline đạt 27,5%. Tỷ lệ hỏi lại đúng là 100% với Texa và hai cấu hình Texa without retrieval and consistency, Texa with only consistency; Texa with only retrieval đạt 99,2%, baseline 67,5%. Các thành phần không cải thiện mọi loại yêu cầu đồng đều. Ngoài phạm vi, Texa đạt 95% action accuracy. Kết quả còn exploratory vì test chưa được rà soát độc lập và còn family overlap.

### Ablation bổ sung: memory và clarification

| Phiên bản | Hội thoại, business accuracy | Clarification, business accuracy | Hỏi lại đúng |
|---|---:|---:|---:|
| Texa with structured memory | 84,58% (521/616) | — | — |
| Texa with only window-6 memory | 85,55% (527/616) | — | — |
| Texa without memory | 83,93% (517/616) | — | — |
| Texa with clarification | — | 86,67% (104/120) | 75,00% (90/120) |
| Texa without clarification | — | 62,50% (75/120) | 50,00% (60/120) |

**Lời nói:** Bảng này là một ablation khác với retrieval/consistency. Tất cả biến thể vẫn giữ retrieval và consistency; chỉ thay memory hoặc clarification. Structured memory cao hơn without memory khoảng 0,65 điểm phần trăm, còn window-6 đạt 85,55% trên bộ này. Clarification tạo chênh lệch rõ hơn: bật hỏi lại đạt 86,67% so với 62,50% khi tắt. Đây là kết quả exploratory, cần mở rộng hội thoại trước khi kết luận window-6 hay structured memory khác nhau ổn định.

## Slide 12 — Chi phí, độ trễ và kiểm thử sản phẩm (1:15)

- Median latency trên 400 lần chạy: LLM chỉ nhận schema **7,7 giây**; Texa **13,8 giây**
- Chi phí ước tính/400 lần chạy: LLM chỉ nhận schema **$0,074**; Texa **$0,401**
- Backend **398 passed, 36 skipped**; DB integration **30 passed**; Playwright **15 passed** với provider giả lập
- Browser observations trước đây: 5/6 câu khớp; view count khi đó trả 12 thay vì 24. Đây là kết quả lịch sử, không thuộc benchmark mới.
- Browser regression benchmark cũ: Texa without retrieval and consistency 15/15 single, 18/19 lượt hội thoại; chỉ là replay trên câu đã biết.

**Lời nói:** Texa cho kết quả đúng hơn trong bộ câu đơn, với median 13,8 giây so với 7,7 giây của baseline; tổng chi phí ước tính cho 400 lượt là 0,401 USD so với 0,074 USD. Các quan sát browser trên slide là từ phiên kiểm thử cũ: khi đó một câu đếm views trả 12 thay vì 24. Chúng không phải E2E mới hay kết quả benchmark research-v3.

## Slide 13 — Kết luận và giới hạn (0:45)

- Texa tập trung vào PM/PO hỏi dữ liệu event e-commerce đã định nghĩa trên PostgreSQL
- Research-v3 có hai lần chạy và bộ câu hỏi đa dạng hơn, nhưng chưa tách riêng giá trị workflow khỏi semantic knowledge
- Cần review đáp án độc lập, khóa holdout mới, lặp lại benchmark và kiểm tải trước khi mở rộng

**Lời nói:** Trên 200 câu hỏi đơn chạy hai lần, Texa đạt 91,25% so với 22,5% của baseline chỉ có schema. Đây là chênh lệch lớn trong candidate benchmark, nhưng baseline thiếu catalog và mapping nghiệp vụ; vì vậy chưa thể quy mức tăng riêng cho workflow Texa. Hội thoại và câu ngoài phạm vi được chấm riêng. Dữ liệu synthetic, có template overlap và chưa được human-review hay khóa kín. Cần review gold độc lập và holdout mới trước khi khẳng định khả năng tổng quát hóa.

### Ghi chú cho người trình bày

- LLM chỉ nhận schema/LLM có lịch sử chat/Texa đều dùng cùng model và fixtures; baseline không có catalog, định nghĩa business hay source-value mapping. Đây là so sánh hệ thống với thông tin đầu vào khác nhau, không phải model ranking.
- Research-v3 gồm 300 câu đơn (100 dev/200 test), 60 clarification cases, 40 hội thoại (355 lượt; 308 answer slots) và 40 câu ngoài phạm vi; dữ liệu synthetic, còn family overlap, chưa human-reviewed/sealed.
- Browser parity (Texa without retrieval and consistency 15/15 câu đơn; 18/19 lượt hội thoại) là replay trên câu đã biết. Browser UI đã đo với Texa without retrieval and consistency có một lỗi thực: event views trả 12 thay vì 24.
- Single-question business accuracy: baseline schema-only 22,5%; Texa 91,25%; Texa without retrieval and consistency 87,5%; Texa with only consistency 87%; Texa with only retrieval 90,25% (400 executions mỗi cấu hình).
- Hai lần gọi model benchmark chạy trên fixture base; ba worlds chỉ dùng để kiểm tra 2.004 gold SQL/world checks.
- Quan sát browser trước đây chỉ là lịch sử, không khẳng định có E2E mới trong research-v3.
- Persona PM/PO chưa được xác nhận qua user study; không suy rộng hai nguồn hiện tại sang mọi doanh nghiệp.
