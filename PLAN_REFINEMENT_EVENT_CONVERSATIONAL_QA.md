# Kế hoạch thu hẹp và cải thiện TEXA

Ngày: 01/11/2026. Trạng thái: **đề xuất để review; chưa triển khai sửa code**.

Toàn bộ phạm vi là `/Users/thanhhigk/Study/NLP/Final`. Không đọc, sử dụng hoặc thay đổi các dự án DIego, Text2SQL, Text2Analytic hay hệ thống Inwave. Một số tài liệu cũ trong repository có nhắc các tên này; đó không phải nguồn phụ thuộc cho kế hoạch.

## 1. Kết luận đề xuất

**Định vị:** trợ lý hỏi đáp dữ liệu hội thoại cho PM/PO của sản phẩm thương mại điện tử, dùng một bộ event đã được chuẩn bị và một tập định nghĩa metric được duyệt. Người dùng hỏi bằng ngôn ngữ tự nhiên, nhận số liệu kèm cách tính, phạm vi thời gian và các giả định.

**Bài toán nghiên cứu:** xác định metric, tham chiếu và trạng thái truy vấn qua nhiều lượt hội thoại trên dữ liệu event có thuộc tính nested; tạo SQL đúng trong phạm vi hỗ trợ và hỏi lại khi chưa đủ thông tin.

**Hướng triển khai khuyến nghị:** tận dụng `LLM → QuerySpec → compiler → PostgreSQL` hiện có; bổ sung memory có cấu trúc, chính sách hỏi lại, hỗ trợ nested có giới hạn và evaluator dựa trên kết quả thực thi. Chưa thay đồng thời compiler bằng LLM sinh SQL tự do và PostgreSQL bằng DuckDB.

**Hướng thử nghiệm bổ sung:** direct LLM-to-SQL là baseline bắt buộc. Pipeline sinh SQL có AST validator và self-correction là một challenger tùy nguồn lực, không phải điều kiện để hoàn thành bản đầu. Nếu môn học yêu cầu LLM trực tiếp sinh SQL, cần chọn lại nhánh kiến trúc trước khi triển khai.

Không có số liệu thực nghiệm mới trong tài liệu này. Mọi kích thước benchmark, ngân sách và tiêu chí bên dưới là thiết kế đề xuất, không phải kết quả đã đạt.

## 2. Đã khám phá gì và code hiện tại thực sự làm gì?

Ba agents đọc độc lập: kiến trúc/ETL; memory/UX; evaluation/dataset. Agent chính kiểm tra lại các đoạn code quyết định. Chỉ đọc source và tài liệu, chưa chạy dịch vụ, tải dữ liệu hay gọi model thật.

| Phần | Bằng chứng trong repository | Ý nghĩa với kế hoạch |
|---|---|---|
| Luồng hiện tại | [answer.py](/Users/thanhhigk/Study/NLP/Final/backend/texa/answer.py:187), [pipeline.py](/Users/thanhhigk/Study/NLP/Final/backend/texa/pipeline.py:30) | LLM diễn giải thành candidate/QuerySpec; Python validate, kiểm tra dữ liệu, compile, execute, tính facts. Không phải LLM sinh SQL trực tiếp. |
| Compiler và engine | [compile.py](/Users/thanhhigk/Study/NLP/Final/backend/texa/compile.py:45), [execute.py](/Users/thanhhigk/Study/NLP/Final/backend/texa/execute.py:26) | SQL PostgreSQL qua psycopg; JSON hiện được truy cập một key dưới `ep`/`up`. Có JSONB không đồng nghĩa đã hỗ trợ nested object/array tùy ý. |
| Chuẩn hóa nhiều nguồn | [01_init.sql](/Users/thanhhigk/Study/NLP/Final/pipeline/sql/init/01_init.sql:24), [run.py](/Users/thanhhigk/Study/NLP/Final/pipeline/texa_etl/run.py:20) | Cosmetics event stream và Olist relational cùng được đưa về event mart. Đã có giả định kiến trúc chung; chưa có bằng chứng áp dụng được cho mọi DB. |
| Catalog | [ecommerce.yaml](/Users/thanhhigk/Study/NLP/Final/catalog/ecommerce.yaml:82) | Metric phong phú, có traffic, revenue, ratio, retention, giao hàng/review. Scope thực tế đang rộng hơn một use case PM/PO. |
| Hỏi lại | [clarify.py](/Users/thanhhigk/Study/NLP/Final/backend/texa/clarify.py:66) | Có hỏi metric/nguồn/thời gian/filter. Một số alternative cùng nhóm được chọn phần tử đầu rồi cho đổi; chưa bảo đảm luôn hỏi khi khác biệt nghiệp vụ đáng kể. |
| Memory | [answer.py](/Users/thanhhigk/Study/NLP/Final/backend/texa/answer.py:97), [interpret.py](/Users/thanhhigk/Study/NLP/Final/backend/texa/interpret.py:96) | Lấy tối đa 6 lượt trước, loại running/error/cancelled; render thêm giới hạn khoảng 6.000 token. Đây là giới hạn context, chưa có bằng chứng thực nghiệm biện minh cho số 6. |
| Tham chiếu kết quả cũ | [answer.py](/Users/thanhhigk/Study/NLP/Final/backend/texa/answer.py:206) | Nhánh `answer_from_previous` chọn lượt `answered` gần nhất trong lịch sử lấy được; có thể lệch với kết quả người dùng thực sự đang nhắc. |
| Golden eval | [run_golden.py](/Users/thanhhigk/Study/NLP/Final/backend/eval/run_golden.py:24), [golden.yaml](/Users/thanhhigk/Study/NLP/Final/backend/eval/golden.yaml) | Có 63 cases, chấm status và các trường expectation được hỗ trợ. Không đối chiếu toàn bộ kết quả SQL với đáp án chuẩn. |
| Kiểm thử khác | [test_compile_numbers.py](/Users/thanhhigk/Study/NLP/Final/backend/tests/test_compile_numbers.py:9), [test_flow.py](/Users/thanhhigk/Study/NLP/Final/backend/tests/test_flow.py) | Có so compiler với SQL viết tay và scripted flow tests. Numeric tests có thể bị skip nếu warehouse chưa sẵn sàng. Không nên nói dự án hoàn toàn chưa có đánh giá. |

