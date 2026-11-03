# Kế hoạch bổ sung ablation study cho Texa

Ngày: 03/11/2026. Trạng thái: **chỉ lập kế hoạch, chưa triển khai các thay đổi dưới đây, chưa chạy model thật**.

## 1. Mục tiêu và cách giải thích

Ablation study trả lời: **từng thành phần của Texa có giúp ích không?**

Lấy Texa đầy đủ làm mốc. Mỗi lần chỉ thay hoặc bỏ một thành phần, giữ nguyên các thành phần khác; cho các phiên bản làm cùng câu hỏi trên cùng dữ liệu và cùng model. So kết quả đúng, thời gian và token. Không mặc định trước Texa đầy đủ phải thắng.

Phân biệt hai loại so sánh:

- **Baseline:** LLM sinh SQL trực tiếp so với Texa đầy đủ, nhằm đánh giá cả giải pháp.
- **Ablation:** Texa đầy đủ so với Texa bị thay/bỏ một phần, nhằm tìm đóng góp của phần đó.

Texa là hệ thống đề xuất quanh một LLM, không phải mô hình mới được huấn luyện.

## 2. Phạm vi giữ nguyên

- Một domain e-commerce, PostgreSQL, một nguồn cho mỗi truy vấn, tám metric trong `catalog/product_events.yaml`.
- Nested scalar được khai báo trước, tối đa hai cấp khóa; không mở rộng mảng hoặc chuẩn hóa mọi database.
- Giữ nguyên QuerySpec, compiler, kiểm tra kiểu/giá trị, giới hạn nguồn, kiểm tra snapshot và thực thi chỉ đọc.
- Chỉ bổ sung cấu hình cho thử nghiệm offline; không thay hành vi mặc định của sản phẩm.

## 3. Các phiên bản cần thử

| ID | Phiên bản | Chỉ thay đổi gì so với F? | Nhóm dữ liệu dùng để kết luận |
|---|---|---|---|
| F | Texa đầy đủ | Structured memory và hỏi lại được bật | Tất cả nhóm phù hợp |
| M6 | Texa nhớ 6 lượt | Thay chiến lược chọn ngữ cảnh bằng 6 lượt gần nhất | Hội thoại cần ngữ cảnh |
| M0 | Texa không memory | Không đưa nội dung, trạng thái hoặc kết quả lượt trước vào xử lý câu hiện tại | Hội thoại cần ngữ cảnh |
| C0 | Texa không chủ động hỏi lại về nghiệp vụ | Với phần nghiệp vụ còn thiếu/mơ hồ, suy đoán có kiểm soát thay vì hỏi người dùng | Tình huống cần làm rõ |
| B0 | LLM sinh SQL trực tiếp | Baseline toàn hệ thống, không phải ablation | Câu hỏi đơn đã đủ thông tin |

**Ưu tiên:** F–M6 trước; tiếp theo F–M0 và F–C0. Không đồng thời tắt memory và hỏi lại trong cùng biến thể ở vòng đầu.

### Memory: định nghĩa để tránh chấm thiên lệch

- M6 đã có công tắc `TEXA_MEMORY_MODE=window6`; F dùng `structured`.
- M6 vẫn có thể thấy QuerySpec và kết quả trong sáu lượt được render. Đây là **cửa sổ sáu lượt trong Texa**, không phải baseline chỉ có văn bản chat thuần.
- M0 phải loại bỏ cả ngữ cảnh đưa vào LLM lẫn các đường tái sử dụng kết quả/thừa kế slot ẩn. Không chỉ xóa một đoạn prompt.
- Cho phép lưu lịch sử để ghi log, nhưng không cho M0 đọc lại lịch sử để trả lời. Chỉ giữ trạng thái của câu đang chờ làm rõ để hoàn tất chính câu đó.
- Các ràng buộc an toàn vẫn áp dụng. Nếu không đủ thông tin để trả lời hợp lệ, ghi nhận không trả lời; không ép sinh SQL sai.
- Chấm chính theo kết quả và slot nghiệp vụ. Không bắt M6/M0 phải xuất `context.references` giống F: M6 hiện không ghi trường này theo cách của structured memory. Tham chiếu nội bộ chỉ là chẩn đoán riêng, không được làm M6 tự động trượt dù trả đúng.

### Hỏi lại: định nghĩa C0 cụ thể

Phạm vi C0 ban đầu chỉ gồm **thiếu kỳ báo cáo** và **mơ hồ về metric nghiệp vụ** mà catalog thực sự có nhiều lựa chọn hợp lệ. Không bỏ hỏi xác nhận tham chiếu lịch sử, không thay toàn bộ resolver.

