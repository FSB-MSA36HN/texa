> **Tài liệu kiến trúc cũ, giữ để tham chiếu.** Scope triển khai hiện hành nằm trong [kế hoạch refinement](PLAN_REFINEMENT_EVENT_CONVERSATIONAL_QA.md) và [product contract](docs/PRODUCT_SCOPE.md). Các nguồn tham chiếu lịch sử bên dưới không phải phụ thuộc và không được truy cập trong đợt triển khai này.

# Texa: hệ thống Text-to-SQL dùng semantic catalog (học theo DIego)

> Khi được duyệt, file này được copy thành `/Users/thanhhigk/Study/NLP/Final/PLAN.md` (bước đầu tiên của M0).

## 0. Context

DIego (Inwave) trả lời câu hỏi dữ liệu theo nguyên tắc **"compiler trước, model sau"**. Model chỉ chọn id từ semantic catalog để tạo ra một `QuerySpec` JSON. Python sẽ validate, compile thành SQL có tham số, chạy truy vấn, tính sẵn các facts, rồi model chỉ viết nhận xét dựa trên các facts đó. DIego **fail closed**: thiếu dữ liệu thì từ chối, không bao giờ trả về một số 0 giả.

Texa là một dự án **độc lập** áp dụng lại cùng cơ chế đó, với các khác biệt sau:
- **Dữ liệu:** dữ liệu e-commerce công khai (Kaggle) thay cho dữ liệu game của Inwave. Có pipeline ETL riêng (Airflow → PostgreSQL) để chuẩn hóa về **một bảng `event_activity` thống nhất**.
- **UI:** chỉ một màn hình chat full-screen, có chọn provider/model. Không có dashboard, Insight Maker hay admin cabinet.
- **Scope v1:** text → SQL → bảng kết quả + nhận xét insight. **Không** có chart và **không** có Analytic mode (để sau).

**Đã chốt với user:** dataset e-commerce (REES46 Cosmetics + Olist); stack FastAPI + React/Vite; provider đầu tiên là Gemini.

**Tham chiếu DIego** (chỉ đọc, dùng làm mẫu, không import code):
- Luồng chính: `di_backend/src/apps/header_tools/organization/bi_tool/diego_data_question.py` (`CANDIDATE_SCHEMA`, `_INTERPRET_INSTRUCTION`, `_interpretation_prompt`, `_select_entries`, `_advance`, `_result_facts`, `_ANSWER_INSTRUCTION`)
- Validator + compiler: `.../bi_tool/diego_query_spec.py` (`validate_query_spec`, `compile_query_spec`, `check_game_vocabulary`, `_preview_warnings`)
- Catalog: `.../bi_tool/diego_semantic_catalog.py` (`_validate_business`, draft/publish)
- Provider: `.../bi_tool/diego_provider.py` (`generate_structured`, Fernet)
- Catalog mẫu: `docs/diego/semantic-catalog/mobile-game-starter.yaml`
- UI chat: `di_frontend/src/.../dashboard/AiSidePanel.tsx`, `ai-panel/AiChatHistory.tsx` (`DataQuestionClarificationForm`), `ai-panel/DiegoRunProgress.tsx`

---

## 1. Hệ thống preprocess / ETL dữ liệu

### 1.1 Dataset được chọn

| source_id | Dataset (Kaggle) | Nội dung | Vì sao chọn |
|---|---|---|---|
| `cosmetics_shop` | `mkechinov/ecommerce-events-history-in-cosmetics-shop` (REES46 Open CDP) | 5 file CSV, 10/2019 → 02/2020, khoảng 20 triệu event: `event_time, event_type (view/cart/remove_from_cart/purchase), product_id, category_id, category_code, brand, price, user_id, user_session` | Đã là dữ liệu dạng event, có session và funnel view → cart → purchase. Gần với GA4 event stream nhất. |
| `olist_marketplace` | `olistbr/brazilian-ecommerce` (Olist) | 9 bảng quan hệ, 2016-09 → 2018-10, khoảng 100 nghìn đơn: orders, order_items, payments, reviews, customers, products, sellers, category_translation | Dữ liệu **quan hệ**, phải "event hóa". Có địa lý (bang/thành phố), thanh toán, review, giao hàng. Tên event **khác** nguồn 1, nên demo được đúng cơ chế ánh xạ của catalog. |
| *(stretch)* `uk_giftshop` | UCI Online Retail II (`mashlyn/online-retail-ii-uci`) | Hóa đơn 2009–2011, có country và hóa đơn hủy `C…` | Dùng để chứng minh "thêm nguồn mới mà không sửa code AI": chỉ cần thêm 1 DAG và vài dòng mapping trong catalog. |

