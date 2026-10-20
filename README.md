# Texa

Texa là một hệ thống chat Text-to-SQL chạy trên semantic catalog, dựng lại theo cách DIego của Inwave hoạt động. Bạn đặt câu hỏi bằng ngôn ngữ tự nhiên; model chỉ chọn id trong catalog để tạo **QuerySpec**. Sau đó Python validate spec, compile ra SQL có tham số, chạy SQL bằng role chỉ đọc và tính sẵn các con số (facts). Cuối cùng model viết nhận xét, nhưng mọi con số trong đó đều phải trỏ tới placeholder `[[fact_id]]` và server sẽ thay giá trị thật vào.

Thiết kế chi tiết nằm ở [PLAN.md](PLAN.md).

```
data/landing  ──Airflow ETL──►  analytics.event_activity (1 bảng thống nhất, 2 nguồn)
                                analytics.source_registry / vocabulary
catalog/ecommerce.yaml ──publish──► app.catalog_versions
web (React)  ◄──SSE──  api (FastAPI): context → interpret (LLM) → clarify → validate → check data
                                       → compile SQL → run (read-only) → facts → insight (LLM)
```

## Chạy nhanh (dev)

TEXA dùng cổng riêng, tách khỏi Inwave và DI Platform:

| Dịch vụ | Cổng trên máy |
|---|---|
| Web (Docker, Vite dev/preview) | `15173` |
| API | `18000` |
| Airflow | `18080` |
| PostgreSQL | `15432` |

Proxy dev trỏ tới API `18000`; Vite sẽ báo lỗi nếu cổng `15173` đã được dùng. Các cổng nội bộ Docker vẫn giữ nguyên.

```bash
cp .env.example .env
docker compose up -d postgres airflow
```

**1. Nạp dữ liệu.** Nạp tỷ giá trước, rồi tới hai cửa hàng (bước nạp cửa hàng dùng tỷ giá để tính `revenue_usd`). Có hai cách:

- **Qua Airflow:** mở Airflow tại http://localhost:18080 (user `admin`; mật khẩu nằm trong `docker compose logs airflow | grep password`), trigger DAG `ingest_fx_rates`, rồi `ingest_olist_marketplace` và `ingest_cosmetics_shop`.
- **Không qua Airflow:** chạy cùng các bước đó trực tiếp:

```bash
cd pipeline && uv run --python 3.12 --with 'psycopg[binary]' python -m texa_etl.run fx_rates
```

```bash
cd pipeline && uv run --python 3.12 --with 'psycopg[binary]' python -m texa_etl.run olist_marketplace
```

