# Kịch bản thuyết trình cuối — Texa

## Phân công người nói

| Người nói | Slide | Nội dung |
|---|---:|---|
| Hoà | 1–4 | Giới thiệu, vấn đề, người dùng và phạm vi |
| Dương | 5–6 | Hai nguồn dữ liệu, metric và lớp semantic catalog |
| Hải | 7–11 | Kiến trúc, workflow, memory và trải nghiệm sản phẩm |
| Hiệp | 12–15 | Thiết kế đánh giá và kết quả chính |
| Đức | 16–18 | Ablation studies, giới hạn và kết luận |

> Các con số benchmark dùng trong script là kết quả research-v3: cùng `gpt-6-luna`, cùng snapshot dữ liệu cố định và hai lần chạy cho mỗi phiên bản. Bộ dữ liệu do nhóm xây dựng; vì vẫn còn các câu cùng dạng và chưa có holdout độc lập, đây là kết quả thăm dò. Sau buổi trình bày, nhóm đã bổ sung bộ test v4 (đáp án tính độc lập từ CSV thật) và thang baseline; các con số của hai phần này **chưa được đo bằng model thật** nên chưa có trong kịch bản. Các chỗ đã sửa theo góp ý nằm ở slide 6, 12 và 13; bản ghi chi tiết cho cô là file Word `docs/TEXA_phan_hoi_gop_y.docx`.

---

## Hoà — Giới thiệu và bài toán

### Slide 1 — Texa: hỏi dữ liệu thương mại điện tử bằng ngôn ngữ tự nhiên (0:40)

**Ý chính trên slide:** Trợ lý phân tích cho PM/PO và quản lý không chuyên SQL.

**Lời nói:**

“Texa là một trợ lý phân tích dữ liệu cho PM, PO và quản lý không chuyên SQL. Người dùng có thể hỏi bằng ngôn ngữ tự nhiên, xem kết quả dưới dạng bảng và xem cả câu SQL để đối chiếu. Texa hỗ trợ người dùng ra quyết định nhanh hơn trong phạm vi dữ liệu đã định nghĩa; hệ thống không thay thế chuyên viên dữ liệu và cũng không giả định rằng LLM luôn đúng.”

### Slide 2 — Một câu hỏi cần một căn cứ rõ ràng (0:55)

**Ý chính trên slide:** Câu trả lời cần đi kèm các thông tin để kiểm tra cách hệ thống hiểu câu hỏi.

**Lời nói:**

“Điểm khác biệt của Texa không nằm ở việc biến một câu hỏi thành SQL, vì LLM thông thường cũng có thể làm được điều đó. Điểm quan trọng là sau khi hỏi ‘doanh thu tháng trước’, người dùng có thể kiểm tra Texa đã hiểu câu hỏi theo chỉ số nào, nguồn nào, khoảng thời gian nào và điều kiện lọc nào. Những thông tin này được giữ trong QuerySpec và semantic catalog, rồi mới dùng để tạo SQL. Như vậy người dùng không chỉ nhận một con số, mà còn biết con số đó được tính dựa trên căn cứ nào.”

### Slide 3 — Phạm vi thực hiện (0:55)

**Ý chính trên slide:** Bốn giới hạn giúp hệ thống kiểm soát được chất lượng.

**Lời nói:**

“Để kiểm soát chất lượng, nhóm chốt bốn điều kiện. Người dùng mục tiêu là PM, PO và quản lý e-commerce. Bài toán chỉ làm trên event e-commerce và PostgreSQL, mỗi truy vấn dùng một nguồn. Semantic catalog có tám metric gốc đã định nghĩa; ngoài ra catalog còn chứa dimensions, event roles và mapping; nested chỉ xử lý scalar đã khai báo, tối đa hai key. Scope được giữ nhỏ để mỗi câu trả lời có thể kiểm tra và giải thích được.”

### Slide 4 — Tám metric gốc, nhiều cách kết hợp (1:05)

**Ý chính trên slide:** Tám metric gốc được kết hợp với thời gian, filter và breakdown để tạo nhiều truy vấn hợp lệ.

**Lời nói:**