Mặc định nạp REES46 2 tháng (12/2019–01/2020, khoảng 8 triệu dòng). Muốn nạp đủ 5 tháng thì đặt biến `REES46_MONTHS`.

### 1.2 Hạ tầng
- `docker-compose.yml` gồm:
  - `postgres:17`: một server, hai database `airflow` và `texa`.
  - `airflow`: image `apache/airflow:2.10.x`, chạy `airflow standalone` (LocalExecutor, 1 container, chỉ dùng cho dev).
  - `api` (FastAPI) và `web` (Vite).
- Các schema trong DB `texa`:
  - `raw`: CSV nạp nguyên trạng, tất cả cột là TEXT.
  - `staging`: đã ép kiểu, làm sạch, khử trùng lặp.
  - `analytics`: bảng `event_activity` cùng metadata.
  - `app`: dữ liệu của ứng dụng chat.
- Role `texa_reader` chỉ có quyền `SELECT` trên `analytics.*`, được set `default_transaction_read_only=on` và `statement_timeout=30s`. API dùng role này để chạy SQL do compiler sinh ra.

### 1.3 Pipeline (ELT bằng SQL, Airflow điều phối)
Mỗi nguồn có một DAG `ingest_<source_id>` (chạy tay hoặc `@once`), tất cả đều idempotent:
1. `download`: nếu `data/landing/<source>/` chưa có file thì gọi Kaggle API (cần `~/.kaggle/kaggle.json` do user cung cấp). User cũng có thể tải tay rồi bỏ file vào thư mục đó.
2. `load_raw`: `TRUNCATE raw.<source>_*` rồi `COPY FROM STDIN` bằng psycopg.
3. `stage`: chạy các file `pipeline/sql/<source>/staging_*.sql`, gồm:
   - Ép kiểu bằng hàm `try_cast`.
   - Đổi về timezone UTC.
   - Bỏ dòng trùng tuyệt đối.
   - Bỏ dòng thiếu `user_id` hoặc `event_time` và ghi số dòng bị bỏ vào `analytics.etl_runs`.
   - Gắn cờ giá ≤ 0.
4. `load_mart`: `DELETE FROM analytics.event_activity WHERE source_id = :s` rồi `INSERT … SELECT` từ staging trong một transaction (giống WRITE_TRUNCATE theo partition).
5. `quality_checks`: chạy các file `pipeline/sql/quality/*.sql`, mỗi file trả về các dòng vi phạm. Có vi phạm thì task fail. Các kiểm tra gồm:
   - PK duy nhất.
   - `event_date` không null.
   - `revenue ≥ 0`.
   - Mỗi `event_name` trong mart đều có trong vocabulary.
   - Tổng revenue khớp với staging.
6. `refresh_metadata`: ghi lại `analytics.source_registry` và `analytics.vocabulary` (xem 1.5).

### 1.4 Bảng thống nhất `analytics.event_activity`

Nguyên tắc học từ DIego:
- Mọi nguồn có **chung 100% cột bắt buộc**.
- Thuộc tính riêng của từng nguồn nằm trong `ep` (event params) và `up` (user properties) dạng JSONB.
- **Tên event giữ nguyên như nguồn ghi.** ETL chỉ chuẩn hóa *cấu trúc*, không chuẩn hóa *ngữ nghĩa*; phần ngữ nghĩa do catalog đảm nhận.

```sql
CREATE TABLE analytics.event_activity (
  event_id        text        NOT NULL,   -- md5(source_id||src key), ổn định giữa các lần chạy
  source_id       text        NOT NULL,   -- "game" trong DIego = "store" ở đây
  event_ts        timestamptz NOT NULL,
  event_date      date        NOT NULL,   -- ngày UTC
  event_name      text        NOT NULL,   -- tên gốc: view/cart/purchase/order_purchased...
  user_id         text        NOT NULL,
  session_id      text,
  first_seen_date date        NOT NULL,   -- ngày user xuất hiện lần đầu trong nguồn (≈ install_date)
  platform        text,                   -- web/unknown
  country         text, region text, city text,
  item_id         text, item_category text, item_brand text,
  item_price      numeric(14,2), quantity int,
  revenue         numeric(14,2),          -- chỉ khác null ở event mang tiền
  currency        text,                   -- USD/BRL theo nguồn (ghi rõ, không quy đổi ngầm)
  ep              jsonb NOT NULL DEFAULT '{}',
  up              jsonb NOT NULL DEFAULT '{}',
  src_table       text, ingested_at timestamptz DEFAULT now(),
  PRIMARY KEY (source_id, event_id)
) PARTITION BY LIST (source_id);
-- 1 partition / nguồn (≈ "1 bảng / game"); index (event_date), (event_name, event_date), (user_id); GIN(ep) chỉ khi cần.
```

**Ánh xạ nguồn → bảng thống nhất:**