## 3. Đánh giá và refine từng đề xuất

| Đề xuất nhận được | Đánh giá | Refinement khuyến nghị |
|---|---|---|
| Người dùng là PM, PO, CEO không chuyên dev | Hợp lý về nhu cầu self-service nhưng vẫn quá rộng, chưa có user research trong source. | PM/PO theo dõi hành vi và chuyển đổi của một sản phẩm e-commerce là persona chính. Quản lý/C-level là nhóm phụ; chưa tối ưu cho báo cáo tài chính hay quyết định chiến lược. |
| DA/Dev không phù hợp vì LLM không chính xác 100% | Lập luận chưa đủ. DA cũng có thể dùng trợ lý; người ít chuyên môn lại khó phát hiện kết quả sai hơn. | Chọn persona theo công việc và giá trị tiết kiệm thời gian, không dựa trên khả năng chấp nhận sai. Vẫn cần nguồn số liệu, metric rõ ràng và cách kiểm chứng. |
| Tập trung event & nested để tránh relational | Thu hẹp workload là tốt; lý do “né” không thuyết phục. Event/nested vẫn được truy vấn bằng mô hình quan hệ và có thể rất phức tạp. | Chọn event vì phù hợp câu hỏi sản phẩm; định nghĩa nested depth, kiểu field, một array và grain dữ liệu. Không nhận bài toán join nhiều hệ thống doanh nghiệp. |
| Tự build dataset vì không có dataset phù hợp | Chưa có khảo sát đủ để kết luận không tồn tại dataset. Dataset riêng có nguy cơ tự thiết kế cho hệ thống dễ đạt điểm. | Xây benchmark riêng cho khoảng trống cụ thể: tiếng Việt, hội thoại, định nghĩa metric và nested event; công bố cách tạo, gold, split và giới hạn. Khảo sát benchmark công khai trước khi tuyên bố khoảng trống. |
| Baseline gọi thuần LLM | Cần thiết nhưng phải nói rõ LLM được cung cấp những gì. Không có schema/định nghĩa nghiệp vụ thì baseline bị làm yếu. | Direct prompting cùng model, engine, snapshot, schema, metric definitions, câu hỏi và ngân sách context; không có resolver riêng, compiler hay vòng sửa lỗi. |
| Resolver → Linker/Profiler → LLM SQL → AST/sandbox correction | Hợp lý như một phương án nghiên cứu, nhưng là chuyển hướng lớn so với code hiện có. Nhiều module có thể chỉ lặp chức năng catalog. | Giữ resolver và schema context nhẹ. Ưu tiên QuerySpec/compiler hiện có; đánh giá LLM SQL như baseline/challenger. Chỉ đưa challenger vào sản phẩm nếu có bằng chứng lợi ích. |
| Metric là độ chính xác SQL | Đúng hướng nhưng chưa có định nghĩa đo. Cùng ý nghĩa có thể có nhiều chuỗi SQL. | Primary: độ đúng kết quả thực thi trên câu hỏi có đáp án. Bổ sung chất lượng hỏi lại, memory, executable rate, độ trễ và chi phí. Không dùng exact SQL string match làm thước đo chính. |

### Persona và đầu ra sản phẩm

