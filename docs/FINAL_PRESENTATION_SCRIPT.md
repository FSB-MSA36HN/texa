# Kịch bản thuyết trình cuối — Texa

## Phân công người nói

| Người nói | Slide | Nội dung |
|---|---:|---|
| Người 1 | 1–4 | Giới thiệu, vấn đề, người dùng và phạm vi |
| Người 2 | 5–6 | Hai nguồn dữ liệu, metric và lớp semantic catalog |
| Người 3 | 7–12 | Kiến trúc, workflow, memory và trải nghiệm sản phẩm |
| Người 4 | 13–16 | Thiết kế đánh giá và kết quả chính |
| Người 5 | 17–21 | Ablation studies, giới hạn và kết luận |

> Các con số benchmark dùng trong script là kết quả research-v3: cùng `gpt-6-luna`, cùng fixture, hai lần chạy cho mỗi phiên bản. Bộ dữ liệu do nhóm xây dựng, còn template/family overlap và chưa human-review hoặc sealed, nên đây là kết quả exploratory.

---

## Người 1 — Giới thiệu và bài toán

### Slide 1 — Texa: hỏi dữ liệu thương mại điện tử bằng ngôn ngữ tự nhiên (0:40)

**Ý chính trên slide:** Trợ lý phân tích cho PM/PO và quản lý không chuyên SQL.

**Lời nói:**

“Texa là một trợ lý phân tích dữ liệu cho PM, PO và quản lý không chuyên SQL. Người dùng có thể hỏi bằng ngôn ngữ tự nhiên, xem kết quả dưới dạng bảng và xem cả câu SQL để đối chiếu. Texa hỗ trợ người dùng ra quyết định nhanh hơn trong phạm vi dữ liệu đã định nghĩa; hệ thống không thay thế chuyên viên dữ liệu và cũng không giả định rằng LLM luôn đúng.”

### Slide 2 — Một câu hỏi cần một căn cứ rõ ràng (0:55)

**Ý chính trên slide:** Câu trả lời cần đi kèm các thông tin để kiểm tra cách hệ thống hiểu câu hỏi.

**Lời nói:**

“Điểm khác biệt của Texa không nằm ở việc biến một câu hỏi thành SQL, vì LLM thông thường cũng có thể làm được điều đó. Điểm quan trọng là sau khi hỏi ‘doanh thu tháng trước’, người dùng có thể kiểm tra Texa đã hiểu câu hỏi theo metric nào, nguồn nào, kỳ nào và filter nào. Những thông tin này được giữ trong QuerySpec và semantic catalog, rồi mới dùng để tạo SQL. Như vậy người dùng không chỉ nhận một con số, mà còn biết con số đó được tính dựa trên căn cứ nào.”

### Slide 3 — Phạm vi thực hiện (0:55)

**Ý chính trên slide:** Bốn giới hạn giúp hệ thống kiểm soát được chất lượng.

**Lời nói:**

“Để kiểm soát chất lượng, nhóm chốt bốn điều kiện. Người dùng mục tiêu là PM, PO và quản lý e-commerce. Bài toán chỉ làm trên event e-commerce và PostgreSQL, mỗi truy vấn dùng một nguồn. Semantic catalog có tám metric gốc đã định nghĩa; ngoài ra catalog còn chứa dimensions, event roles và mapping; nested chỉ xử lý scalar đã khai báo, tối đa hai key. Scope được giữ nhỏ để mỗi câu trả lời có thể kiểm tra và giải thích được.”

### Slide 4 — Tám metric gốc, nhiều cách kết hợp (1:05)

**Ý chính trên slide:** Tám metric gốc được kết hợp với thời gian, filter và breakdown để tạo nhiều truy vấn hợp lệ.

**Lời nói:**

“Tám metric trên slide là tám phép đo gốc được định nghĩa trong semantic catalog, không phải toàn bộ số loại câu hỏi mà Texa trả lời. Từ mỗi metric, người dùng có thể kết hợp thời gian, filter và breakdown để tạo ra nhiều truy vấn và insight khác nhau trong phạm vi cho phép. Catalog còn quản lý dimensions, event roles và mapping. Một chi tiết cần nhớ là purchases đếm event mua item, không mặc định là số đơn hàng; còn buyer conversion của Olist dựa trên observed users, không phải toàn bộ visitors.”

**Chuyển ý:** “Tiếp theo, bạn [Người 2] sẽ nói rõ dữ liệu và semantic catalog mà Texa sử dụng.”

---

## Người 2 — Dữ liệu và lớp ngữ nghĩa

### Slide 5 — Vì sao chọn Cosmetics và Olist? (0:55)

**Ý chính trên slide:** Hai nguồn có hành vi và độ bao phủ khác nhau.

