# Kịch bản thuyết trình cuối — Texa (khoảng 16–18 phút)

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
- Ablation memory: 12 hội thoại holdout / 39 lượt gold; clarification: 20 scenario holdout
- Cùng `gpt-6-luna`, code và dữ liệu đóng băng; ba lần lặp
- Diagnostic đa nguồn riêng: 17 dòng, 33 câu đơn, 7 hội thoại; dev, English, một lần chạy

**Lời nói:** Bộ v2 có 96 event tổng hợp, 104 câu đơn (41 dev, 63 test) và 12 hội thoại. So sánh B0 và Texa dùng cùng `gpt-6-luna`, schema, định nghĩa metric, dữ liệu và code đã đóng băng; B0 sinh SQL trực tiếp còn Texa đi qua resolver, kiểm tra nguồn/phạm vi và compiler. Chấm điểm bằng cách thực thi SQL rồi so toàn bộ bảng với gold; lỗi và timeout vẫn tính sai. Memory ablation dùng 12 hội thoại holdout, clarification ablation dùng 20 scenario holdout. Ngoài ra nhóm chạy diagnostic riêng trên 17 dòng tổng hợp cho hai nguồn, với 33 câu đơn và 7 hội thoại; đây là dev tiếng Anh, một lần chạy, không phải holdout. Tất cả là dữ liệu tổng hợp, nên kết quả không đại diện cho warehouse production hay người dùng thật.

## Slide 11 — Kết quả chính: chưa đủ để nói Texa thắng (1:45)

Kết quả test holdout, `gpt-6-luna`, 63 câu, ba lần lặp:

| Cấu hình | Kết quả đúng | Tỷ lệ | Trung vị thời gian |
|---|---:|---:|---:|
| B0: LLM sinh SQL trực tiếp | 130/189 | 68,8% | 5,952 giây |
| Texa: pipeline đầy đủ | 143/189 | 75,7% | 9,554 giây |

Chênh lệch ghép theo scenario: **−14,5 đến +26,1 điểm %** (CI). B0 đạt 89,9% khi bỏ qua cột thừa trong chẩn đoán hậu nghiệm; metric chính yêu cầu toàn bảng khớp. Texa latency gồm cả insight; B0 chỉ sinh SQL.

**Lời nói:** Trên 63 câu test, qua ba lần chạy, Texa đúng 143 trong 189 lượt, tương đương 75,7%; B0 đúng 130, tương đương 68,8%. Nhìn vào điểm trung bình thì Texa cao hơn, nhưng khoảng tin cậy của chênh lệch chạy từ âm 14,5 đến dương 26,1 điểm phần trăm, nên dữ liệu hiện tại chưa đủ để kết luận Texa tốt hơn. B0 thường trả thêm cột; nếu bỏ qua lỗi đó trong phép chẩn đoán thì điểm tăng lên 89,9%, nhưng đó không phải thước đo chính vì bảng trả lời chưa khớp hoàn toàn. Texa cũng chậm hơn trong phép đo này; lưu ý Texa tạo thêm insight còn B0 chỉ sinh SQL.

## Slide 12 — Ablation: thành phần nào có ích? (1:30)

| So sánh | Kết quả | Diễn giải |
|---|---:|---|
| Memory: F / cửa sổ 6 lượt / không memory — scenario success | 63,9% / 66,7% / 19,4% | Chưa thấy F hơn M6; F hơn M0 |
| Clarification: F / bỏ hỏi lại — scenario success | 85,0% / 51,7% | Có lợi rõ, chủ yếu khi thiếu kỳ báo cáo |