- PM/PO muốn biết: “Số người mua tuần này?”, “Chia theo thiết bị”, “Chỉ nhóm đến từ quảng cáo”, “Quay lại số liệu tuần trước”.
- Mỗi câu trả lời cần có bảng/số liệu, định nghĩa metric, filter, thời gian, độ mới dữ liệu và cảnh báo thiếu dữ liệu. SQL mở ra khi cần kiểm tra.
- “Tại sao giảm?” chỉ được mô tả chênh lệch/phân rã theo dữ liệu hỗ trợ. Không khẳng định nguyên nhân nhân quả từ một bảng event.
- Người chuẩn bị dữ liệu/catalog là vai trò kỹ thuật riêng. Bản đầu không yêu cầu PM tự tích hợp DB, thiết kế schema hay định nghĩa tất cả metric.
- Kiểm chứng persona bằng 3–5 trao đổi hoặc task walkthrough với người đại diện; nếu chưa tiếp cận được, ghi rõ đây là giả thuyết và dùng kịch bản đánh giá thay thế, không gọi là user validation.

## 4. Scope bản đầu

### 4.1 Data contract

Một domain e-commerce event, một dataset đang hoạt động và một SQL dialect: **PostgreSQL + JSONB** để tận dụng code. Không bổ sung connector DB mới trong giai đoạn này.

- Một event có ID duy nhất, timestamp, event type, user/session ID khi nguồn cung cấp, các thuộc tính scalar và nested object.
- Nested object: tối đa 2 cấp key dưới payload; khai báo path, kiểu dữ liệu, missing/null policy, phép lọc được hỗ trợ.
- Bản tối thiểu bắt buộc có câu hỏi thực sự dùng nested path; không chỉ đổi tên cột phẳng thành JSON rồi tuyên bố giải quyết nested analytics tổng quát.
- Một array `items[]` là phần mở rộng có điều kiện sau pilot; mỗi query tối đa một lần expand. Nếu không kịp triển khai và đánh giá, công bố phạm vi **nested object**, không tuyên bố hỗ trợ array.
- Với array phải phân biệt event grain và item grain; expand item không được nhân đôi event count hoặc event-level revenue. Chỉ hỗ trợ các tổ hợp aggregation được định nghĩa rõ.
- Chốt timezone, khoảng thời gian dạng `[start, end)`, ngày kết thúc và mốc “hôm nay” trong benchmark. Không để ngày máy chạy làm thay đổi gold.

Đây là contract cho một workload xác định, không phải kiến trúc chuẩn hóa dữ liệu của mọi doanh nghiệp. Import file/event cần mapping tường minh; dữ liệu không đúng contract bị báo lỗi hoặc loại kèm thống kê.

### 4.2 Metric và câu hỏi

P0 giữ khoảng 6–8 metric: event count, active users, sessions khi có ID, viewers, buyers, item purchases, revenue có định nghĩa rõ, và một tỷ lệ buyer/user. Hỗ trợ aggregate, theo ngày/tuần, breakdown, filter scalar/nested, top-k, đổi kỳ và follow-up.

Các tỷ lệ dùng tập người trong khoảng thời gian phải được gọi đúng tên: buyer/user ratio không chứng minh funnel có thứ tự. Không đồng nhất purchase item, order và session. Chưa có order ID thật thì không quảng bá order count/AOV chính xác.

Ngoài P0: cross-company normalization, nhiều currency/FX, Olist delivery/review, cohort/retention nhiều biến thể, funnel tuần tự, cross-database joins, ingest tài liệu doanh nghiệp và tự sinh catalog tổng quát. Giữ source cũ làm tham chiếu/regression, không xóa ngay.

### 4.3 Chọn dữ liệu

1. Giữ một snapshot nhỏ, cố định của Cosmetics/REES46 để làm sanity check trên dữ liệu event thật, sau khi kiểm tra quyền sử dụng và chất lượng. Không giả định dữ liệu này vốn có nested payload.
2. Tạo bộ event nested tổng hợp có seed, schema, quy tắc sinh và đáp án độc lập. Dùng một số schema variant đã định nghĩa trong cùng domain, không mở lại bài toán mọi DB.
3. Nếu serialize lại dữ liệu phẳng thành nested, phải ghi rõ đây là biến đổi cấu trúc, không phải nguồn nested tự nhiên. Không bịa thêm device/channel/geography rồi mô tả như dữ liệu thật.
4. Olist không nằm trong benchmark chính mới; vẫn giữ khả năng chạy regression cũ nếu môi trường đã có dữ liệu.

## 5. Kiến trúc khuyến nghị và phương án LLM SQL

### 5.1 Hướng A — ưu tiên để sửa dự án hiện tại

```text
Câu hỏi + conversation ID
  → nhận diện tiếp nối / chủ đề mới / tham chiếu cũ / ngoài phạm vi
  → chọn dialogue state và các evidence liên quan
  → resolver metric + QuerySpec, hỏi lại khi cần
  → schema context: path, kiểu, grain, metric definition, data coverage
  → validate QuerySpec + nested capabilities
  → deterministic PostgreSQL compiler
  → read-only execution có timeout/giới hạn
  → facts + câu trả lời có phạm vi rõ ràng
  → commit state có provenance sau khi xác nhận/thực thi thành công
```