**Lời nói:**

“Nhóm chọn cả Cosmetics và Olist vì hai nguồn cùng thuộc e-commerce nhưng bổ sung cho nhau về góc nhìn dữ liệu. Cosmetics cho phép kiểm tra hành vi trước mua, như xem sản phẩm, thêm vào giỏ và mua hàng. Olist cho phép kiểm tra giao dịch và vòng đời đơn, như item, order và trạng thái xử lý. Nhờ vậy, nhóm đánh giá được semantic layer trên hai kiểu dữ liệu khác nhau, thay vì chỉ kiểm tra Texa trên một schema.”

### Slide 6 — ELT: từ dữ liệu nguồn đến semantic layer (0:55)

**Ý chính trên slide:** Extract → Load → Transform → Semantic layer.

**Lời nói:**

“Slide này mô tả quy trình ELT của Texa. Đầu tiên, hệ thống lấy dữ liệu gốc từ Cosmetics và Olist. Tiếp theo, dữ liệu được nạp vào PostgreSQL để giữ bản ghi theo từng nguồn. Sau đó, lớp transform chuẩn hóa kiểu dữ liệu, ngày, field và event role thành event rows. Cuối cùng, semantic catalog gắn định nghĩa metric, mapping và coverage. Kết quả là một lớp event thống nhất để Texa xử lý, nhưng vẫn giữ được ngữ nghĩa riêng của từng nguồn.”

**Chuyển ý:** “Phần tiếp theo sẽ trình bày cách các thành phần đó phối hợp thành workflow của Texa.”

---

## Người 3 — Kiến trúc và workflow sản phẩm

### Slide 7 — Kiến trúc đã triển khai (1:15)

**Ý chính trên slide:** Mỗi bước chỉ rõ phần LLM đề xuất và phần code kiểm tra, thực thi.

**Lời nói:**

“Đây là kiến trúc triển khai đầy đủ của Texa. Đầu tiên, hệ thống nhận câu hỏi mới cùng memory có cấu trúc, gồm các slot và kết quả đã xác nhận. Nếu phù hợp, retrieval lấy các ví dụ đã xác minh và các mục catalog liên quan để đưa vào ngữ cảnh. Tiếp theo, LLM gọi để đề xuất candidate về intent, metric, nguồn và các điều kiện; consistency có thể gọi thêm các mẫu song song để chọn cách hiểu ổn định hơn. Phần code sau đó bind candidate vào QuerySpec, kiểm tra metric, source, thời gian, filter, breakdown và coverage; nếu thiếu hoặc mơ hồ thì hỏi lại. Compiler tạo SQL tham số hóa, còn sqlglot AST và sandbox read-only kiểm tra khả năng thực thi và tự sửa trong giới hạn. Cuối cùng PostgreSQL chạy truy vấn chỉ đọc, server tính facts và hiển thị SQL; LLM chỉ diễn giải các facts đã kiểm chứng thành nhận xét cho người dùng.”

### Slide 8 — Một câu hỏi đi qua hệ thống (1:00)

**Ý chính trên slide:** Ví dụ cụ thể từ câu hỏi đến bảng kết quả.

**Lời nói:**

“Ở slide này, ta nhìn một câu hỏi cụ thể thay vì chỉ nhìn sơ đồ. Texa xác định người dùng đang hỏi metric nào, trong khoảng thời gian nào và trên nguồn nào. Các giá trị như event role hoặc trạng thái mua hàng được lấy từ catalog, không tự dịch theo cảm tính. Cuối cùng hệ thống trả về bảng kết quả, các facts chính và câu SQL tương ứng để người dùng có thể xem lại.”

### Slide 9 — Kiểm tra trước và sau truy vấn (0:55)

**Ý chính trên slide:** Kiểm tra semantic, schema, AST và kết quả.

**Lời nói:**

“Texa kiểm tra ở cả trước và sau khi chạy SQL. Trước khi chạy, QuerySpec phải hợp lệ với catalog, nguồn và schema hiện tại. Sau khi model sinh SQL, AST validator kiểm tra cấu trúc truy vấn, sandbox kiểm tra khả năng thực thi và lớp kết quả kiểm tra các điều kiện business contract. Nếu thiếu dữ liệu thì hệ thống không biến nó thành số 0. Nếu nguồn không có field cần thiết, Texa phải nói rõ là không hỗ trợ.”

### Slide 10 — Structured memory cho hỏi tiếp (1:00)

**Ý chính trên slide:** Memory lưu QuerySpec và result reference có cấu trúc.

**Lời nói:**