| Cột / event | cosmetics_shop (REES46) | olist_marketplace |
|---|---|---|
| event_name | `view`, `cart`, `remove_from_cart`, `purchase` (giữ nguyên `event_type`) | Event hóa từ bảng quan hệ: `order_purchased` (mỗi order_item một dòng, theo `order_purchase_timestamp`), `order_approved`, `order_shipped`, `order_delivered`, `order_canceled`, `payment_made` (mỗi payment một dòng), `review_submitted` |
| user_id | `user_id` | `customer_unique_id` (không dùng `customer_id`, vì `customer_id` sinh mới theo từng đơn) |
| session_id | `user_session` | null |
| item_* | product_id, category_code cấp 1, brand, price | product_id, category đã dịch sang tiếng Anh, null, price |
| revenue | `price` khi event là `purchase` | `price` ở `order_purchased`; `payment_value` ở `payment_made` |
| country/region/city | null (nguồn không có dữ liệu địa lý) | BR / customer_state / customer_city |
| ep | `category_path`, `category_id` | `order_id`, `freight_value`, `seller_id`, `seller_state`, `payment_type`, `installments`, `review_score`, `delivery_days`, `is_late` |
| up | — | `customer_state`, `customer_zip_prefix` |
| currency | USD | BRL |

`first_seen_date` = `min(event_date)` theo `(source_id, user_id)`, tính trong bước `load_mart` bằng window function. Cột này dùng cho cohort metric như retention và repeat purchase.

### 1.5 Metadata cho AI và validator (thay cho "vocabulary cache 6h" của DIego)
- `analytics.source_registry`: `source_id, label, description, currency, min_date, max_date, row_count, user_count, last_loaded_at`.
- `analytics.vocabulary`: `source_id, kind (event_name | ep_key | up_key | value), field, value, event_count, last_seen`. Phần `value` chỉ lấy top 500 giá trị của các field có cardinality thấp.
- Validator dùng vocabulary để **từ chối** khi một event hoặc giá trị chưa từng được nguồn ghi nhận. Value-lookup cũng dùng nó để tự khớp giá trị user gõ, ví dụ "sao paulo" → `SP`.

**Quyết định quan trọng: mốc thời gian.** Dữ liệu là dữ liệu lịch sử, nên một khoảng tương đối như "7 ngày gần nhất" được tính **tính đến `max_date` của nguồn**, không tính đến hôm nay. Mốc này luôn được hiển thị trong câu trả lời, ví dụ "dữ liệu tới 2020-01-31".

---

## 2. Kiến trúc AI

### 2.1 Semantic catalog (`catalog/ecommerce.yaml`)
Dùng cùng grammar với `mobile-game-starter.yaml`, rút gọn cho v1. Catalog là định nghĩa nghiệp vụ, **không phải prompt và không phải SQL**.

```yaml
version: 1
table: analytics.event_activity
sources: [{id: cosmetics_shop, label: Cosmetics shop}, {id: olist_marketplace, label: Olist marketplace}]
columns:      # id, label, description, data_type, role (event_time|event_name|user_id|user_date|measure|attribute), allowed_operators
event_roles:  # 1 hành động nghiệp vụ -> các tên event ghi lại nó (theo nguồn)
  - {id: purchase, label: Purchase, events: [purchase, order_purchased]}
  - {id: add_to_cart, label: Add to cart, events: [cart]}          # olist không có -> từ chối có lý do
  - {id: product_view, label: Product view, events: [view]}
dimensions:   # field + cast, hoặc kind: bucket | days_since | first_or_repeat
  - {id: payment_type, label: Payment type, field: ep.payment_type, cast: text}
  - {id: price_range, label: Price range, kind: bucket, field: item_price, edges: [10, 50, 100, 500]}
metrics:      # type: simple | ratio | cohort | per_user | per_day
  - {id: revenue, label: Revenue, unit: currency, synonyms: [doanh thu, GMV, sales], type: simple,
     simple: {aggregation: sum, event_role: purchase, field: revenue}}
  - {id: cart_to_purchase_rate, label: Cart to purchase rate, unit: percent, type: ratio,
     ratio: {numerator: buyers, denominator: cart_users}}
field_mappings:  # cùng nghĩa, khác nguồn
  - {field: ep.order_id, source: cosmetics_shop, to: session_id}   # REES46 không có order_id → dùng session
variant_groups: [{id: conversion, metrics: [buyer_conversion_rate, purchase_event_rate]}]
glossary: [{id: aov, label: AOV, description: Average order value}, {id: cart_abandonment, ...}]
verified_questions: [...]   # few-shot + golden eval
data_notes: []
policy: {min_sample: 30, ask_when_missing: [], anchor_events: []}
```