- F hỏi đúng trường còn thiếu; một bộ mô phỏng người dùng cung cấp lựa chọn đã được định trước.
- C0 nhận cùng câu hỏi ban đầu, tự chọn một giá trị hợp lệ dựa trên thông tin hiện có. Không được đọc đáp án/ý định ẩn của người dùng.
- Đề xuất thêm một bước đoán dùng cùng LLM, chỉ khi resolver phát hiện các trường thuộc phạm vi trên. Giới hạn một lượt đoán, ghi lại lựa chọn, token và thời gian. Không đoán được thì không trả lời.
- Sau lựa chọn của C0, vẫn chạy kiểm tra QuerySpec và compiler bình thường. Không mặc định bỏ bộ lọc hay cưỡng ép mọi câu thiếu kỳ thành “toàn bộ dữ liệu”.
- Nếu có trường mơ hồ ngoài phạm vi thử nghiệm, xử lý như F và đánh dấu riêng; không âm thầm tắt các cơ chế khác.
- Đây là phép so sánh **hỏi để lấy thêm thông tin** với **tự suy đoán**, không phải hai bên đã có lượng thông tin người dùng bằng nhau. Phải báo cáo thêm số lượt tương tác.

### Chưa đưa vào thử nghiệm chính

- **Bỏ schema shortlisting:** `interpret.py` chỉ kích hoạt shortlist khi catalog vượt ngân sách context. Catalog nhỏ có thể không kích hoạt; khi đó ablation này không đo được tác dụng. Chỉ làm P1 nếu có dữ liệu/schema phù hợp và log xác nhận tính năng đã chạy.
- **Bỏ profiler hoặc validator:** đang gắn với kiểm tra trường nested và khả năng dữ liệu. Tắt trực tiếp có thể đổi phạm vi hỗ trợ hoặc bỏ ràng buộc, không cô lập được một cải tiến chất lượng.
- **Bỏ QuerySpec/compiler:** thay đổi cả cách sinh SQL. Trước mắt dùng B0 để so kiến trúc tổng thể; không gán toàn bộ chênh lệch B0–F cho riêng compiler.
- **Kết hợp nhiều thành phần bị tắt:** để sau nếu kết quả đơn lẻ cho thấy cần khảo sát tương tác. Ablation một thành phần chỉ đo đóng góp trong cấu hình còn lại, không chứng minh các đóng góp độc lập hay cộng được với nhau.

## 4. Dữ liệu đánh giá

### Giữ nguyên benchmark v2

- 96 event tổng hợp, 104 câu đơn: 41 dev và 63 test.
- 12 hội thoại, trong đó 30 lượt có SQL/đáp án kết quả.
- Dùng v2 làm hồi quy và thử nghiệm sơ bộ. Bộ hiện có ít trường hợp hỏi lại và hội thoại độc lập, chưa đủ làm bằng chứng mạnh cho mọi component.
- Test v2 đã được đọc khi phát triển dataset; không mô tả là tập test hoàn toàn chưa từng được xem. Các mẫu hội thoại cũng có giao nhau giữa dev/test.

### Bổ sung suite ablation riêng, có phiên bản và checksum

Đề xuất lưu tại `data/benchmark/ablation_v1/`, không sửa âm thầm dữ liệu/gold v2.

**Memory: tối thiểu 24 hội thoại độc lập**, 12 dev và 12 test, cân bằng sáu nhóm:

1. Hỏi tiếp trong phạm vi ngắn.
2. Sửa thời gian/bộ lọc và thay metric.
3. Câu xã giao/nhiễu không được làm mất chủ đề.
4. Chuyển chủ đề rồi quay lại kết quả cụ thể.
5. Tham chiếu có khoảng cách hơn sáu lượt; có hội thoại dài 8, 10 và 12 lượt.
6. Tham chiếu thực sự mơ hồ cần hỏi lại; câu hỏi độc lập mới không được thừa kế bộ lọc cũ.

Ghi `referenced_turn`, khoảng cách phụ thuộc, slot kỳ vọng, gold SQL và bảng kết quả cho mỗi lượt có thể trả lời. Phân nhóm theo hiện tượng có thể giao nhau; phải ghi rõ cách đếm.

**Clarification: tối thiểu 16 tình huống mơ hồ**, 8 dev và 8 test:

- Thiếu kỳ báo cáo, với lựa chọn người dùng khác nhau giữa các tình huống.
- Cách đếm mơ hồ, chỉ dùng các lựa chọn có thật trong catalog; xác nhận resolver hiện hỗ trợ trước khi viết gold.
- Có cặp câu đã ghi đủ thông tin làm đối chứng để đo hỏi lại không cần thiết. Các câu cùng mẫu/cặp luôn ở cùng split.
- Mỗi tình huống khai báo: câu ban đầu, trường cần hỏi, ý định người dùng, câu trả lời mô phỏng theo lựa chọn hợp lệ và đáp án cuối.
- Chọn dữ liệu để các cách hiểu khác nhau cho kết quả khác nhau. Nếu hai lựa chọn tình cờ cùng kết quả, sửa fixture hoặc thay câu trước khi đóng băng.

Đây là mức tối thiểu phục vụ đồ án, không phải bảo đảm đủ sức mạnh thống kê. Cần người ngoài nhóm tạo câu hỏi hoặc PM/PO duyệt nghĩa nghiệp vụ. Không gán “đã được người dùng xác nhận” cho kiểm tra bằng agent.

## 5. Cách chạy công bằng

1. Chốt một model/version/provider, thiết lập sinh được API hỗ trợ, giới hạn context/output, timeout và retry. Nếu provider không cho khóa tham số/seed, ghi rõ. Không giả định có thể tái lập tuyệt đối.
2. Khóa catalog, snapshot DB, prompt và cấu hình; lưu commit SHA cùng checksum của **đúng các file input thực dùng**, kể cả đường dẫn override.
3. Dùng dev để sửa implementation, prompt và bộ chấm. Đóng băng suite/cấu hình trước vòng test; không tinh chỉnh tiếp theo lỗi test rồi báo đó là kết quả giữ lại ban đầu.
4. Mỗi scenario tạo hội thoại mới. Mỗi biến thể chạy trong process riêng để không rò environment hoặc trạng thái. Không truyền actual output của biến thể khác.
5. Chạy ba lần mỗi cấu hình trong thử nghiệm chính; xen kẽ thứ tự F/M6/M0/C0 giữa các lượt chạy để giảm ảnh hưởng thời điểm/cache. Có thể tăng năm lần nếu ngân sách cho phép và quy tắc được chốt trước.
6. Lặp chạy không tạo thêm câu hỏi độc lập. Không coi 12 hội thoại chạy ba lần là 36 hội thoại độc lập.
7. Đếm cả model call, lượt hỏi lại và chi phí của bước viết câu trả lời cuối. Tách thời gian máy xử lý khỏi thời gian chờ người dùng; bộ mô phỏng trả lời không đại diện độ trễ của người thật.
8. Không lọc bỏ câu lỗi/timeout/không trả lời khỏi mẫu số. Ghi nguyên nhân riêng. Lỗi hạ tầng diện rộng phải có quy tắc chạy lại theo block, không chỉ chạy lại các câu Texa sai.

### Giao thức người dùng mô phỏng cho C0/F

- Bộ mô phỏng chỉ biết lựa chọn nghiệp vụ cần cung cấp; không gửi gold SQL, kết quả hay toàn bộ gold QuerySpec cho model.
- Với F, chỉ cung cấp lựa chọn khi hệ thống thực sự hỏi đúng trường; không tự bổ sung thông tin để cứu câu trả lời.
- C0 không hỏi thì không được nhận thông tin làm rõ. Chấm câu trả lời cuối/duy nhất của nó với ý định người dùng đã khóa trước.
- Runner hiện dùng chuỗi `clarify` → `clarification_answer` cố định. Cần thêm kịch bản rẽ nhánh theo hành động thực tế; không ép C0 thực hiện một lượt hỏi lại mà biến thể đã bị tắt.
- Giới hạn cùng số vòng làm rõ tối đa được chốt trên dev; hết giới hạn tính thất bại. Cần test trường hợp hỏi sai trường, hỏi thừa và thiếu đáp án oracle, không dừng cả batch.

## 6. Chấm điểm và báo cáo

| Thước đo | Định nghĩa / cách dùng |
|---|---|
| Execution Accuracy | Số yêu cầu trả kết quả SQL đúng / tổng yêu cầu có đáp án. Giữ kiểm tra cột, NULL, hàng, sai số số học và thứ tự top-k như bộ chấm hiện có. |
| Đúng kết quả cuối sau làm rõ | Với F–C0, mỗi tình huống chỉ tính một lần; kết quả cuối phải khớp ý định người dùng đã khóa. Không đếm thêm lượt oracle thành một câu độc lập. |
| Thành công hội thoại | Tất cả hành vi bắt buộc và các câu trả lời trong scenario đều đúng. Báo cáo song song tỷ lệ từng lượt để thấy lỗi nằm đâu. |
| Đúng trạng thái | Metric, kỳ báo cáo, bộ lọc và breakdown khớp gold; chỉ số chẩn đoán cho các biến thể Texa. Chuẩn hóa time range trước khi so. |
| Đúng hỏi lại | Trường cần làm rõ và hỏi thừa/hỏi thiếu. Chấm trên cả câu mơ hồ và câu đầy đủ thông tin. Không dùng việc C0 không hỏi làm bằng chứng duy nhất rằng F tốt hơn. |
| Hiệu năng / tương tác | p50/p95 thời gian, input/output token, số model call, số lượt hỏi lại; tiền chỉ tính khi có bảng giá/version cụ thể. |