“Tám metric trên slide là tám phép đo gốc được định nghĩa trong semantic catalog, không phải toàn bộ số loại câu hỏi mà Texa trả lời. Từ mỗi metric, người dùng có thể kết hợp thời gian, filter và breakdown để tạo ra nhiều truy vấn và nhận định khác nhau trong phạm vi cho phép. Catalog còn quản lý chiều phân tích, vai trò sự kiện và mapping giữa các nguồn. Một chi tiết cần nhớ là purchases đếm event mua item, không mặc định là số đơn hàng; còn buyer conversion của Olist dựa trên số người dùng quan sát được, không phải toàn bộ người truy cập.”

**Chuyển ý:** “Phần đầu đã giới thiệu bài toán và phạm vi. Tiếp theo, Dương sẽ trình bày hai nguồn dữ liệu và cách nhóm đưa dữ liệu về semantic layer.”

---

## Dương — Dữ liệu và lớp ngữ nghĩa

### Slide 5 — Vì sao chọn Cosmetics và Olist? (0:55)

**Ý chính trên slide:** Hai nguồn có hành vi và độ bao phủ khác nhau.

**Lời nói:**

“Nhóm chọn cả Cosmetics và Olist vì hai nguồn cùng thuộc e-commerce nhưng bổ sung cho nhau về góc nhìn dữ liệu. Cosmetics cho phép kiểm tra hành vi trước mua, như xem sản phẩm, thêm vào giỏ và mua hàng. Olist cho phép kiểm tra giao dịch và vòng đời đơn, như item, order và trạng thái xử lý. Nhờ vậy, nhóm đánh giá được semantic layer trên hai kiểu dữ liệu khác nhau, thay vì chỉ kiểm tra Texa trên một schema.”

### Slide 6 — ELT: từ dữ liệu nguồn đến semantic layer (0:55)

**Ý chính trên slide:** Extract → Load → Transform → Semantic layer.

**Lời nói:**

“Slide này mô tả quy trình ELT của Texa. Đầu tiên, hệ thống lấy dữ liệu gốc từ Cosmetics và Olist. Tiếp theo, dữ liệu được nạp vào PostgreSQL để giữ bản ghi theo từng nguồn. Sau đó, lớp transform chuẩn hóa kiểu dữ liệu, ngày, field và event role thành event rows. Cuối cùng, semantic catalog gắn định nghĩa metric, mapping và coverage. Kết quả là một lớp event thống nhất để Texa xử lý, nhưng vẫn giữ được ngữ nghĩa riêng của từng nguồn. Khó khăn lớn nhất ở bước này là hai nguồn khác bản chất: Cosmetics là luồng hành vi, Olist là vòng đời đơn hàng, nên user_id, giờ, purchase và revenue khác nghĩa; Olist không có session, giờ Brazil được lưu như UTC, và purchases cùng revenue của Olist gồm cả đơn sau đó bị hủy. Nhóm đã thêm ghi chú theo nguồn hiện cùng kết quả và hai quality check ở bước ETL.”

**Chuyển ý:** “Khi dữ liệu đã được chuẩn hóa, Hải sẽ trình bày kiến trúc và cách Texa xử lý một câu hỏi.”

---

## Hải — Kiến trúc và workflow sản phẩm

### Slide 7 — Kiến trúc đã triển khai (1:15)

**Ý chính trên slide:** Mỗi bước chỉ rõ phần LLM đề xuất và phần code kiểm tra, thực thi.

**Lời nói:**

“Đây là sơ đồ đầy đủ của Texa. Hệ thống bắt đầu từ câu hỏi mới và phần memory đã được xác nhận. Nếu có ví dụ phù hợp, retrieval đưa ví dụ và các mục catalog liên quan vào ngữ cảnh. Sau đó LLM đề xuất cách hiểu gồm metric, nguồn và điều kiện lọc; khi cần, consistency gọi thêm mẫu song song để kiểm tra cách hiểu đó. Phần code chuyển đề xuất thành QuerySpec, kiểm tra lại với catalog và hỏi người dùng nếu thiếu hoặc mơ hồ. Compiler tạo SQL có tham số; sqlglot và sandbox read-only kiểm tra cấu trúc và khả năng chạy. Cuối cùng PostgreSQL thực thi, server tính facts, còn LLM chỉ viết nhận xét dựa trên facts đã kiểm chứng.”

### Slide 8 — Ví dụ về một câu hỏi đi qua hệ thống (1:00)

**Ý chính trên slide:** Một câu hỏi cụ thể được chuyển thành QuerySpec rồi thành kết quả có thể đối chứng.

**Lời nói:**