Không cần mỗi hộp là một LLM call. Ưu tiên kết hợp phân loại và diễn giải trong output có schema; dùng Python cho kiểm tra ID, path, kiểu và policy. Profile dữ liệu tại import/cập nhật snapshot, cache theo dataset version; không quét DB lại cho mọi câu hỏi.

Catalog được thu gọn và xác nhận thủ công cho workload này. Schema linker khởi đầu bằng lookup catalog/path và mẫu giá trị an toàn; chưa cần vector DB/RAG riêng. Profiler chỉ xác định cấu trúc, kiểu và độ phủ; không tự suy ra định nghĩa nghiệp vụ từ sample.

### 5.2 Hướng B — challenger nếu cần nghiên cứu LLM sinh SQL

Giữ resolver, memory và context contract; thay compiler bằng LLM SQL generator, kiểm tra AST bằng sqlglot đúng dialect, rồi chạy trong môi trường chỉ đọc bị giới hạn. Tối đa 2 lần sửa sau lần sinh đầu; chỉ cung cấp lỗi parse/bind/runtime có kiểm soát, không đưa gold result vào vòng sửa.

AST phải kiểm tra toàn cây truy vấn, bảng/cột/function cho phép và nhiều statement. Parser không phải sandbox; quyền DB, timeout, tài nguyên và chặn truy cập ngoài phạm vi phải được áp dụng ở môi trường thực thi.

**SQL chạy được không đồng nghĩa hiểu đúng metric.** Sai time range, filter hoặc mẫu số có thể không gây runtime error. Self-correction không thay thế gold evaluation; báo điểm lần sinh đầu và sau correction riêng.

DuckDB thích hợp cho JSON/Parquet cục bộ nhưng chưa có trong code. Nếu chọn DuckDB thì tất cả baseline/system/gold dùng cùng DuckDB snapshot và dialect. Không dùng DuckDB để chứng minh SQL PostgreSQL đúng chỉ bằng parse/transpile. Chuyển engine là milestone riêng, chỉ thực hiện nếu lợi ích lớn hơn chi phí chuyển compiler, metadata và tests.

**Quyết định mặc định:** hướng A. Không gộp A và B thành một hệ thống lớn rồi mới đánh giá. Đóng góp chính là xử lý hội thoại/metric trong workload giới hạn; không gọi hệ thống là LLM SQL Generator nếu thực tế SQL do compiler sinh.

## 6. Memory: thay giới hạn lượt bằng trạng thái và tham chiếu

### 6.1 Vì sao “6” chưa đủ căn cứ?

Code lưu lịch sử trong DB, nhưng chỉ lấy 6 lượt trước vào bước diễn giải và còn cắt theo token. Thông tin không nhất thiết bị xóa khỏi DB; nó không được đưa lại vào context. Số 6 là lựa chọn kỹ thuật cần ablation, không phải giới hạn hợp lý đã được chứng minh.

“Một câu chứa 10 ví dụ” và “hội thoại dài 10 lượt” là hai vấn đề khác nhau. Trường hợp đầu liên quan độ dài input/token; trường hợp sau liên quan khôi phục ngữ cảnh. Bộ đánh giá cần tách hai trường hợp.

### 6.2 Trạng thái đề xuất

Lưu theo conversation và topic, tối thiểu gồm:

```text
dataset_version, catalog_version, topic_id
metric_id, metric_definition_version, time_range, grain
filters, breakdown, comparison
last_successful_query_id, referenced_result_id
pending_clarification
provenance: mỗi slot đến từ turn nào, do user xác nhận hay suy ra
```

Phân biệt state đã commit với candidate đang chờ hỏi lại; lỗi thực thi hoặc câu nhiễu không được ghi đè active query. User sửa một trường thì cập nhật trường đó, giữ các trường còn lại chỉ khi ngữ cảnh xác nhận là follow-up. Thay dataset/catalog phải kiểm tra lại slot và không dùng lại kết quả đã lỗi thời.

### 6.3 Chính sách xử lý

| Tình huống | Hành vi mong đợi |
|---|---|
| “Chia theo thiết bị” sau một query | Kế thừa metric/thời gian/filter phù hợp; đổi breakdown. |
| “Cảm ơn”, câu ngoài chủ đề | Trả lời ngắn hoặc giới hạn phạm vi; không thay active query. |
| Một câu hỏi đầy đủ thuộc chủ đề mới | Tạo state mới; không tự mang filter cũ sang. |
| “Quay lại doanh thu lúc nãy” | Tìm topic/query trước bằng metadata và lịch sử liên quan. Có nhiều ứng viên thì hỏi chọn. |
| “Không, tính theo người mua” | Sửa metric/denominator rõ ràng, lưu provenance, hiện lại cách hiểu. |
| “Tại sao?” khi có nhiều kết quả | Xác định result được nhắc; hỏi lại nếu chưa rõ, không mặc định luôn chọn answered gần nhất. |
| Câu mới bỏ ngỏ thông tin nghiệp vụ quan trọng | Hỏi câu ngắn với lựa chọn cụ thể; không âm thầm chọn alternative đầu. |