V1 có khoảng 25 metric: users, active_users, events, product_views, add_to_carts, cart_users, purchases, buyers, orders (`count_distinct ep.order_id`), revenue, aov, arpu, arppu, view_to_cart_rate, cart_to_purchase_rate, buyer_conversion_rate, cart_abandonment_rate, cancel_rate, avg_review_score, late_delivery_rate, avg_delivery_days, repeat_purchase_rate_d30, retention_d7, retention_d30, items_per_order.

Khoảng 12 dimension: event_date / week / month, source, item_category, brand, country, region, city, payment_type, review_score, price_range, user_type (new/returning), days_since_first_seen.

**Vòng đời catalog:**
1. Lệnh CLI `texa catalog publish catalog/ecommerce.yaml` validate file bằng Pydantic cùng các luật chéo:
   - Mọi id tham chiếu đều phải tồn tại.
   - Ratio chỉ được tham chiếu tới metric `simple`.
   - Aggregation `sum` / `avg` cần field kiểu số.
   - Mỗi `event` phải có trong vocabulary của ít nhất một nguồn.
2. Sau đó ghi vào `app.catalog_versions (version, yaml, fingerprint, published_at)`.
3. Câu hỏi được gắn `contract_version`. Nếu catalog đổi giữa lúc hỏi và lúc trả lời thì Texa báo cho user.
4. Lệnh `texa catalog coverage` in ra mức độ khớp catalog của từng nguồn (bao nhiêu % metric dùng được, thiếu event hoặc field nào). Đây là bản rút gọn của "Độ phủ theo từng game".

Bỏ khỏi v1: UI chỉnh catalog, AI gợi ý mapping, cơ chế ký metric verification.

### 2.2 Backend: các module (`backend/texa/`, FastAPI, SQLAlchemy 2, psycopg 3)

| Module | Vai trò (tương ứng trong DIego) |
|---|---|
| `catalog.py` | Pydantic models, load bản catalog đã publish, build compact index (`_select_entries` index) |
| `context.py` | Chuẩn bị ngữ cảnh: catalog ≤ `TEXA_CONTEXT_BUDGET` (mặc định 32k token) thì gửi nguyên; vượt thì shortlist (`_interpretation_prompt`) |
| `interpret.py` | LLM hiểu câu hỏi → candidate JSON (`CANDIDATE_SCHEMA`) |
| `clarify.py` | Quyết định hỏi lại hay đi tiếp, không gọi AI (`_advance`) |
| `validate.py` | Validator QuerySpec (`validate_query_spec`) |
| `compile.py` | QuerySpec → SQL Postgres có tham số (`compile_query_spec`) |
| `sanity.py` | Soát dữ liệu: vocabulary, chống số 0 giả, cảnh báo đếm trùng (`check_game_vocabulary`, `_preview_warnings`) |
| `execute.py` | Chạy SQL bằng role `texa_reader`, giới hạn 2000 dòng, timeout |
| `facts.py` | Tính facts trên **toàn bộ** kết quả (`_metric_result_facts`) |
| `insight.py` | LLM viết nhận xét dựa trên facts |
| `llm.py` | `generate_structured(provider, model, system, prompt, schema)`; v1 chỉ có Gemini (`google-genai`, `response_json_schema`). Mã hóa key bằng Fernet, liệt kê model khả dụng, ghi usage |
| `runs.py` | Một run cho mỗi câu hỏi, các step được đẩy qua SSE |
| `api.py`, `models.py`, `prompts.py`, `main.py` | Routes, bảng `app.*`, các instruction |

Thêm provider OpenAI hoặc Claude về sau chỉ cần thêm một nhánh trong `llm.py` (giống 3 nhánh của `diego_provider.generate_structured`). V1 không làm interface hay factory.

### 2.3 Luồng chính (standard mode): thường 2 lần gọi AI cho mỗi câu hỏi

```
User hỏi ─► [1] Nhận câu hỏi + nạp hội thoại (QuerySpec & tóm tắt các turn trước, ≤6k token)
         ─► [2] Chuẩn bị ngữ cảnh: catalog đã publish + source_registry (+shortlist nếu > budget: 1 call nhỏ, ≤80 id, fallback lexical)
         ─► [3] AI hiểu câu hỏi (call #1, JSON schema bắt buộc) → candidate
         ─► [4] Kiểm candidate: mọi id tồn tại, ≤4 metric, ≤4 selection, ≤3 filter field
         ─► [5] Đủ & rõ? ── thiếu/mơ hồ ─► Form hỏi lại (nút bấm, KHÔNG gọi AI) ─► trả lời ─► quay lại [5]
                        └─ không làm được ─► Từ chối có lý do + gợi ý câu hỏi làm được
         ─► [6] Validator (Python) ─► [7] Compiler → SQL có tham số
         ─► [8] Soát dữ liệu (vocabulary, nguồn không ghi event → từ chối, không trả 0)
         ─► [9] Chạy query (read-only) ─► [10] Facts (code) ─► [11] AI viết nhận xét (call #2)
         ─► [12] Lưu turn, trả: diễn giải + insight + bảng (≤100 dòng preview) + SQL + cảnh báo + gợi ý hỏi tiếp
```

