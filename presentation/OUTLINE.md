# Texa: dàn ý thuyết trình (bản tóm tắt để chốt)

> Mỗi mục ghi **thông điệp chính** và **ý cần nói**. Sau khi chốt dàn ý sẽ viết script đầy đủ (lời nói + gợi ý slide).
> Số liệu có ⚠️ là trích từ paper, cần kiểm tra lại trước khi đưa lên slide.

Thời lượng dự kiến khoảng 15–20 phút, chia làm 6 phần.

---

## 1. Problem statement, goals, scope, assumptions (~3')

**Thông điệp chính:** người làm kinh doanh muốn hỏi dữ liệu bằng ngôn ngữ tự nhiên. Nhưng nếu để LLM tự viết SQL thì nó có thể **bịa số** hoặc hiểu sai nghiệp vụ, và người hỏi không có cách nào kiểm tra.

- **Problem:** Text-to-SQL trên dữ liệu thật gặp 3 khó khăn:
  - schema lớn;
  - một khái niệm nghiệp vụ có nhiều cách ghi, ví dụ "purchase" ở nguồn này là `purchase`, ở nguồn kia là `order_purchased`;
  - câu trả lời của LLM không truy vết được về dữ liệu.
- **Goals:**
  1. Trả lời đúng câu hỏi tiếng Việt và tiếng Anh trên dữ liệu e-commerce.
  2. Mọi con số hiển thị đều truy vết được: lấy từ SQL, do server tính, hoặc do người dùng nhập.
  3. Hệ thống **fail closed**: thiếu dữ liệu thì từ chối hoặc hỏi lại, không trả về số giả.
- **Scope v1:**
  - Có: chat → QuerySpec → SQL → bảng kết quả + nhận xét; 2 nguồn dữ liệu; nhiều LLM provider.
  - Không có: chart, phân tích tự do (analytic mode), dashboard.
- **Assumptions:**
  - Dữ liệu là dữ liệu lịch sử, nên "7 ngày gần nhất" được tính đến `max_date` của nguồn, không tính đến hôm nay.
  - Catalog do người hiểu nghiệp vụ viết.
  - Câu hỏi nằm trong phạm vi các metric đã định nghĩa trong catalog.

## 2. Literature review: methods / techniques / architecture (~4')

**Thông điệp chính:** có 3 hướng tiếp cận chính. Texa chọn hướng thứ 3 để đổi lấy độ tin cậy.

| Hướng | Đại diện | Điểm mạnh | Điểm yếu |
|---|---|---|---|
| Rule / grammar-based, seq2seq cổ điển | NaLIR, Seq2SQL, SQLNet, IRNet, RAT-SQL | SQL đúng cú pháp, kiểm soát được | Cần nhiều dữ liệu train, khó chuyển sang domain khác, kém với câu hỏi tự do |
| LLM sinh SQL trực tiếp (prompting) | DIN-SQL, DAIL-SQL, C3, MAC-SQL; self-correction | Không cần train, linh hoạt, mạnh trên benchmark | Hallucinate bảng/cột, sai logic nghiệp vụ mà không báo, khó audit, tốn token khi schema lớn |
| Semantic layer + LLM chọn ý định | dbt Semantic Layer / MetricFlow, Cube, LookML, DIego (Inwave) | Định nghĩa metric thống nhất, SQL do compiler sinh nên đúng và an toàn | Chỉ hỏi được trong phạm vi catalog, phải tốn công viết catalog |

- Một số kỹ thuật bổ trợ cần nhắc tới: schema linking, constrained decoding (PICARD), structured output (JSON schema), RAG trên schema/catalog.

## 3. Available datasets: compare and contrast (~3')

**Thông điệp chính:** có 2 loại dataset. Benchmark dùng để đo khả năng sinh SQL; dataset nghiệp vụ dùng để kiểm tra hệ thống chạy thật.

- **Benchmark Text-to-SQL:**
  - WikiSQL: 1 bảng, câu hỏi đơn giản.
  - Spider: cross-domain, nhiều bảng.
  - BIRD: DB lớn, dữ liệu "bẩn", cần kiến thức ngoài.
  - Spider 2.0: workflow doanh nghiệp.
  - Một số dataset tiếng Việt: ViText2SQL.
- **Dữ liệu Texa dùng** (Kaggle):
  - REES46 Cosmetics: khoảng 20 triệu event, dạng event stream view/cart/purchase, có session, tiền USD, không có địa lý.
  - Olist: khoảng 100 nghìn đơn, 9 bảng quan hệ, có địa lý, thanh toán, review, giao hàng, tiền BRL.