Context cho LLM gồm state đang dùng, câu mới, pending clarification và một số lượt/evidence liên quan trong ngân sách token. Khi cần quay lại chủ đề cũ, tìm trong lịch sử đã lưu thay vì chỉ trong 6 lượt. Bắt đầu bằng metadata/keyword và ID tham chiếu; chỉ dùng embeddings nếu đánh giá cho thấy lookup đơn giản chưa đủ.

Không đưa toàn bộ insight/SQL cũ vào prompt mặc định. Nếu cần summary văn bản, tạo từ state có cấu trúc và giữ nguồn tham chiếu; summary do LLM tự viết có thể làm sai hoặc mất điều kiện.

### 6.4 Chứng minh memory hiệu quả

So sánh fixed window 2/6/10, full history có giới hạn token, và structured state + relevant evidence trên cùng tập hội thoại. Đo phụ thuộc cách 1/6/8/10 lượt, chuỗi 4/8/12 lượt, nhiều lượt nhiễu, đổi chủ đề, quay lại chủ đề và user correction. Các tham số budget/retrieval được chọn trên dev, không chọn bằng test.

Kiến trúc này có thể giữ state lâu hơn cửa sổ prompt; không hứa nhớ vô hạn hoặc luôn xác định đúng mọi tham chiếu.

## 7. Dataset, baseline và protocol đánh giá

### 7.1 Câu hỏi nghiên cứu

- RQ1: hệ thống có cải thiện độ đúng kết quả so với direct LLM-to-SQL khi cùng thông tin nghiệp vụ và dữ liệu không?
- RQ2: structured memory có giảm mất/ngộ nhận ngữ cảnh so với cửa sổ 6 trên phụ thuộc dài và câu nhiễu không?
- RQ3: chính sách resolver có hỏi đúng lúc thay vì đoán metric hoặc hỏi thừa không?

### 7.2 Benchmark đề xuất

Pilot: 24 single-turn cases và 6 hội thoại để kiểm tra evaluator/khả năng annotate. Sau pilot mới đóng protocol và ngân sách.

Bộ chính dự kiến: **120 single-turn cases** (20 dev, 100 held-out test) và **24 hội thoại** (6 dev, 18 test; test có 6 chuỗi mỗi độ dài 4/8/12). Không fine-tune nên không bắt buộc train split; few-shot chỉ lấy từ tập phát triển được chỉ định.

- Single-turn bao gồm query scalar, nested path, aggregation, time, ratio, câu mơ hồ và ngoài phạm vi. Tách nhóm query có đáp án với nhóm cần clarification/refusal.
- Hội thoại gắn nhãn từng lượt: action, referenced turn, gold state sau lượt, SQL/result khi cần, và câu trả lời clarification chuẩn.
- Test phải có nhiều trường hợp độc lập mỗi nhóm, không chỉ paraphrase cùng một câu. Split theo query template/intent family và toàn bộ dialogue; các paraphrase, bản VI/EN của cùng câu và cùng họ scenario không được rải sang cả dev/test.
- Tiếng Việt là tập chính theo persona. EN là tập bổ sung nếu đủ nguồn lực; báo điểm riêng, không tuyên bố bilingual nếu chỉ kiểm tra vài câu.
- Mỗi record có ID, ngôn ngữ, nguồn/seed, schema/snapshot version, metric definition, câu hỏi, gold action, gold SQL khi phù hợp, kết quả chuẩn và nhãn độ khó.
- Người viết gold phải xem xét ý định và tính kết quả độc lập; không lấy output hệ thống làm đáp án. Review toàn bộ case mơ hồ/nested-grain và tối thiểu một mẫu 20% còn lại bởi người thứ hai; nếu thiếu reviewer, công bố hạn chế.
- Dataset generator và SQL gold không dùng chung implementation aggregation với compiler hệ thống. Có fixture tính tay để phát hiện lỗi cùng chiều.
- Freeze test trước khi tuning. Không đưa test/gold vào catalog `verified_questions`, prompt few-shot, profile có câu trả lời hoặc bước self-correction. Profile schema/thống kê dữ liệu được phép nếu mọi phương pháp đều được tiếp cận cùng thông tin.

### 7.3 Baseline và ablation