Tỷ giá lấy từ chuỗi [FRED DEXBZUS](https://fred.stlouisfed.org/series/DEXBZUS) (BRL cho 1 USD, hằng ngày, không cần key). Mỗi sự kiện được quy đổi theo tỷ giá đúng ngày của nó (ngày nghỉ dùng ngày giao dịch gần nhất trước đó, trong vòng 7 ngày). `load_mart` tính USD ngay lúc INSERT; Cosmetics vốn dùng USD nên `revenue_usd = revenue`.

Nếu dữ liệu cửa hàng đã có trong mart, dùng `refresh_revenue_usd` để tính lại USD sau khi nạp tỷ giá. Bước này chỉ cập nhật giá trị thay đổi, không xóa và nạp lại toàn bộ sự kiện như `load_mart`. Chạy từ thư mục `Final`:

```bash
(
  cd pipeline &&
  uv run --python 3.12 --with 'psycopg[binary]' python -m texa_etl.run fx_rates &&
  uv run --python 3.12 --with 'psycopg[binary]' python -m texa_etl.run olist_marketplace refresh_revenue_usd refresh_metadata &&
  uv run --python 3.12 --with 'psycopg[binary]' python -m texa_etl.run cosmetics_shop refresh_revenue_usd refresh_metadata
)
```

`refresh_metadata` vẫn quét dữ liệu để cập nhật vocabulary nên có thể mất thời gian với Cosmetics. Nếu dừng bằng Ctrl+C, bước đang chạy sẽ rollback; những bước trước đã commit vẫn được giữ lại. `KeyboardInterrupt` trong log là do thao tác ngắt này.

Không cần Kaggle API key: bước `download` tự tải dataset public. Nếu muốn tải tay thì đặt file CSV vào `data/landing/<source_id>/`.

**2. Publish catalog.** Lệnh `coverage` cho biết mỗi nguồn trả lời được những metric nào.

```bash
cd backend && uv sync && uv run texa catalog publish && uv run texa catalog coverage
```

**3. Chạy API và web.**

```bash
cd backend && uv run uvicorn texa.main:app --port 18000
```

```bash
cd web && npm install && npm run dev
```

Mở http://localhost:15173, bấm ⚙ **Cài đặt**, chọn provider (**Google Gemini**, **Anthropic Claude** hoặc **OpenAI**), nhập API key, bấm "Kiểm tra key & tải danh sách model", chọn model rồi Lưu.

**Gateway của tổ chức:** chọn provider có API giống gateway (đa số gateway như LiteLLM, OpenRouter, Azure OpenAI, vLLM… tương thích OpenAI), điền key do gateway cấp và **Base URL** của gateway (ví dụ `https://litellm.congty.vn/v1`). Nếu gateway không hỗ trợ `json_schema`, Texa tự chuyển sang JSON mode và vẫn kiểm tra kết quả theo schema. Cũng có thể đặt sẵn trong `.env`: `OPENAI_API_KEY` / `ANTHROPIC_API_KEY` / `GEMINI_API_KEY`, cùng `TEXA_BASE_URL` và `TEXA_DEFAULT_MODEL`.

Muốn chạy cả `api` lẫn `web` bằng Docker thì dùng `docker compose up -d`, web sẽ ở http://localhost:15173. Trong trường hợp này hãy đặt `TEXA_SECRET_KEY` trong `.env`; key này dùng để mã hóa API key đã lưu.

## Con số trong câu trả lời

Model không bao giờ tự gõ con số. Mỗi số trong câu trả lời có một trong ba nguồn, và giao diện đánh dấu khác nhau:

| Đánh dấu | Nguồn |
|---|---|
| Tô vàng | Lấy thẳng từ kết quả SQL |
| Tô vàng + gạch chấm (bấm để xem công thức) | Texa tính từ các số trên: model viết công thức (`f_a / u_rate`), Python tính (`backend/texa/derive.py`) |
| Gạch chân | Số bạn đưa ra trong câu hỏi, ví dụ một tỷ giá. Số model "nhớ" mà bạn chưa gõ sẽ bị loại |

Vì vậy các câu như "quy đổi theo tỷ giá 5,2", "tháng 1 tăng bao nhiêu % so với tháng 12" được trả lời; còn "quy đổi sang euro" khi chưa có tỷ giá euro thì Texa hỏi lại tỷ giá thay vì đoán.

## Kiểm thử

```bash
cd backend && uv run pytest
```

Cần đã nạp warehouse. Bộ test gồm:
- validator;
- facts;
- placeholder của insight;
- kiểm tra prompt không chứa từ nghiệp vụ;
- so số liệu của compiler với SQL viết tay;
- luồng hội thoại với model giả.

Golden eval chạy với model thật (cần đã kết nối model trong Cài đặt, hoặc đặt một trong các key ở `.env`):

```bash
cd backend && uv run python eval/run_golden.py --runs 3
```

Bộ eval có 62 câu tiếng Việt và tiếng Anh. Lệnh in ra accuracy và các case không ổn định; mặc định fail nếu accuracy dưới 90%.

## Bố cục

| Đường dẫn | Nội dung |
|---|---|
| `pipeline/texa_etl/run.py` | Các bước ETL: download → raw → staging → mart → metadata → quality |
| `pipeline/sql/` | SQL khởi tạo, staging cho từng nguồn, mart thống nhất, quality checks |
| `pipeline/dags/texa_ingest.py` | Mỗi nguồn một DAG |
| `catalog/ecommerce.yaml` | Semantic catalog: event roles, dimensions, metrics, variant groups, glossary… |
| `backend/texa/` | `catalog`, `spec` (validator), `sanity`, `compile`, `execute`, `facts`, `interpret`, `clarify`, `insight`, `llm`, `answer`, `main` |
| `backend/eval/` | Golden questions và runner |
| `web/src/` | UI chat full-screen |