“Sau khi xem kiến trúc tổng quát, ta đi qua một ví dụ cụ thể. Người dùng hỏi doanh thu theo danh mục của Cosmetics trong tháng 12 năm 2019. Texa lấy đúng nguồn, metric, breakdown và khoảng thời gian để tạo QuerySpec. Sau đó compiler tạo SQL tham số hóa và PostgreSQL chạy ở chế độ chỉ đọc. Kết quả trả về gồm bảng dữ liệu, các facts chính và SQL tương ứng, nên người dùng có thể kiểm tra cả câu hỏi đã được hiểu như thế nào lẫn con số được tính ra sao.”

### Slide 9 — Các lớp kiểm tra để bảo đảm câu trả lời có căn cứ (0:55)

**Ý chính trên slide:** Mỗi cổng kiểm tra chặn một loại sai khác nhau.

**Lời nói:**

“Slide này trả lời câu hỏi: vì sao Texa không chỉ cần sinh ra một câu SQL chạy được? Trước khi chạy, hệ thống kiểm tra QuerySpec, định nghĩa metric, source coverage và các field cần thiết; nếu thiếu hoặc mơ hồ thì hỏi lại, không tự đoán. Trong khi chạy, SQL được tham số hóa, chỉ đọc và bị giới hạn thời gian, số dòng. Sau khi chạy, server tính facts từ kết quả thật để đối chiếu; LLM chỉ được diễn giải các facts đó. Vì vậy slide 7 cho thấy pipeline gồm những thành phần nào, còn slide 9 cho thấy mỗi lớp bảo vệ chất lượng ở điểm nào.”

### Slide 10 — Structured memory cho hỏi tiếp (1:00)

**Ý chính trên slide:** Memory lưu QuerySpec và mã tham chiếu kết quả theo cấu trúc.

**Lời nói:**

“Memory của Texa không chỉ lấy sáu lượt chat gần nhất. Sau mỗi truy vấn thành công, hệ thống lưu các slot của QuerySpec và mã tham chiếu kết quả. Khi người dùng nói ‘đổi sang desktop’ hoặc ‘giữ nguyên các điều kiện khác’, server chỉ cập nhật đúng slot được nêu, giữ các slot còn lại và kiểm tra lại trước khi chạy. Nếu câu hỏi không rõ đang tham chiếu kết quả nào, Texa phải hỏi lại thay vì tự đoán.”

### Slide 11 — Catalog thay đổi: quy trình và tác động (0:55)

**Ý chính trên slide:** Thay đổi catalog theo quy trình rõ ràng và không làm đổi nghĩa các truy vấn cũ một cách âm thầm.

**Lời nói:**

“Khi cần đổi catalog, nhóm sửa metric, dimension hoặc mapping trong YAML; sau đó hệ thống validate cấu trúc, các liên kết và coverage với source trước khi publish thành một version mới. Câu hỏi mới sẽ dùng version mới. Nếu một truy vấn đang chạy, nó tiếp tục dùng version đã được đọc lúc bắt đầu, không đổi nghĩa giữa chừng. Nếu schema hoặc source thay đổi làm thiếu field, validation sẽ chặn truy vấn thay vì cố chạy. Với hội thoại hoặc QuerySpec cũ khác version, Texa không tự kế thừa theo định nghĩa mới mà yêu cầu người dùng hỏi lại. Như vậy thay đổi được kiểm soát và có thể truy vết.”

**Chuyển ý:** “Như vậy, catalog có version và mọi thay đổi đều được kiểm soát. Tiếp theo, Hiệp sẽ trình bày cách nhóm benchmark và đọc kết quả.”

---

## Hiệp — Đánh giá chính

### Slide 12 — Đánh giá: baseline, Texa và bộ benchmark (0:55)

**Ý chính trên slide:** Hai hệ thống dùng cùng model, câu hỏi, snapshot dữ liệu và cách chấm; khác nhau ở thông tin và workflow được phép dùng.

**Lời nói:**