| Cấu hình | Mục đích |
|---|---|
| B0: direct LLM → SQL, schema + metric definitions, không correction | Baseline chính single-turn. Cùng model/dialect/dữ liệu, không cố tình thiếu định nghĩa metric. |
| B1: direct LLM → SQL + raw 6-turn history | Baseline hội thoại, tách hiệu ứng của việc có lịch sử khỏi phương pháp memory mới. |
| S0: hệ thống QuerySpec/compiler hiện tại với window 6, trên workload nó hỗ trợ | Mốc hiện trạng. Nested mới chưa hỗ trợ được báo là unsupported, không loại khỏi thống kê coverage. |
| S1: hệ thống hướng A với structured memory và resolver đã refine | Phương pháp chính. So cùng workload với B0/B1; báo coverage cùng accuracy. |
| Ablation S1 dùng window 6 thay memory mới | Cô lập đóng góp memory khi các thành phần còn lại giống nhau. |
| Ablation S1 bỏ chính sách hỏi lại mới | Đánh giá resolver, bao gồm đoán sai và hỏi thừa. |
| Challenger hướng B, nếu thực hiện | Thử LLM SQL + AST/correction; báo trước/sau sửa và thêm chi phí. Không cần làm để hoàn tất hướng A. |

Không kết luận “module X tốt” chỉ bằng so B0 với S1 vì nhiều thành phần thay đổi cùng lúc. Baseline được phép trả `clarify/refuse` bằng cùng output contract trong bài đo action; thiếu khả năng này phải được công bố là giới hạn của baseline, không coi đó là so sánh ngang bằng.

Giữ cố định model/provider/version, decoding khi API hỗ trợ, input facts, snapshot và giới hạn tài nguyên. Dùng cùng model chính; model thứ hai là kiểm tra bổ sung, không bắt buộc. Ghi đầy đủ token, số lần gọi và retries. Profile context tương đương cho phép so phương pháp công bằng; latency/cost vẫn tính toàn bộ overhead của hệ thống.

### 7.4 Metric phải được định nghĩa trước khi chạy

**Primary — Execution/Result Accuracy trên tập answerable:**

`số câu có kết quả candidate tương đương gold / tổng số câu answerable trong scope benchmark`

SQL lỗi, timeout, hệ thống từ chối câu thực ra trả lời được hoặc không sinh SQL đều tính sai; không chỉ chia trên số câu chạy thành công. Công bố accuracy trên toàn scope và trên phần giao capabilities để phân biệt coverage với chất lượng diễn giải.

Quy tắc đối chiếu:

- Chạy candidate và gold trên cùng snapshot và cùng engine. Lấy kết quả đầy đủ trong evaluator; không so chỉ 100 dòng UI lưu hoặc preview bị truncate.
- So số cột/ý nghĩa output, shape và multiset hàng nếu không yêu cầu thứ tự; giữ duplicate. Khi người dùng yêu cầu xếp hạng/top-k phải kiểm tra thứ tự và policy tie đã chốt.
- Chuẩn hóa date/time, NULL và tên/ánh xạ cột theo output contract. Count/integer so chính xác; float có tolerance được định nghĩa trước, ví dụ `abs=1e-6, rel=1e-6`; tiền dùng precision phù hợp contract.
- Gold empty result chỉ đúng nếu thật sự được thiết kế; không dùng fixture toàn rỗng làm bằng chứng ngữ nghĩa.
- Với từng nhóm lỗi quan trọng, chạy thêm fixture đổi phân phối/biên: missing key, null, số 0, duplicate, ngày biên, item array nhiều phần tử nếu có. Điều này giảm việc SQL sai tình cờ ra cùng kết quả trên một DB.
- Execution equivalence trên một số fixture là bằng chứng thực nghiệm, không phải chứng minh tương đương SQL cho mọi dữ liệu. SQL exact match/AST match chỉ là diagnostic phụ nếu cần.

**Các metric bắt buộc bổ sung:**

| Metric | Cách đo |
|---|---|
| Executable rate | Tỷ lệ SQL thực thi được; báo riêng để không nhầm với semantic correctness. |
| Clarification precision/recall | TP là hỏi trường thiếu/mơ hồ đúng theo gold; hỏi thừa là FP, đoán khi cần hỏi là FN. Có chấm nội dung câu hỏi, không chỉ status. |
| End-to-end task success | Hoàn thành đúng intent sau tối đa 2 lượt hỏi lại; clarification oracle chỉ trả lời trường được hỏi, không đưa SQL hoặc toàn bộ gold state. |
| Context/slot accuracy | Metric, time, filters, breakdown và referenced turn khớp gold state; báo theo slot và toàn state. |
| Context contamination | Tỷ lệ tình huống đổi chủ đề/nhiễu bị mang theo slot cũ trái gold; mẫu số là các lượt được gắn nhãn cần kiểm tra kế thừa. |
| Dialogue success | Tỷ lệ hội thoại mà mọi lượt cần hành động quan trọng đều đúng; báo thêm accuracy theo độ dài và dependency distance. |
| Refusal/action quality | Bảng nhầm lẫn answer/clarify/refuse/conversation; từ chối đúng ngoài phạm vi và từ chối sai câu answerable được tách riêng. |
| Cost/latency | Token, số calls, chi phí khi có giá xác định, p50/p95 thời gian; bao gồm resolver/linker/correction nếu có. |