“Memory của Texa không chỉ lấy sáu lượt chat gần nhất. Sau mỗi truy vấn thành công, hệ thống lưu các slot của QuerySpec và mã tham chiếu kết quả. Khi người dùng nói ‘đổi sang desktop’ hoặc ‘giữ nguyên các điều kiện khác’, server chỉ cập nhật đúng slot được nêu, giữ các slot còn lại và kiểm tra lại trước khi chạy. Nếu câu hỏi không rõ đang tham chiếu kết quả nào, Texa phải hỏi lại thay vì tự đoán.”

### Slide 11 — Khi catalog thay đổi, TEXA xử lý thế nào? (0:55)

**Ý chính trên slide:** Versioning và kiểm tra tương thích.

**Lời nói:**

“Semantic catalog cũng có version. Khi catalog hoặc dataset snapshot thay đổi, QuerySpec cũ không được tự động diễn giải lại theo nghĩa mới. Texa kiểm tra version và từ chối khi ngữ cảnh không còn tương thích. Cách làm này giúp tránh việc hệ thống âm thầm trả một con số khác chỉ vì định nghĩa metric đã thay đổi.”

### Slide 12 — Sản phẩm: xem và đối chứng (0:55)

**Ý chính trên slide:** Bảng, facts, SQL và phạm vi hiển thị.

**Lời nói:**

“Ở giao diện sản phẩm, người dùng nhìn thấy bảng kết quả và các facts giải thích con số. SQL và phạm vi nguồn, thời gian, metric được hiển thị để đối chứng. Mục tiêu của giao diện là để một người không chuyên SQL vẫn hiểu con số được tính từ đâu, đồng thời có đủ thông tin để trao đổi lại với đội dữ liệu khi cần.”

**Chuyển ý:** “Tiếp theo, [Người 4] sẽ trình bày cách nhóm đánh giá Texa và kết quả chính.”

---

## Người 4 — Đánh giá chính

### Slide 13 — Thiết lập đánh giá và lý do chọn benchmark (0:55)

**Ý chính trên slide:** Cùng model và dữ liệu; baseline chỉ nhận schema.

**Lời nói:**

“Để so sánh, các phiên bản dùng cùng model gpt-6-luna, cùng câu hỏi và cùng fixture. Baseline được thiết kế như LLM sinh SQL trực tiếp: nó chỉ nhận câu hỏi, schema PostgreSQL vật lý và nguồn được chọn trên giao diện. Baseline không nhận semantic catalog, định nghĩa nghiệp vụ, source-value mapping hay verified examples. Texa nhận thêm các thành phần semantic và workflow của sản phẩm. Vì vậy kết quả đo là so sánh giữa hai hệ thống với thông tin đầu vào khác nhau, không phải bảng xếp hạng giữa các model.”

### Slide 14 — Chấm kết quả, không chấm chuỗi SQL (0:50)

**Ý chính trên slide:** Business accuracy dựa trên bảng kết quả.

**Lời nói:**

“Metric chính không yêu cầu hai câu SQL phải giống từng ký tự. Một câu trả lời được tính là đúng khi bảng kết quả khớp với đáp án gold và thỏa business contract. Với hội thoại, nhóm chấm theo từng answer slot. Clarification được chấm thêm ở hai mặt: bảng cuối cùng có đúng không và hệ thống có hỏi lại đúng lúc không. Cách chấm này phản ánh kết quả mà người dùng thực sự nhìn thấy.”

### Slide 15 — Kết quả chính: câu hỏi đơn (1:00)

**Ý chính trên slide:** Texa 91,25%, baseline schema-only 22,50%.

**Lời nói:**

“Trên 200 câu test được chạy hai lần, baseline chỉ nhận schema đạt 22,50% business accuracy. Texa đạt 91,25%. Các biến thể Texa có retrieval hoặc consistency đạt từ 87,00% đến 90,25%. Khoảng cách lớn cho thấy semantic catalog và workflow có giá trị trong bộ candidate này. Tuy nhiên, vì baseline không có định nghĩa nghiệp vụ giống Texa, chúng ta không được nói rằng toàn bộ mức tăng chỉ đến từ một component riêng lẻ.”

### Slide 16 — Hội thoại, hỏi lại và ngoài phạm vi (1:00)

**Ý chính trên slide:** Mỗi loại tác vụ có metric riêng.

**Lời nói:**

“Với hội thoại, Texa đạt 94,81% trên 616 answer slots; retrieval-only đạt 96,10% trong suite này. Với clarification, bảng kết quả cuối của Texa đạt 100% trong bộ revision1 và hành động hỏi lại cũng đạt 100% ở phép đo chính trước đó. Ngoài scope, Texa đạt 95% action accuracy. Các con số này không được gộp thành một điểm overall, vì chúng đo các năng lực khác nhau.”

**Chuyển ý:** “Phần cuối sẽ đi sâu vào ablation studies, giới hạn của kết quả và kết luận của nhóm.”