**Lời nói:** Khi bỏ memory hoàn toàn, tỷ lệ hoàn thành scenario giảm xuống 19,4%; nhưng cấu hình đầy đủ chỉ đạt 63,9%, còn cửa sổ sáu lượt đạt 66,7%. Vì khoảng tin cậy của chênh lệch F–M6 còn chứa 0, chưa thể nói memory cấu trúc tốt hơn cửa sổ sáu lượt. Với clarification, cấu hình đầy đủ đạt 85%, so với 51,7% khi bỏ bước hỏi lại; cải thiện chủ yếu đến từ việc hỏi rõ kỳ báo cáo. Đây là bằng chứng bước đầu trên bộ test tổng hợp, không phải cam kết cho mọi hội thoại. Trong memory run có sự cố gateway ở bốn scenario, nên usage ghi nhận là cận dưới; điểm kết quả vẫn được giữ nguyên. Thời gian clarification chỉ tính xử lý máy và oracle, chưa tính thời gian người dùng thật suy nghĩ/chọn câu trả lời.

## Slide 13 — Demo, giới hạn và kết luận (1:15)

- Demo: hỏi, xem scope/định nghĩa, kiểm tra bảng và SQL, hỏi tiếp
- Benchmark synthetic; chưa chứng minh kết quả trên warehouse hoặc người dùng thật
- Cần sửa lỗi diễn giải/filter của Texa, tham chiếu xa và hỏi lại thừa; giảm latency
- Diagnostic dev hai nguồn: Texa 31/33, baseline 19/33 câu đơn; chưa phải holdout
- E2E dữ liệu thật: mẫu truy vấn khớp SQL gold; còn lỗi follow-up tiếng Việt và gợi ý ngoài scope

**Lời nói:** Demo theo một hành trình: PM hỏi doanh thu Cosmetics tháng 12/2019, xem breakdown theo danh mục, rồi thêm điều kiện bằng câu tiếp nối; sau đó hỏi revenue Olist để thấy nguồn phải được chọn rõ và tiền tệ vẫn là BRL. Ở diagnostic đa nguồn nhỏ, Texa đạt 31/33 câu đơn so với baseline 19/33, nhưng đây mới là 33 câu dev tiếng Anh chạy một lần, chưa thể khái quát. Trên benchmark holdout chính, khoảng tin cậy vẫn chưa đủ để kết luận Texa tốt hơn; Texa cũng chậm hơn và cần tiếp tục giảm lỗi diễn giải. Memory cấu trúc chưa thắng rõ cửa sổ sáu lượt, còn clarification cho thấy cải thiện trong bài test. Nhóm cũng đã chạy website và hỏi thật trên Cosmetics/Olist: các mẫu tổng, nhóm tháng, top danh mục và item purchases khớp SQL đối chiếu. Tuy nhiên hai cách nói tiếp nối tiếng Việt vẫn làm mất ngữ cảnh, và gợi ý trang đầu còn vượt scope; nhóm chưa kết luận sẵn sàng mở demo tự do cho cả lớp. Texa là trợ lý phân tích có phạm vi kiểm soát được, chưa phải hệ thống đúng tuyệt đối hay thay thế chuyên viên dữ liệu. Xin cảm ơn.


### Ghi chú cho người trình bày

Mạch kể rút từ slide mẫu: vấn đề → sản phẩm/phạm vi → dữ liệu → phương pháp → ví dụ → đánh giá → demo/giới hạn. Đã bỏ literature review. Bảng điểm chấm **kết quả thực thi**, không lấy QuerySpec khớp làm bằng chứng kết quả đúng.

Số liệu formal lấy từ report đóng băng tại `backend/eval/results/study-20261105/` (single, memory, clarification); bản report được lưu trong `data/benchmark/results/study-20261105/report.json`. Bốn scenario memory bị gateway incident được ghi tại `data/benchmark/results/study-20261105/provider-incident.json`. Diagnostic đa nguồn riêng: `data/benchmark/results/multisource-20261105/report.json`; 33 câu đơn, dev tiếng Anh, một lần chạy. Runner hội thoại thô báo Texa 7/7 và direct 4/7, nhưng tiêu chí slot/reference nội bộ không giống nhau giữa hai phương pháp nên không trình bày như so sánh công bằng. Không gộp diagnostic với kết quả holdout.

Bằng chứng E2E website với model thật, sau `run.sh`: `data/benchmark/results/live-e2e-20261105/report.json`. Hai phiên browser chạy đồng thời không thay thế kiểm thử tải cả lớp. Download CSV chưa xác minh do timeout của công cụ; không tính là đã đạt.