Chạy hội thoại **rollout** bằng output thực tế để thấy lỗi tích lũy. Có thể thêm chế độ gold prior state để chẩn đoán riêng lượt hiện tại, nhưng không trộn hai kết quả. Baseline hội thoại dùng cùng lịch sử khả dụng; không được cho gold state nếu phương pháp chính phải tự suy ra.

Lặp tối thiểu 3 lần nếu ngân sách cho phép; lưu raw output và độ dao động, không chọn lần tốt nhất. Báo chênh lệch theo cặp và khoảng tin cậy bootstrap; resample theo scenario family/dialogue để không coi các lượt hoặc paraphrase phụ thuộc là mẫu độc lập. Tập nhỏ thì ghi rõ bất định và không tuyên bố chắc chắn thắng baseline.

Chưa đặt mốc “90% SQL accuracy” theo điểm golden cũ. Tiêu chí nghiên cứu là cải thiện so baseline, phân tích trade-off và giới hạn. Muốn tuyên bố cải thiện thì cần delta dương với mức bất định được báo; nếu không đạt vẫn báo kết quả âm và phân tích nguyên nhân.

## 8. Plan triển khai sau khi review

Các đường dẫn dưới đây là nơi dự kiến sửa/thêm, **chưa được tạo hoặc chỉnh ở giai đoạn này** ngoài chính file kế hoạch.

| Giai đoạn | Công việc và vị trí dự kiến | Đầu ra/điều kiện chuyển bước |
|---|---|---|
| P0.1 — Chốt định vị và scope | Refine README/PLAN; giảm catalog chính; inventory metric giữ/hoãn; chốt object-only hay thêm array. | Một persona chính, data contract, danh sách metric/câu hỏi hỗ trợ, non-goals và task walkthrough. Chưa thêm engine. |
| P0.2 — Dữ liệu và evaluator trước | `backend/eval/`: benchmark spec, case schema, fixtures, comparator và baseline runner; `data/`: manifest/seed, không commit khối dữ liệu lớn tùy tiện. | Pilot tính đúng các fixture biết trước; evaluator bắt được sai metric/date/filter/grain, executable-but-wrong SQL và false refusal. Freeze protocol/split. |
| P0.3 — Lập mốc hiện trạng | Chạy B0/B1/S0 trên snapshot; ghi unsupported và các test skip. | Báo baseline có raw logs, lỗi phân nhóm, latency/cost; không dùng golden pass rate thay result accuracy. |
| P0.4 — Resolver và structured memory | Tách module state/context; `answer.py`, `interpret.py`, `clarify.py`, `prompts.py`; bổ sung schema DB/migration để lưu state/provenance và topic references. | State update có kiểm soát; hồi phục sau reload; noise không ghi đè query; tham chiếu xa và đổi chủ đề được đánh giá trên dev. |
| P0.5 — Nested query support có giới hạn | `catalog.py`, `spec.py`, `compile.py`, `sanity.py`; adapter/profile cho schema đã chốt; tests theo nested paths và grain. | Path/kiểu không hỗ trợ bị chặn; missing/null có semantics rõ; numeric parity với gold độc lập. Array chỉ mở sau khi object path ổn định. |
| P0.6 — Trả lời dễ kiểm chứng | `web/src/components/TurnView.tsx`, catalog UI và response metadata khi cần. | PM thấy metric/filter/thời gian/nguồn; câu hỏi mơ hồ có lựa chọn; không phải đọc SQL để hiểu cách tính. Giữ facts grounding hiện có. |
| P0.7 — Đánh giá và báo cáo | Chạy S1, baseline và ablation trên test đã freeze; giữ golden cũ như regression riêng. | Kết quả theo nhóm, CI, cost, ví dụ sai, giới hạn; chỉ kết luận trong domain/scope đã đo. |
| P1 — Challenger | Chỉ khi còn thời gian hoặc rubric yêu cầu: LLM SQL generator + AST + bounded correction; DuckDB là quyết định tách biệt. | So sánh có kiểm soát; không làm chậm việc hoàn thành P0. |

Chưa có deadline và số người triển khai nên không gán lịch ngày/tuần chắc chắn. Khi thiếu thời gian, cắt array, challenger, model thứ hai và EN trước; giữ evaluator, memory, resolver và workload object nested tối thiểu.

### Điều phối agents cho giai đoạn sửa sau này

