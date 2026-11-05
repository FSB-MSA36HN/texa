# Kịch bản thuyết trình cuối — Texa (khoảng 15 phút)

## Slide 1 — Texa: hỏi dữ liệu bằng ngôn ngữ tự nhiên (0:45)

- Text-to-SQL trên semantic catalog
- Con số có thể kiểm tra; cách tính có thể kiểm soát

**Lời nói:** Xin chào thầy cô và các bạn. Texa giúp hỏi dữ liệu thương mại điện tử bằng ngôn ngữ tự nhiên. Hệ thống chuyển yêu cầu thành phép tính đã định nghĩa, chạy trên PostgreSQL và trình bày kết quả cùng phạm vi, SQL để kiểm tra. Mô hình hỗ trợ hiểu câu chữ; phép tính vẫn phải đối chứng được.

## Slide 2 — Một câu hỏi ngắn, nhiều lựa chọn ẩn (1:10)

- Ví dụ: “Doanh thu tháng trước là bao nhiêu?”
- Cần xác định nguồn, thời gian, định nghĩa doanh thu và độ sẵn có của dữ liệu
- Trả lời được không đồng nghĩa đã trả lời đúng câu hỏi

**Lời nói:** Một câu hỏi ngắn vẫn cần xác định nguồn, tháng nào trong dữ liệu và định nghĩa doanh thu. Cộng payment thay vì giá trị hàng hóa có thể cho SQL hợp lệ nhưng sai nghiệp vụ. Texa cần làm rõ yêu cầu, kiểm tra dữ liệu hỗ trợ phép đo và cho thấy nguồn gốc kết quả. Khi mơ hồ, hệ thống nên hỏi lại thay vì đoán.

## Slide 3 — Mục tiêu và câu hỏi cần kiểm chứng (1:00)

- Hiểu đúng câu hỏi và tính đúng kết quả trong phạm vi hỗ trợ
- Làm rõ mơ hồ; từ chối có căn cứ khi thiếu dữ liệu
- Đo đánh đổi về thời gian, token và chi phí

**Lời nói:** Nhóm hỏi: Texa hiểu và tính đúng đến đâu; có biết lúc nào làm rõ hay từ chối vì thiếu dữ liệu; và các bước kiểm soát tốn bao nhiêu thời gian, tài nguyên? Đây là câu hỏi nghiên cứu, không phải giả định Texa tốt hơn gọi mô hình trực tiếp.

## Slide 4 — Sản phẩm và phạm vi hiện tại (1:15)

- PostgreSQL; chọn một nguồn cho mỗi truy vấn
- Hai nguồn cấu hình sẵn: Cosmetics và Olist
- Persona sản phẩm: PM/PO theo dõi chỉ số sản phẩm thương mại điện tử
- 8 metric; catalog giới hạn dimensions/filter và nested scalar tối đa hai cấp
- Không join/cộng hai nguồn; không arrays, FX, order/AOV, delivery/review

**Lời nói:** Texa hướng tới PM/PO theo dõi chỉ số sản phẩm thương mại điện tử bằng những câu hỏi nhanh, như lượt xem hay người mua. Hệ thống dùng PostgreSQL với hai nguồn đã ánh xạ: REES46 Cosmetics và Brazilian Olist; mỗi query chỉ dùng một nguồn. Tám metric gồm events, users, sessions, viewers, buyers, purchases, revenue và buyer conversion rate. Nested field chỉ hỗ trợ scalar đến hai key, không mở arrays. Order/AOV, FX và delivery/review nằm ngoài scope; persona và nhu cầu vẫn cần walkthrough xác nhận.

## Slide 5 — Dữ liệu, ETL và hợp đồng nguồn (1:20)

- Adapter đưa dữ liệu về event rows trong PostgreSQL
- Registry/metadata ghi nguồn, thời gian, event, field và coverage
- Catalog định nghĩa phép tính, ánh xạ, đơn vị và giới hạn
- Snapshot cố định giúp benchmark so sánh có ý nghĩa

**Lời nói:** Adapter riêng đưa mỗi nguồn về event rows trong PostgreSQL. Metadata mô tả ngày, event và field; catalog quy định metric cùng ánh xạ. Đây là ETL cụ thể, không phải bộ hiểu mọi database. Cosmetics có session và product views; Olist không có nên sessions/viewers phải báo unavailable, không trả 0. Snapshot phiên bản hóa giúp lần chạy benchmark dùng cùng dữ liệu.

## Slide 6 — Kiến trúc: từ câu hỏi đến insight có nguồn (1:30)