**Các outcome từ bước [3]:**
- `query`: tiếp tục pipeline.
- `conversation`: chào hỏi hoặc hỏi "bạn làm được gì". Trả lời kèm 3 câu hỏi gợi ý lấy từ `verified_questions`.
- `answer_from_previous`: ví dụ "giải thích thêm", "vì sao tháng 1 giảm". Bỏ qua SQL, gọi lại insight với facts và preview của turn trước.
- `unsupported`: chỉ số chưa được định nghĩa, hoặc vượt giới hạn. Trả lời kèm lý do và gợi ý.

**Candidate schema** (rút gọn từ `CANDIDATE_SCHEMA`; mọi key đều required, `additionalProperties: false`):
```
outcome: query|conversation|answer_from_previous|unsupported, reason, suggestions[],
source_ids[], shape: aggregate|breakdown|time_trend|distinct_values|unclear,
selection[dimension ids ≤4], recipe (metric id) | metrics[2-4], recipe_alternatives[], recipe_stated,
filters[{field, values_mentioned[], min, max}],
time_range{kind: none|last_n_days|between, days, start, end, field, field_stated},
answer_request{need: none|describe|compare|explain, ask}, language (BCP47)
```

**Các luật chính trong instruction** (lấy từ `_INTERPRET_INSTRUCTION`):
- Không bao giờ viết SQL, công thức hay tên bảng. Chỉ được dùng các id có trong danh sách.
- Nếu có nhiều metric cùng khớp: để `recipe=""` và liệt kê chúng trong `recipe_alternatives`.
- Metric chưa được định nghĩa thì trả `unsupported`.
- `values_mentioned` phải chép nguyên văn user viết.
- Instruction chỉ chứa grammar. Kiến thức nghiệp vụ nằm trong catalog. Có test assert rằng instruction không chứa từ nghiệp vụ như "revenue".

**QuerySpec** (đầu vào của validator và compiler):
```
{source_ids[1-3], contract_version, shape, selection[≤4], recipe | metrics[2-4],
 filters[{field, operator ∈ =,!=,IN,NOT IN,>,>=,<,<=,CONTAINS, values[1-20]}≤8],
 time_range{field, kind: last_n_days(days 1-366, tính đến max_date) | between(start,end ≤366d)}, limit≤2000}
```

**Hỏi lại khi** (giống `_advance`):
- Không nêu nguồn và có nhiều hơn một nguồn. Lựa chọn: từng nguồn, hoặc "So sánh cả 2".
- Metric mơ hồ: dùng `recipe_alternatives`. Nếu các metric thuộc cùng một variant_group thì chọn sẵn một cái, hiện nút chuyển cách tính và không hỏi.
- Thiếu khoảng thời gian. Lựa chọn: 7, 30 hoặc 90 ngày tính đến max_date, toàn bộ, hoặc Khác.
- Giá trị filter không khớp chính xác. Gợi ý gần đúng từ vocabulary, kèm "Khác…".
- Field nằm trong `policy.ask_when_missing`.

Form có dạng `{message, fields:[{id, label, kind: single_choice|multi_choice, required, choices[{id,label,description}], allow_other, default}]}`. Câu trả lời được POST lên `/answer` rồi quay lại bước [5]. Phiên hỏi lại hết hạn sau 30 phút.

**Validator** (một phần của `validate_query_spec`, áp dụng cho Postgres):
- Không chấp nhận key lạ.
- `contract_version` phải đúng bản hiện tại.
- `source_id` phải tồn tại.
- `shape` hợp lệ; `selection` không trùng và ≤ 4.
- Không được đặt đồng thời `recipe` và `metrics`.
- Operator phải nằm trong `allowed_operators` của field; số lượng values đúng với loại operator.
- Khoảng thời gian ≤ 366 ngày.
- Không trộn ngày cohort với ngày event trên cùng một trục.
- Các metric phải dùng cùng `period_field`.
- `limit` nằm trong 1–2000.