- Main agent quyết định contract, semantics metric, memory state transition, tích hợp và review tính đúng dữ liệu.
- Explorer đọc call sites/tests/schema và trả báo cáo file:line ngắn; không tự mở rộng phạm vi sang dự án khác.
- Worker evaluator phụ trách baseline/comparator/fixtures sau khi main chốt spec; worker tests chạy bộ kiểm thử và báo rõ pass/fail/skip.
- Các worker chỉ sửa file được phân công; tránh cùng sửa `answer.py`, `compile.py` hoặc catalog. Main kiểm tra critical changes và các claims từ báo cáo agents.
- Benchmark held-out không được dùng làm tài liệu tuning cho worker triển khai. Mọi file và runtime artifact của dự án nằm trong `Final`.

## 9. Tiêu chí nghiệm thu và rủi ro chính

### Nghiệm thu bản đầu

- [ ] Persona, use case, scope event/nested và metric definitions nhất quán giữa README, giao diện và báo cáo.
- [ ] Có direct prompting baseline chạy lại được, cùng model/schema/definitions/snapshot với hệ thống.
- [ ] Có benchmark versioned, gold SQL/results, held-out split và quy tắc scoring; phân biệt rõ dữ liệu thật, biến đổi và tổng hợp.
- [ ] Có result accuracy và metric hội thoại; không gắn nhãn golden field pass rate thành SQL accuracy.
- [ ] Memory qua được regression định trước: hơn 6 lượt, nhiễu, đổi topic, quay lại, correction và câu tham chiếu mơ hồ; báo kết quả toàn bộ held-out, không chỉ demo thành công.
- [ ] Compiler nested được kiểm chứng bằng dữ liệu biên và gold độc lập; không quảng bá array nếu chưa kiểm thử.
- [ ] Báo đủ test bị skip và lỗi/từ chối/timeout, không loại chúng để nâng điểm.
- [ ] Người dùng xem được cách hiểu câu hỏi và giả định; kết quả chưa rõ phải được hỏi lại hoặc giới hạn trả lời.

### Rủi ro và cách giảm

| Rủi ro | Cách xử lý |
|---|---|
| Scope mới lại thành platform tổng quát | Giữ một domain, một dialect, giới hạn path/array, 6–8 metric. Mỗi scope thêm cần chỉ rõ phần bị cắt hoặc nguồn lực thêm. |
| Dataset riêng thiên vị hệ thống | Gold độc lập, family split, reviewer, real-event sanity check, công bố generation và giới hạn generalization. |
| Compiler thắng vì chỉ cho câu hỏi nó hỗ trợ | Công bố capability contract trước; báo coverage trên toàn test và accuracy trên phần giao. Baseline nhận cùng định nghĩa metric. |
| Memory lưu nhầm giả định và kéo dài lỗi | Provenance từng slot, pending/committed state tách riêng, explicit correction và hỏi lại khi nhiều antecedent. |
| Tăng hỏi lại làm chậm người dùng | Đo precision/recall hỏi lại và task success trong budget; không coi hỏi lại mọi câu là tốt. |
| Nhầm đúng cú pháp với đúng nghiệp vụ | Result comparison nhiều fixture và kiểm tra metric/filter/date/grain riêng. |
| Giảm scope lệch rubric Conversational QA | Trình bày tổng quan dialogue management, context và các hướng nghiên cứu; giải thích vì sao ứng dụng chọn structured data. RAG/IE tài liệu là related work/future scope trừ khi giảng viên xác nhận là yêu cầu bắt buộc. |

## 10. Các điểm cần chốt trước triển khai

Đề xuất mặc định đã có để không làm kế hoạch bị treo; các điểm còn mở phải được xác nhận khi bắt đầu sửa:

1. **Rubric môn học — người phụ trách đề tài:** trọng tâm là Conversational QA hay bắt buộc LLM trực tiếp sinh SQL? Mặc định chọn Conversational QA trên dữ liệu có cấu trúc và giữ compiler.
2. **Thời gian/nhân lực — nhóm:** dùng để chốt kích thước benchmark và có mở array/challenger hay không. Không cắt evaluation nền tảng chỉ để thêm tính năng.
3. **Reviewer gold — nhóm/người hỗ trợ:** ai review độc lập và phạm vi review; nếu không có phải ghi hạn chế trong báo cáo.
4. **Literature/dataset gap — nhóm nghiên cứu:** khảo sát Spider/BIRD về single-turn, SParC/CoSQL về hội thoại và benchmark nested/event liên quan; xác minh nguồn trước khi viết “chưa có dataset phù hợp”. Các tên này là đầu mối khảo sát, chưa phải kết luận đã đối chiếu đầy đủ.

Các tài liệu cần cập nhật sau khi thống nhất: định vị và claim trong README; kiến trúc trong PLAN; tài liệu trình bày và phần evaluation. Chưa cập nhật các file đó trong lượt này để tránh biến đề xuất chưa chốt thành mô tả hệ thống đã có.
