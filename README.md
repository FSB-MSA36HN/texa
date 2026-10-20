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

**1. Nạp dữ liệu.** Có hai cách:

- **Qua Airflow:** mở Airflow tại http://localhost:18080 (user `admin`; mật khẩu nằm trong `docker compose logs airflow | grep password`) và trigger 2 DAG `ingest_olist_marketplace` và `ingest_cosmetics_shop`.
- **Không qua Airflow:** chạy cùng các bước đó trực tiếp bằng lệnh sau:

```bash
cd pipeline && uv run --python 3.12 --with 'psycopg[binary]' python -m texa_etl.run olist_marketplace
```

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

Bộ eval có 56 câu tiếng Việt và tiếng Anh. Lệnh in ra accuracy và các case không ổn định; mặc định fail nếu accuracy dưới 90%.

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