**Compiler:**
- Chỉ dùng identifier lấy từ whitelist của catalog, quote bằng `psycopg.sql.Identifier`.
- Mọi literal đều là tham số `%(p0)s`.
- `ep.x` biên dịch thành `(ep->>'x')`. Có `cast` thì dùng `analytics.try_numeric(...)` (tương đương SAFE_CAST).
- Field mapping theo nguồn được áp dụng trước khi biên dịch, ví dụ với `cosmetics_shop` thì `ep.order_id` → `session_id`.
- Event role biên dịch thành `event_name = ANY(%(p)s)`, cộng thêm `event_conditions`.
- Công thức theo loại metric:
  - simple: `count(*)`, `count(DISTINCT user_id)`, `sum`, `avg`, `max`, `count(DISTINCT field)`.
  - ratio: `num / NULLIF(den, 0)`.
  - cohort: CTE neo theo `first_seen_date`.
  - per_day: CTE theo ngày rồi lấy avg hoặc sum.
  - Nhiều metric: mỗi metric một CTE, JOIN theo các cột group.
  - Nhiều nguồn: tự thêm `source_id` vào group by.
- Kết quả cuối gồm `compiled_sql` (dạng hiển thị, đã điền tham số) và `params`.

**Soát dữ liệu (fail closed):**
- Event của role không có trong vocabulary của nguồn → từ chối kèm lý do, ví dụ "Olist không ghi nhận add-to-cart".
- Giá trị filter chưa từng xuất hiện → hỏi lại.
- Một nguồn ghi ≥ 2 spelling của cùng một role có `alternatives` → cảnh báo có thể đếm trùng.
- Khi hỏi nhiều metric, metric mà nguồn không có thì trả `NULL` và đưa vào `unavailable_metrics`, không trả 0.
- Cảnh báo cho các trường hợp: 0 dòng (kèm khoảng ngày nguồn thực sự có dữ liệu), mẫu nhỏ hơn `min_sample`, chạm limit, trộn tiền tệ khi so sánh USD với BRL.

### 2.4 Luồng nhận xét và tạo insight từ kết quả SQL
1. **Facts tính bằng code** trên toàn bộ kết quả, không để AI tự tính:
   - `row_count`, `partial`.
   - `total` (chỉ với aggregation cộng dồn được; có cờ `total_complete`).
   - `highest` / `lowest` kèm nhãn dòng, `average`, `share_percent` của top dòng.
   - `change_over_time` cho mỗi series (đầu → cuối, % thay đổi, đỉnh và đáy), tối đa 10 series.
   - `difference` khi kết quả có 2 dòng hoặc so sánh 2 nguồn.
   - Mỗi fact có một id, ví dụ `f_total_revenue`.
2. **Preview cho model:** tối đa 100 dòng. Breakdown nhiều hơn 100 dòng thì gửi top 99 theo metric chính cộng một dòng "Others" (chỉ khi metric cộng dồn được). Cell bị cắt ở 200 ký tự.
3. **Call #2** gửi lên `{question, language, interpretation, columns+units, facts, preview, warnings, unavailable_metrics, answer_request}` và nhận JSON schema:
   ```
   {headline, body: [≤5 câu], caveats[], follow_ups[≤3]}
   ```
   Model **không viết số trực tiếp**. Mọi con số phải đi qua placeholder `[[f_id]]`, server sẽ thay bằng giá trị đã format theo unit và locale. Cơ chế này mượn từ writer của Analytic mode trong DIego. Placeholder không tồn tại thì câu đó bị bỏ; còn lại dưới 1 câu hợp lệ thì gọi lại 1 lần, vẫn hỏng thì chỉ trả bảng kèm một câu tóm tắt sinh bằng template.
4. **Luật trong instruction:**
   - Chỉ dùng facts.
   - NULL không phải 0.
   - `total_complete=false` nghĩa là chỉ là tổng con.
   - Phải nêu nguồn và khoảng ngày.
   - Trả lời đúng `answer_request.need`: describe, compare hoặc explain. Với explain, chỉ được nêu giả thuyết dựa trên chiều dữ liệu đã có và gợi ý câu hỏi để kiểm chứng.
5. **Hỏi tiếp** (`answer_from_previous`) dùng lại facts và preview của turn trước, không chạy SQL lại. "Xem theo tháng thay vì tuần" là outcome `query` mới, kế thừa spec của turn trước.

### 2.5 Lưu trữ (`app.*`)
- `conversations (id, title, created_at, updated_at)`
- `turns (id, conversation_id, question, status, candidate, query_spec, compiled_sql, params, preview_rows ≤100, facts, insight, warnings, clarification, model, contract_version, error, created_at)`. Mở lại hội thoại **không** tự chạy lại query; nút "Tải full kết quả" chạy lại `compiled_sql` (tối đa 2000 dòng hoặc xuất CSV).
- `runs`, `run_steps (run_id, step, status, started_at, ms, note)` dùng cho SSE và để xem lại tiến trình.
- `feedback (turn_id, rating up|down, comment ≤1000)`.
- `model_connection (provider, encrypted_api_key, allowed_models[], default_model)`. V1 là single-tenant, không có auth hay phân quyền (đã ghi rõ ở phần bỏ qua).
- `llm_usage (run_id, call_name, model, input/cached/output tokens, ms)`. Không lưu nội dung prompt.