- **So sánh:** hai nguồn khác nhau ở 3 điểm: dạng event và dạng quan hệ, tên event khác nhau, đơn vị tiền khác nhau. Đây là lý do cần:
  - ETL đưa cả hai về bảng thống nhất `event_activity`;
  - catalog ánh xạ ngữ nghĩa giữa hai nguồn;
  - quy đổi BRL sang USD theo tỷ giá FRED từng ngày.
- **Vì sao không dùng thẳng Spider/BIRD:** hai bộ này chấm câu SQL. Texa không sinh SQL tự do mà sinh QuerySpec, nên cần một bộ golden riêng.

## 4. Results from previous work (~3')

**Thông điệp chính:** LLM đạt điểm rất cao trên benchmark học thuật, nhưng tụt mạnh khi gặp dữ liệu giống doanh nghiệp. Đó là động lực cho cách tiếp cận dùng semantic layer.

- Spider: các phương pháp LLM prompting (DIN-SQL, DAIL-SQL) đạt khoảng 85–87% execution accuracy ⚠️.
- BIRD: GPT-4 đạt khoảng 55% so với con người khoảng 93% ⚠️. Khoảng cách đến từ dữ liệu bẩn và kiến thức nghiệp vụ.
- Spider 2.0: các model mạnh nhất chỉ đạt khoảng 10–20% ⚠️.
- Nghiên cứu của data.world về knowledge graph / semantic layer: độ chính xác tăng từ khoảng 16% lên khoảng 54% ⚠️.
- **Kết luận rút ra:** cái khó nằm ở nghiệp vụ, không nằm ở cú pháp SQL. Vì vậy hãy đưa nghiệp vụ vào catalog và để LLM làm phần nó giỏi là hiểu ý định.

## 5. Proposed methods: kiến trúc Texa (~5', phần chính)

**Thông điệp chính:** "Compiler trước, model sau". Model chỉ chọn, Python mới là bên tính.

1. **Data pipeline:** Airflow ELT gồm raw → staging → `analytics.event_activity`. Mỗi nguồn là một partition. Có các bước quality check, vocabulary và bảng tỷ giá FX.
2. **Semantic catalog** (`ecommerce.yaml`): định nghĩa event roles, dimensions, metrics (simple, ratio, cohort, per_user, per_day), field mappings và glossary.
3. **Pipeline trả lời** (demo luồng SSE):
   - context
   - **interpret**: LLM tạo QuerySpec bằng structured output, chỉ được chọn id có trong catalog
   - clarify: hỏi lại người dùng nếu câu hỏi mơ hồ
   - **validate**: kiểm tra với catalog và vocabulary
   - compile: sinh SQL có tham số
   - run: chạy bằng role chỉ đọc, có timeout
   - **facts**
   - **insight**: LLM viết nhận xét, chỉ được dùng placeholder `[[fact_id]]`
4. **Cơ chế truy vết số liệu:** facts từ SQL, calculations tính ở server (`derive.py`), giá trị do người dùng nhập. Model không bao giờ tự gõ chữ số.
5. **Hệ thống:** FastAPI, React chat UI, hỗ trợ nhiều provider (Gemini, Claude, OpenAI), có thể sửa hoặc chạy lại câu hỏi cũ.
6. **Đánh giá:** bộ golden khoảng 30+ câu hỏi song ngữ. Chấm theo status, metric, dimension, filter, time range và calculation, tức là chấm **ý định** chứ không chấm chuỗi SQL.
   - ⚠️ **Hiện chưa có kết quả eval chạy live.** Cần chạy `backend/eval/run_golden.py` trước buổi thuyết trình để có số liệu cho phần này.

## 6. Demo + kết luận (~2')

- Demo 3 câu:
  1. Một câu được trả lời bình thường.
  2. Một câu mơ hồ, hệ thống phải hỏi lại.
  3. Một câu bị từ chối, ví dụ hỏi "add to cart" trên Olist, nguồn không có event này.
- Hạn chế: chỉ hỏi được trong phạm vi catalog, tốn công viết catalog, chưa có chart.
- Hướng phát triển: chart, analytic mode, thêm nguồn thứ 3 (UK giftshop) mà không phải sửa code AI.

---

### Cần chốt
- [ ] Thời lượng và số slide?
- [ ] Ngôn ngữ của script: tiếng Việt, tiếng Anh, hay slide tiếng Anh và lời nói tiếng Việt?
- [ ] Có chạy eval live để có số liệu cho mục 5.6 không?
- [ ] Demo trực tiếp hay quay video trước?