- LLM tạo candidate; resolver chuẩn hóa và hỏi lại khi thiếu/mơ hồ
- QuerySpec được validate, kiểm tra availability
- Python compiler sinh SQL PostgreSQL có tham số; reader chạy read-only
- Server tạo facts; LLM diễn đạt insight dựa trên facts

**Lời nói:** Mô hình diễn giải câu hỏi thành candidate; resolver xác định nguồn, metric, thời gian và filter, rồi hỏi lại nếu thiếu hoặc mơ hồ. QuerySpec được validate và kiểm tra availability. Compiler Python sinh SQL xác định từ catalog; reader chạy với timeout và giới hạn dòng. Server tính facts, còn mô hình chỉ diễn đạt insight dựa trên chúng. QuerySpec hợp lệ chưa chứng minh hiểu đúng; cần đo kết quả truy vấn.

## Slide 7 — Ví dụ QuerySpec (1:15)

- “Doanh thu theo danh mục của Cosmetics tháng 12/2019”
- Nguồn: Cosmetics; metric: revenue; breakdown: item_category
- Kỳ: 01–31/12/2019; không tự thêm filter hoặc nhóm theo ngày

**Lời nói:** Với câu “Doanh thu theo danh mục của Cosmetics tháng 12/2019”, QuerySpec ghi source, metric revenue, breakdown danh mục và khoảng 1–31/12. Không tự thêm filter hay chia theo ngày. Nếu tháng hoặc breakdown sai, lỗi nằm ở diễn giải; nếu QuerySpec đúng mà bảng sai, cần kiểm tra compiler, dữ liệu hoặc phép tính.

## Slide 8 — Memory hội thoại có kiểm soát (1:10)

- Lưu QuerySpec thành công cùng provenance tới lượt hỏi
- Noise/lỗi không ghi đè truy vấn đã commit; clarification là state tách biệt
- Hỗ trợ tham chiếu theo vị trí và “kết quả đó”; mơ hồ thì hỏi lại
- Snapshot đổi sẽ chặn kế thừa kết quả cũ

**Lời nói:** Memory lưu truy vấn thành công có cấu trúc và provenance, thay vì chỉ lấy sáu lượt gần nhất như biến thể M6. Câu xã giao/lỗi không ghi đè state; clarification đang chờ cũng tách biệt. Texa hỗ trợ “kết quả đó”, “câu đầu”, “kết quả thứ hai”; tham chiếu không rõ thì hỏi lại. Snapshot/catalog đổi sẽ chặn kế thừa kết quả cũ. Memory không bảo đảm hiểu mọi cách nói.

## Slide 9 — Các con số có đúng nghĩa không? (1:20)

- `purchases` đếm item events, không phải số order
- Olist revenue cộng item price trên `order_purchased`, không cộng payment/freight
- Olist không có visitor đầy đủ; buyer/users không phải visitor conversion
- Giữ tiền tệ gốc: Cosmetics USD, Olist BRL

**Lời nói:** `purchases` đếm item events, không phải orders. Olist revenue cộng item price tại `order_purchased`, không cộng payment/freight. Giữ nguyên USD cho Cosmetics, BRL cho Olist, không tự quy đổi. Olist chỉ có khách từng đặt hàng, không phải toàn bộ visitors; buyer/users vì vậy không phải visitor conversion. Câu trả lời cần nêu các giới hạn này.

## Slide 10 — Benchmark và baseline (1:35)

- v2: 96 synthetic events; 104 câu đơn (41 dev, 63 test), 12 hội thoại
- Baseline B0: cùng model, schema và metric definitions, sinh SQL trực tiếp
- Execution Accuracy so bảng kết quả thực thi với gold; lỗi/timeout vẫn tính sai
- Bổ sung diagnostic hai nguồn: 16 event tổng hợp, 24 câu đơn + 6 tình huống (dev)
- Chưa có test holdout độc lập hoặc kết quả ablation nhiều repeats