### 2.6 API
- `POST /api/questions` với body `{conversation_id?, question, model, source_ids?}` trả `{run_id, turn_id}`.
- `GET /api/runs/{id}/stream`: SSE, các event là `step` và `result`. Client chỉ cần một luồng (không poll song song như DIego, vì chỉ có một worker).
- `POST /api/turns/{id}/answer` (trả lời form hỏi lại), `/retry`, `/cancel`, `/feedback`, `/full-result`, `/variant`.
- `GET|DELETE /api/conversations[/{id}]`.
- `GET|PUT /api/model-connection`, `POST /api/model-connection/discover` (liệt kê các model Gemini mà key dùng được).
- `GET /api/catalog/summary` (dùng cho drawer "Texa biết gì"), `GET /api/sources`.

Câu hỏi chạy bằng `asyncio` background task ngay trong process API. Không dùng Celery hay Redis: một user dev không cần queue.

---

## 3. UI/UX (`web/`, React 19 + Vite + TypeScript + Tailwind)

**Layout full-screen:**
```
┌──────────────┬──────────────────────────────────────────────────────────────┐
│ ☰ Texa       │  Top bar: [Nguồn: Tất cả ▾]   [Gemini · gemini-x-flash ▾]  ⚙   │
│ + Chat mới   ├──────────────────────────────────────────────────────────────┤
│ Hôm nay      │                       message list                           │
│  • Doanh thu…│                                                              │
│ Tuần trước   │                                                              │
│  • …         │  ┌─────────────────────────────────────────────────────────┐ │
│ (thu gọn được│  │ Hỏi Texa về dữ liệu…                         [Gửi/Stop] │ │
│  trên mobile)│  └─────────────────────────────────────────────────────────┘ │
└──────────────┴──────────────────────────────────────────────────────────────┘
```

**Luồng màn hình:**
1. **Trạng thái rỗng:** lời chào; một thẻ cho mỗi nguồn (tên, khoảng ngày có dữ liệu, số user và event); 6 câu hỏi mẫu dạng chip lấy từ `verified_questions`. Bấm chip là gửi ngay.
2. **Đang chạy:** khối tiến trình thu gọn được. Các bước gồm "Đọc ngữ cảnh → Chọn định nghĩa → Hiểu câu hỏi → Kiểm tra → Dựng SQL → Soát dữ liệu → Chạy truy vấn → Viết nhận xét", mỗi bước có icon trạng thái, thời gian và ghi chú, ví dụ "1.2M dòng quét". Có nút **Dừng**.
3. **Hỏi lại:** một card màu vàng có message và các nhóm nút toggle (chọn một) hoặc checkbox (chọn nhiều). "Khác…" mở một ô nhập. Nút Gửi bị khóa đến khi chọn đủ các field required. Có nút Hủy.
4. **Từ chối:** một card màu đỏ nhạt nêu lý do và 2–3 chip câu hỏi làm được.
5. **Kết quả:**
   - Dòng "Texa hiểu là…" hiển thị các chip: metric · chia theo · filter · khoảng ngày · nguồn. Nếu metric thuộc một variant group thì có dropdown "Cách tính".
   - **Insight** (headline in đậm, 3–5 câu, các số được highlight).
   - Badge cảnh báo hoặc caveat.
   - Tab **Bảng**: phân trang, preview 100 dòng, format theo unit (%, tiền kèm mã tiền tệ), hiện "Đang xem 100/N dòng", có nút "Tải full" và "Tải CSV".
   - Tab **SQL**: code highlight (đọc được), nút Copy, hiện kèm params.
   - Chip câu hỏi tiếp theo.
   - 👍 / 👎. Bấm 👎 thì mở ô nhập góp ý.
6. **Lỗi:** thông báo theo mã lỗi (`MODEL_OUTPUT_INVALID`, `QUOTA`, `TIMEOUT`, `DB_ERROR`) kèm nút **Thử lại** hoặc **Diễn đạt lại**.

**Chọn provider và model:**
- Dropdown model ở top bar chỉ liệt kê `allowed_models`, mặc định là `default_model`, và nhớ lựa chọn trong localStorage.
- **⚙ Cài đặt** (modal):
  - Provider: v1 chỉ có Gemini; OpenAI và Claude hiện ở trạng thái "sắp có".
  - API key: ô password; khi đã lưu thì hiện "Đã lưu an toàn – nhập key mới để thay".
  - "Kiểm tra & tải danh sách model" gọi `/discover`.
  - Multi-select các model được phép, cùng một model mặc định.
  - Ngân sách: số token output tối đa cho mỗi call, và token mỗi ngày (0 = không giới hạn).
  - Ngôn ngữ trả lời: theo câu hỏi, hoặc ép vi / en.