Phải tách kết quả theo nhóm câu. Không lấy trung bình chung nhiều câu không cần memory rồi kết luận memory không hữu ích. Không gọi SQL chạy được là đúng nghiệp vụ.

So sánh từng ablation với F trên cùng scenario và repeat. Báo cáo số đúng/tổng số, trung bình và độ dao động giữa các repeat; chênh lệch bằng **điểm phần trăm**.

Khoảng tin cậy 95% dùng paired cluster bootstrap: lấy trọn hội thoại/tình huống và toàn bộ repeat tương ứng, không lấy từng lượt chat hoặc từng lần chạy như mẫu độc lập. Với các câu đơn sinh từ cùng họ mẫu, giữ cụm họ mẫu. Giữ cặp câu đối chứng cùng cụm. Bộ `paired_delta_bootstrap` hiện tại dùng lại được cho một repeat; cần bổ sung tổng hợp nhiều repeat, không ghép JSONL thành ID trùng hoặc giả tăng cỡ mẫu.

Nhiều phép so sánh và mẫu nhỏ: chốt F–M6 là so sánh chính; các so sánh khác là bổ sung. Không dựa vào một p-value hoặc một lần chạy tốt nhất. Khoảng tin cậy rộng/bao gồm 0 thì báo chưa đủ bằng chứng. Dataset synthetic không chứng minh hiệu quả với mọi công ty.

Mẫu bảng báo cáo, **để trống đến khi có kết quả thật**:

| Nhóm | Phiên bản | Đúng / tổng | Accuracy trung bình | Chênh lệch F–biến thể (đpt), CI95% | Token | p50/p95 | Lượt hỏi lại |
|---|---|---|---|---|---|---|---|
| Memory | F / M6 / M0 | Chưa chạy | — | — | — | — | — |
| Clarification | F / C0 | Chưa chạy | — | — | — | — | — |
| Câu đơn v2 | F / B0 | Chưa chạy | — | — | — | — | — |

Nếu F tốt hơn nhưng tốn thêm thời gian/token, kết luận theo đánh đổi. Nếu không tốt hơn, báo trung thực và xem component có thực sự được kích hoạt hoặc dataset có kiểm tra đúng hiện tượng không.

## 7. Các bước implement sau khi chốt kế hoạch

Làm trực tiếp trên `main` trong `Final`, không tạo branch mới. Mỗi mốc lớn kiểm tra rồi commit; push theo yêu cầu Git đã có của người dùng. **Không thực hiện các bước này trong lượt chỉ lập kế hoạch.**

### Bước 1 — Chốt giao thức và config thử nghiệm

- Thêm cấu hình ablation có tên rõ ràng, mặc định giữ F, từ chối tổ hợp không hợp lệ.
- Phân biệt baseline toàn hệ thống với ablation. Khóa phạm vi F/M6/M0/C0 và điều kiện component được tính là đã kích hoạt.
- Dự kiến file: `backend/eval/ablation.py` hoặc module cấu hình tương đương; tài liệu hướng dẫn chạy.

### Bước 2 — Bổ sung và kiểm chứng suite

- Tạo `data/benchmark/ablation_v1/` gồm manifest, kịch bản, gold/reference, provenance và lock. Dùng lại fixture v2 nếu đủ phân biệt ý định; nếu cần sửa dữ liệu thì version fixture riêng và giữ v2.
- Mở rộng `backend/eval/validate_dataset.py`: tag hiện tượng, cặp câu, oracle, tham chiếu, split và kết quả literal.
- Chạy gold SQL trên DB `texa_benchmark` bằng read-only role, so với tính toán tham chiếu độc lập; kiểm tra human-review status.
- Đầu ra: suite tái lập được, từng kịch bản có nghĩa rõ; không tăng số lượng bằng các câu chỉ đổi cách diễn đạt.

### Bước 3 — Bổ sung các biến thể trong Texa