“Baseline là LLM sinh SQL trực tiếp, dùng cùng gpt-6-luna nhưng chỉ nhận câu hỏi, schema PostgreSQL và nguồn được chọn; baseline không nhận semantic catalog, định nghĩa nghiệp vụ, ví dụ đã xác minh hay workflow QuerySpec. Texa đầy đủ dùng đúng model đó nhưng có thêm semantic catalog, memory, retrieval, consistency khi cần, QuerySpec, compiler và validation. Hai bên cùng chạy trên dữ liệu Cosmetics và Olist với điều kiện chạy cố định, gồm bốn nhóm. Thứ nhất, 300 câu đơn đo độ chính xác: 100 câu dev để phát triển, 200 câu test để đánh giá, chia theo ba mức basic, compositional và semantic. Thứ hai, 60 tình huống clarification gồm 30 câu mơ hồ và 30 câu rõ ràng đối chứng, để đo việc hỏi lại đúng lúc chứ không phải câu nào cũng hỏi. Thứ ba, 40 hội thoại dài 6 đến 12 lượt đo khả năng giữ và cập nhật ngữ cảnh. Thứ tư, 40 câu ngoài scope đo khả năng từ chối thay vì bịa ra câu trả lời. Mỗi cấu hình chạy hai lần; kết quả được so với bảng gold, không yêu cầu câu SQL phải giống nhau. Bộ test vẫn còn một số câu cùng dạng với dev và chưa có holdout độc lập, nên đây là kết quả thăm dò. Sau góp ý, nhóm nhận thấy baseline schema-only chủ yếu đo việc thiếu định nghĩa nghiệp vụ, nên bổ sung thang baseline: thêm ví dụ, thêm đúng định nghĩa Texa đang dùng, thêm một lần sửa SQL, rồi mới đến Texa; số liệu của thang này chưa được chạy. Nhóm cũng xây bộ test v4 trên dữ liệu thật với đáp án tính độc lập từ CSV.”

### Slide 13 — QUY TẮC ĐÁNH GIÁ (0:55)

**Ý chính trên slide:** Tách rõ cách xác định một kết quả đúng và các metric dùng để đo.

**Lời nói:**

“Thứ nhất là quy tắc: hai câu SQL không cần giống nhau; chỉ cần chạy trên cùng snapshot và trả về cùng bảng gold. Bảng phải khớp cột, dòng, NULL và duplicate; thứ tự dòng chỉ quan trọng khi câu hỏi yêu cầu. Tên cột (alias) không bắt buộc giống nhau nhưng số cột phải khớp. Sai số số học cho phép là 1e-6 (1x 10 mu -6), còn lỗi hoặc timeout vẫn tính là sai. Thứ hai là metric: câu hỏi đơn dùng tỷ lệ bảng đúng; clarification chấm cả bảng cuối và việc hệ thống có hỏi lại đúng lúc; hội thoại chấm từng lượt có đáp án, cùng với hành động và việc tham chiếu đúng kết quả trước. Thời gian, số lần gọi model và token là các chỉ số bổ sung. Về độ chính xác của đáp án chuẩn, bộ v4 tính đáp án độc lập từ CSV thật bằng DuckDB: 300 câu, 96 nhóm dạng câu, dev và test không trùng nhóm nào, và cả 300 câu SQL chuẩn đều khớp. Vì chưa có hai người review độc lập nên bộ test vẫn là thăm dò.”

### Slide 14 — Kết quả benchmark — câu hỏi đơn (0:55)

**Ý chính trên slide:** Semantic workflow tạo khác biệt lớn trên các câu hỏi đơn trong scope đã chọn.

**Lời nói:**

“Kết quả chính: baseline schema-only đúng 90 trên 400 lượt, tức 22,5%; Texa đúng 365 trên 400, tức 91,25%. Ba phiên bản ablation nằm giữa: 87,5% khi bỏ cả retrieval và consistency, 87% khi chỉ có consistency và 90,25% khi chỉ có retrieval. Khoảng cách lớn này gợi ý rằng định nghĩa nghiệp vụ, QuerySpec, compiler và validation đang giải quyết đúng điểm yếu của việc để LLM tự đoán từ schema. Retrieval có đóng góp tích cực, còn consistency chưa cho thấy hiệu quả ổn định ở mọi cấu hình. Cần lưu ý baseline này không có định nghĩa nghiệp vụ nên con số 22,5% chủ yếu đo kiến thức; phần này được làm rõ ở slide 12.”

### Slide 15 — Kết quả theo loại tác vụ (0:55)

**Ý chính trên slide:** Mỗi loại tác vụ cho thấy một khía cạnh khác nhau của hệ thống.

**Lời nói:**