---

## Người 5 — Ablation studies và kết luận

### Slide 17 — Ablation: thành phần nào giúp ích? (0:55)

**Ý chính trên slide:** Retrieval và consistency được bật/tắt riêng.

**Lời nói:**

“Ở ablation đầu tiên, nhóm giữ catalog và pipeline nền, sau đó bật hoặc tắt retrieval và consistency. Kết quả cho thấy Texa đạt 91,25% ở câu đơn, retrieval-only đạt 90,25%, còn consistency-only đạt 87,00%. Ở hội thoại, retrieval-only đạt 96,10%, cao hơn Texa đầy đủ 94,81%. Điều này cho thấy không có component nào cải thiện đồng đều mọi suite; cần đọc kết quả theo từng loại tác vụ.”

### Slide 18 — Ablation: memory và clarification (1:05)

**Ý chính trên slide:** Ablation mới, giữ retrieval và consistency bật.

**Lời nói:**

“Bảng này là một ablation khác. Retrieval và consistency được giữ bật; nhóm chỉ thay memory hoặc clarification. Structured memory đạt 84,58%, window-6 đạt 85,55% và without memory đạt 83,93% trên 616 answer slots. Chênh lệch memory còn nhỏ nên chưa đủ để kết luận window-6 hay structured memory tốt hơn một cách ổn định. Clarification có tác động rõ hơn: bật clarification đạt 86,67% so với 62,50% khi tắt; policy accuracy lần lượt là 75% và 50%. Đây vẫn là kết quả exploratory trên dữ liệu tổng hợp.”

### Slide 19 — Bộ đánh giá và giới hạn bằng chứng (0:55)

**Ý chính trên slide:** Quy mô benchmark và các giới hạn cần nói rõ.

**Lời nói:**

“Bộ research-v3 gồm 300 câu đơn, 60 clarification cases, 40 hội thoại và 40 câu ngoài phạm vi. Hai nguồn là Cosmetics Shop và Olist, với nested extension được kiểm soát trong fixture. Điểm giới hạn là test còn template overlap, nhãn đã được người xây biết trước và chưa có hai reviewer độc lập khóa holdout. Vì vậy đây là bằng chứng để kiểm tra hướng thiết kế trong scope hiện tại, chưa phải lời khẳng định về mọi doanh nghiệp.”

### Slide 20 — Kiểm thử thực tế và giới hạn (0:50)

**Ý chính trên slide:** Kết quả test phần mềm và browser cần được phân biệt với benchmark.

**Lời nói:**

“Các test backend và Playwright kiểm tra chức năng của sản phẩm; chúng không thay thế benchmark accuracy. Một số browser observation trên slide là kết quả lịch sử với cấu hình cũ, nên không dùng để khẳng định chất lượng research-v3 hiện tại. Trước khi demo cho nhiều người dùng đồng thời, nhóm vẫn cần chạy lại browser E2E trên Texa đầy đủ và kiểm tra tải.”

### Slide 21 — Kết luận (0:55)

**Ý chính trên slide:** Scope rõ, có bằng chứng ban đầu, còn bước kiểm chứng tiếp theo.

**Lời nói:**

“Texa hiện là một trợ lý phân tích event e-commerce trên PostgreSQL, dành cho PM, PO và quản lý không chuyên SQL. Trong scope đã chọn, Texa đạt 91,25% ở câu hỏi đơn so với 22,50% của baseline schema-only; các ablation cho thấy semantic workflow, retrieval và clarification đều có vai trò, nhưng hiệu quả thay đổi theo loại tác vụ. Bước tiếp theo là review gold độc lập, khóa một holdout mới, mở rộng test hội thoại và chạy lại browser E2E trước khi đưa ra kết luận rộng hơn. Cảm ơn cô và mọi người đã lắng nghe.”

---

## Ghi chú chung cho cả nhóm

- Nói “business accuracy” là **tỷ lệ bảng kết quả khớp đáp án chuẩn**, không phải tỷ lệ chuỗi SQL giống nhau.
- Baseline và Texa dùng cùng model, nhưng baseline chỉ nhận schema; Texa có semantic catalog và workflow. Vì vậy đây là so sánh hệ thống với thông tin đầu vào khác nhau.
- Không nói “Texa đúng trong mọi trường hợp” hoặc “đã chứng minh tổng quát cho mọi database”. Scope chỉ là event e-commerce, PostgreSQL, hai nguồn Cosmetics/Olist.
- Hai nguồn và nested extension là dữ liệu synthetic. Các con số benchmark là exploratory, chưa phải holdout độc lập.
- Các slide 18–19 là hai nhóm ablation khác nhau: slide 18 kiểm tra retrieval/consistency; slide 19 kiểm tra memory/clarification.