- `backend/texa/answer.py`, `memory.py`: thêm M0, giữ F/M6; kiểm tra các đường tái sử dụng kết quả không vượt ranh giới biến thể.
- `backend/texa/clarify.py`, `answer.py` và prompt hỗ trợ: thêm C0 đoán có giới hạn tại ranh giới resolver, chỉ với trường được cho phép.
- Giữ validation/compiler và hành vi sản phẩm mặc định; log component đang bật và thực tế đã chạy.
- Test có model giả để chứng minh chỉ thành phần mục tiêu thay đổi, không chỉ kiểm tra giá trị của công tắc.

### Bước 4 — Sửa runner và bộ chấm

- `backend/eval/run_benchmark.py`: chọn biến thể, scenario rẽ nhánh, conversation/process độc lập, reset environment, trace đầu vào thực dùng.
- Chấm F/M6/M0 theo đầu ra chung, không bắt buộc metadata tham chiếu đặc thù F. Sửa Precision/Recall hỏi lại để tính cả các câu không cần hỏi và xử lý trường hợp không có mẫu phù hợp bằng N/A.
- `backend/eval/benchmark.py` hoặc module tổng hợp: thêm kết quả cuối của tình huống tương tác, tổng hợp repeat, khoảng tin cậy theo cụm và từng nhóm.
- JSONL/summary có variant, model/version, effective generation config, prompt/catalog/dataset hashes, commit, repeat, scope, số call và trạng thái component.

### Bước 5 — Kiểm thử offline và pilot trên dev

- Unit/scripted tests: memory trống, cửa sổ đúng sáu lượt, không rò gold, oracle rẽ nhánh, hỏi thừa/sai, lỗi model, SQL lỗi và mẫu số không thay đổi.
- Integration trên PostgreSQL riêng: slot/filter được giữ đúng, nested NULL/zero/top-k không đổi, không tắt validator, không rò conversation giữa cấu hình.
- Chạy lại hồi quy liên quan của backend. Không cần sửa UI cho nghiên cứu offline.
- Khi bắt đầu vòng thực nghiệm được triển khai: chọn model/ngân sách cụ thể, chạy pilot dev để phát hiện lỗi giao thức và ước tính chi phí trước vòng test; không làm model call trong giai đoạn lập kế hoạch này.

### Bước 6 — Khóa cấu hình, chạy test và viết báo cáo

- Lưu cấu hình đã khóa; chạy ba repeat theo thứ tự xen kẽ, lưu log riêng mỗi lần.
- Sinh bảng F–M6, F–M0, F–C0; bảng B0–F đứng riêng. Kiểm tra lỗi tiêu biểu và dấu vết component.
- Viết `docs/ABLATION_STUDY_RESULTS.md` với số thực, CI, độ dao động, đánh đổi chi phí và giới hạn; cập nhật README đánh giá.
- Hoàn tất khi người khác có thể chạy lại từ lệnh/cấu hình và lấy cùng bộ dữ liệu, không khi đạt một mức Accuracy chọn trước.

## 8. Tiêu chí nghiệm thu

- Có định nghĩa chính xác cho mỗi ablation, mỗi lần chỉ thay một component/chiến lược; có trace chứng minh nó được kích hoạt.
- Bộ dữ liệu đủ nhóm đã chốt, có gold/reference kiểm chứng và phân tách dev/test theo cụm kịch bản.
- Không rò gold/ý định ẩn vào model; không chấm biến thể kém chỉ vì thiếu metadata riêng của F.
- Sai/không trả lời đều có mặt trong mẫu số; báo cáo rõ số tình huống, số lượt và số repeat.
- Kiểm thử chứng minh cấu hình mặc định F và các ràng buộc dữ liệu/thực thi vẫn giữ nguyên.
- Có số liệu đúng, hiệu năng, tương tác và độ bất định. Không đưa ra kết luận thắng/thua khi chưa có thực nghiệm thật.

## 9. Căn cứ code hiện tại

- `backend/texa/answer.py`: chọn context, công tắc `TEXA_MEMORY_MODE`, reference form và tiếp tục sau clarification.
- `backend/texa/interpret.py`: render catalog/history; shortlist chỉ khi vượt context budget.
- `backend/texa/clarify.py`: metric/time/filter resolution và tạo form/spec.
- `backend/texa/profiler.py`: metadata bounded nested, không phải một model linker tách riêng.
- `backend/eval/run_benchmark.py`: baseline, Texa rollout, oracle cố định, gold validation, so sánh kết quả.
- `backend/eval/benchmark.py`: so kết quả SQL, chấm trạng thái và bootstrap theo cụm.
- `data/benchmark/v2/README.md`, `manifest.yaml`: phạm vi và giới hạn dataset hiện tại.