“Hội thoại đo khả năng giữ và cập nhật ngữ cảnh; clarification đo khả năng nhận ra khi nào cần hỏi lại; ngoài scope đo khả năng từ chối hoặc hướng người dùng về phạm vi hỗ trợ. Về số liệu: hội thoại tăng từ 14,77% lên 94,81%, trong khi retrieval-only đạt 96,10%; hành động hỏi lại đúng tăng từ 67,5% lên 100%; xử lý ngoài phạm vi tăng từ 5% lên 95%. Texa tốt hơn rõ rệt ở việc hỏi lại và xử lý ngoài phạm vi, còn retrieval-only nổi bật ở hội thoại. Điều này cho thấy hiệu quả của component phụ thuộc vào loại tác vụ.”

**Chuyển ý:** “Sau khi xem kết quả chính, Đức sẽ trình bày các ablation và những nhận định nhóm rút ra.”

---

## Đức — Ablation studies và kết luận

### Slide 16 — Ablation — retrieval và consistency (0:50)

**Ý chính trên slide:** Kiểm tra riêng đóng góp của retrieval và consistency.

**Lời nói:**

“Ablation này giữ nguyên catalog và pipeline, chỉ thay retrieval và consistency. Insight chính là retrieval giúp ích rõ hơn trên bộ test này, trong khi consistency không cải thiện ổn định ở mọi loại tác vụ. Vì vậy không nên mặc định thêm mọi component sẽ luôn làm hệ thống tốt hơn; mỗi component cần được kích hoạt theo đúng tình huống và được kiểm chứng bằng benchmark riêng.”

### Slide 17 — Ablation — memory và clarification (0:55)

**Ý chính trên slide:** Memory và clarification giải quyết hai vấn đề khác nhau trong hội thoại.

**Lời nói:**

“Trong bộ test này, memory có ảnh hưởng nhỏ nên chưa đủ để khẳng định một cách lưu ngữ cảnh nào luôn tốt hơn. Clarification tạo khác biệt rõ hơn vì nó ngăn hệ thống tự đoán khi câu hỏi thiếu hoặc mơ hồ. Vì vậy Texa ưu tiên giữ trạng thái có cấu trúc và hỏi lại đúng lúc, thay vì chỉ kéo dài cửa sổ hội thoại.”

### Slide 18 — Kết luận (0:45)

**Ý chính trên slide:** Texa có giá trị khi semantic layer, compiler, memory và clarification phối hợp đúng phạm vi.

**Lời nói:**

“Qua kết quả đánh giá, nhóm rút ra ba nhận định. Thứ nhất, semantic layer và workflow kiểm soát giúp LLM trả lời có căn cứ hơn so với việc sinh SQL trực tiếp từ schema. Thứ hai, clarification có vai trò rõ ràng trong việc tránh đoán sai; memory có cấu trúc là nền tảng để xử lý câu hỏi nối tiếp. Thứ ba, retrieval và consistency không phải lúc nào cũng cùng tăng chất lượng, nên cần chọn theo tác vụ và đo bằng ablation. Bước tiếp theo là hai người review đáp án gold độc lập, chạy lại benchmark trên bộ v4 với thang baseline, rồi khóa holdout trước khi mở rộng scope. Cảm ơn cô và mọi người đã lắng nghe.”

---

## Ghi chú chung cho cả nhóm

- Nói “business accuracy” là **tỷ lệ bảng kết quả khớp đáp án chuẩn**, không phải tỷ lệ chuỗi SQL giống nhau.
- Baseline và Texa dùng cùng model, nhưng baseline chỉ nhận schema; Texa có semantic catalog và workflow. Vì vậy đây là so sánh hệ thống với thông tin đầu vào khác nhau.
- Không nói “Texa đúng trong mọi trường hợp” hoặc “đã chứng minh tổng quát cho mọi database”. Scope chỉ là event e-commerce, PostgreSQL, hai nguồn Cosmetics/Olist.
- Hai nguồn và nested extension là dữ liệu tổng hợp. Các con số benchmark là mang tính thăm dò, chưa phải holdout độc lập.
- Các slide 16–17 là hai nhóm ablation khác nhau: slide 16 kiểm tra retrieval/consistency; slide 17 kiểm tra memory/clarification.
- Khi nói về phần sửa theo góp ý (slide 6, 12, 13) chỉ nêu những gì đã kiểm chứng được: 300/300 SQL chuẩn khớp đáp án tính từ CSV, dev/test không trùng nhóm. Không nói baseline mới hay v4 “đã đo” khi chưa chạy với model thật, và không nói bộ test “đã được review” khi chưa có hai reviewer.