- Thiếu key thì composer bị khóa và có banner "Thêm Gemini API key để bắt đầu".

**Phụ trợ:**
- Drawer "Texa biết gì": danh sách metric và dimension của catalog kèm mô tả, có ô tìm kiếm. Bấm vào một mục để chèn vào ô hỏi.
- Phím tắt: Enter gửi, Shift+Enter xuống dòng, ⌘K tạo chat mới.
- Hỗ trợ dark mode; responsive (sidebar thành drawer khi màn hình hẹp hơn 768px).

---

## 4. Cấu trúc repo và các mốc

```
Final/
  PLAN.md  README.md  docker-compose.yml  .env.example
  data/landing/<source>/            (gitignored)
  pipeline/dags/{ingest_cosmetics_shop,ingest_olist_marketplace,refresh_metadata}.py
  pipeline/sql/{00_init.sql, cosmetics_shop/, olist_marketplace/, mart/, quality/}
  catalog/ecommerce.yaml
  backend/texa/*.py   backend/tests/{test_validate,test_compile,test_facts,test_insight}.py
  backend/eval/{golden.yaml, run_golden.py}
  web/src/{App.tsx, api.ts, components/{Sidebar,TopBar,Composer,Message,RunProgress,ClarifyForm,ResultCard,SettingsModal,CatalogDrawer}.tsx}
```

| Mốc | Nội dung | Xong khi |
|---|---|---|
| M0 | Scaffold, compose, `00_init.sql` (schema, role, `try_numeric`), copy PLAN.md | `docker compose up` chạy Postgres, Airflow UI và API `/health` |
| M1 | 2 DAG ingest + quality checks + `refresh_metadata` | `event_activity` có cả 2 nguồn, quality checks pass, `source_registry` và `vocabulary` đã có dữ liệu |
| M2 | `catalog/ecommerce.yaml` + `catalog.py` (validate/publish/coverage) | `texa catalog publish` OK; báo cáo coverage thấy Olist thiếu `add_to_cart` |
| M3 | validate, compile, sanity, execute, facts, chạy được **không cần LLM** (`texa query spec.json`) | Test compiler: số liệu khớp với SQL viết tay cho khoảng 15 metric |
| M4 | `llm.py` (Gemini), context/shortlist, interpret, clarify, insight | CLI `texa ask "doanh thu theo danh mục tháng 1/2020"` ra được insight |
| M5 | API, runs/SSE, lưu trữ, feedback, model-connection | Chạy được full luồng qua curl/SSE |
| M6 | UI như mục 3 | Demo end-to-end trên trình duyệt |
| M7 | Golden eval khoảng 60 câu (vi+en: aggregate, breakdown, trend, so sánh nguồn, hỏi lại, từ chối, hỏi tiếp) | `run_golden.py` đạt ≥ 90% outcome và spec khớp, mỗi câu chạy 3 lượt |

## 5. Verification
- `pytest backend/tests`:
  - validator: mỗi luật một case pass và một case fail;
  - compiler: snapshot SQL, và chạy trên DB seed nhỏ để so số với SQL viết tay;
  - facts: total, share, change;
  - insight: thay placeholder, xử lý placeholder không tồn tại.
- `run_golden.py --runs 3`: so outcome, recipe, selection, filters, time_range với kỳ vọng; in ra accuracy và các case không ổn định.
- E2E thủ công, qua UI:
  - "Doanh thu theo danh mục tháng 12/2019 của cosmetics shop" → bảng, insight và SQL.
  - "tỉ lệ chuyển đổi" → hiện chọn cách tính / hỏi nguồn.
  - "add to cart của Olist" → từ chối có lý do.
  - "so sánh AOV 2 nguồn" → cảnh báo trộn tiền tệ.
  - "vì sao giảm?" → hỏi tiếp không chạy SQL.
  - 👎 kèm góp ý → có dòng trong `app.feedback`.

## 6. Cố ý bỏ khỏi v1 (thêm khi cần)
- Chart và Analytic mode: thêm khi phần text-to-SQL đã đạt golden ≥ 90%.
- OpenAI / Claude / Ollama: chỉ cần thêm một nhánh trong `llm.py`.
- Auth và phân quyền theo nguồn: chưa cần vì hệ thống single-user.
- Redis, Celery, prompt cache tường minh: Gemini đã có cache ngầm (implicit), DIego cũng đã chuyển sang dùng implicit.
- UI chỉnh catalog, AI gợi ý mapping: catalog được sửa qua YAML và git.
- Query plan nhiều bước (rank / semi_join) và expressions giữa các metric.