**Lời nói:** v2 có 96 event tổng hợp, 104 câu đơn (41 dev, 63 test) và 12 hội thoại. Baseline B0 nhận cùng schema, định nghĩa metric và sinh SQL trực tiếp. Execution Accuracy so bảng PostgreSQL với gold; SQL lỗi, timeout, từ chối sai và sai cấu trúc đều tính trong mẫu số. Ablation có 24 hội thoại/77 lượt trả lời, 20 câu mơ hồ và 20 control: F là pipeline đầy đủ, M6 chỉ dùng sáu lượt gần nhất, M0 không dùng memory, C0 bỏ clarification trong các trường hợp protocol cho phép. Bộ diagnostic bổ sung 24 câu đơn và 6 tình huống cho hai nguồn: kiểm tra tổng/ngày/danh mục/trend, kết quả rỗng, không cộng payment vào revenue, chuyển nguồn khi hỏi tiếp, hỏi lại và từ chối ngoài scope. Đã kiểm tra 27/27 gold SQL của bộ mới khớp bảng đáp án trên PostgreSQL, nhưng chưa chạy model trên bộ này. Các bộ đều là tổng hợp; chưa đo accuracy trên dữ liệu Olist thật hay người dùng thật.

## Slide 11 — Kết quả hiện có và cách diễn giải (1:45)

Đo ngày 04/11/2026, `gpt-6-luna`, cùng 41 câu đơn **dev** và snapshot v2:

| Cấu hình | Kết quả đúng | Tỷ lệ | Trung vị thời gian |
|---|---:|---:|---:|
| B0: LLM sinh SQL trực tiếp | 40/41 | 97,6% | 5,925 giây |
| Texa trước chỉnh prompt | 37/41 | 90,2% | 9,986 giây |
| Texa sau chỉnh filter/breakdown — vòng dev riêng | 41/41 | 100% | 8,967 giây |

Hội thoại dev sau sửa date/memory: **6/6 scenario**, 19/19 lượt đạt tiêu chí; trước sửa là 1/6. Texa đo cả bước viết insight, B0 chỉ sinh SQL. Không dùng các vòng tinh chỉnh này để kết luận thắng trên test.

**Lời nói:** Vòng đầu dev với `gpt-6-luna`: B0 đạt 40/41, Texa 37/41; SQL thực thi được 41/41 ở cả hai. Median latency là 5,925 và 9,986 giây; Texa còn tạo insight. Lỗi phổ biến là tự breakdown khi chỉ cần filter. Sau điều chỉnh hướng dẫn, vòng dev riêng đạt 41/41 câu đơn; hội thoại chuyển từ 1/6 lên 6/6 qua các vòng chỉnh khác. Đây không phải A/B trên test. Chưa có test holdout hay ablation nhiều repeats, nên chưa thể kết luận Texa vượt baseline.

## Slide 12 — Demo, giới hạn và kết luận (1:35)

- Demo: hỏi, xem scope/định nghĩa, kiểm tra bảng và SQL, hỏi tiếp
- Regression mới nhất: backend 169 đạt/23 bỏ qua; scripted E2E 11/11
- Olist mới được kiểm thử contract/SQL, chưa benchmark model thật
- Bước tiếp theo: freeze, test holdout, ablation repeats và walkthrough PM/PO

**Lời nói:** Demo theo một hành trình: PM hỏi doanh thu Cosmetics tháng 12/2019, xem breakdown theo danh mục, rồi thêm một điều kiện bằng câu tiếp nối; sau đó hỏi revenue Olist để thấy nguồn phải được nêu rõ và tiền tệ vẫn là BRL. Regression mới nhất: backend 169 đạt/23 bỏ qua; scripted E2E 11/11. Đây xác nhận luồng kỹ thuật, không phải accuracy model. Olist qua contract/SQL tests nhưng chưa benchmark model thật. Tiếp theo cần freeze, chạy 63 câu test, ablation nhiều lượt và walkthrough PM/PO. Texa đã triển khai pipeline có phạm vi và truy vết; chưa đủ bằng chứng để khẳng định ưu thế tổng quát. Xin cảm ơn.


### Ghi chú cho người trình bày

Mạch kể rút từ slide mẫu: vấn đề → sản phẩm/phạm vi → dữ liệu → phương pháp → ví dụ → đánh giá → demo/giới hạn. Đã bỏ literature review. Bảng điểm chấm **kết quả thực thi**, không lấy QuerySpec khớp làm bằng chứng kết quả đúng.

Số liệu đối chiếu từ JSONL local (Git ignored) trong `backend/eval/results/`: `luna-direct-dev-20261104.jsonl`, `luna-texa-dev-20261104-migrated.jsonl`, `luna-texa-dev-20261104-filter-prompt.jsonl`, `luna-texa-dialogue-dev-20261104-memory-fix.jsonl`. Bản tóm tắt số liệu được lưu tại `data/benchmark/development_results.json`; raw log không được đóng gói cùng hai tài liệu. Các số regression/E2E là lần kiểm thử đã ghi nhận trước lần thu gọn tài liệu, không phải kết quả chạy mới trong lần này.
