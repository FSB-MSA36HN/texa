# Texa

Texa là trợ lý hỏi đáp dữ liệu hội thoại dành cho **PM/PO của một sản phẩm thương mại điện tử**. Người dùng hỏi về hành vi và kết quả sản phẩm; LLM chọn định nghĩa trong semantic catalog để tạo QuerySpec, Python validate và compile SQL PostgreSQL, sau đó câu trả lời sử dụng facts từ dữ liệu.

Scope hiện tại đang được triển khai theo [kế hoạch refinement](PLAN_REFINEMENT_EVENT_CONVERSATIONAL_QA.md): một dataset event mỗi câu hỏi, 8 metric, nested object có giới hạn; memory có cấu trúc và đánh giá kết quả thực thi. Không phải nền tảng tích hợp mọi database hoặc báo cáo tài chính. PM/PO là persona giả thuyết cần kiểm chứng bằng task walkthrough; quản lý là nhóm người dùng phụ.

Catalog bản sản phẩm là `catalog/product_events.yaml`; `catalog/ecommerce.yaml` giữ để chạy regression cũ. Chỉ catalog được publish mới có hiệu lực trong DB đã tồn tại. Những giới hạn và lệnh kiểm tra cập nhật nằm trong [scope contract](docs/PRODUCT_SCOPE.md).

Thiết kế chi tiết nằm ở [PLAN.md](PLAN.md).

```
event snapshot ──metadata refresh──► analytics.event_activity (một nguồn mỗi câu hỏi)
                                    source_registry / nested vocabulary
catalog/product_events.yaml ──publish──► app.catalog_versions
web (React) ◄──SSE── api: structured memory → interpret → clarify → validate
                         → PostgreSQL compiler → read-only run → facts → insight
```

## Bản triển khai hiện tại

Đã bổ sung structured memory, hỗ trợ nested object hai key, source scope và thông tin cách tính trên giao diện. [Trạng thái triển khai và kiểm chứng](docs/IMPLEMENTATION_STATUS.md) phân biệt rõ tính năng đã có với thí nghiệm còn phải chạy. [Benchmark pilot](data/benchmark/README.md) có SQL gold, direct LLM baseline và hội thoại. Đã bắt đầu kiểm tra model thật trên tập dev; kết quả và giới hạn nằm trong [kiểm thử demo lớp học](docs/CLASS_DEMO_CHECKS.md).

## Chạy nhanh (dev)

Các lệnh FX/Olist bên dưới là luồng dữ liệu/regression cũ. Scope sản phẩm dùng Cosmetics hoặc benchmark riêng; không cần nạp Olist để dùng catalog sản phẩm.

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
cd backend && uv sync && uv run texa catalog publish ../catalog/product_events.yaml && uv run texa catalog coverage
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

Bộ eval có **63 case tiếng Việt và tiếng Anh**. Chạy `--runs 3` tạo 189 lượt chấm; lệnh in ra tỷ lệ pass và các case lúc pass, lúc fail. Ngưỡng mặc định là 90%; đây là ngưỡng mục tiêu, không phải kết quả đã đạt.

### Evaluation đối chiếu những gì?

| Lớp kiểm tra | Đối tượng đối chiếu | Phạm vi |
|---|---|---|
| Compiler tests | **Kết quả thực thi** của SQL compiler sinh với SQL tham chiếu viết tay, trên cùng warehouse | Kiểm tra các case tính toán đã viết test; input đã là QuerySpec, không cần model thật |
| Golden eval với model thật | **Status và một số trường của QuerySpec cuối** với kỳ vọng viết tay trong `backend/eval/golden.yaml` | Chỉ chấm các trường `expect` được khai báo và được hàm `score()` hỗ trợ; không so toàn bộ JSON |
| Unit / scripted flow tests | Output và hành vi của module/pipeline với assertions viết sẵn | Kiểm tra validator, facts, placeholder, hỏi lại, từ chối…; không dùng để đo độ chính xác của model thật |

Golden hiện **không so chuỗi SQL**, **không đối chiếu bảng số liệu với đáp án chuẩn**, và **không chấm toàn bộ lời nhận xét**. QuerySpec được chấm là kết quả sau khi Python làm rõ/chuẩn hóa/validate cách hiểu của model, không phải chỉ JSON thô model trả về.

Ví dụ minh họa: nếu `expect` chỉ ghi `status: answered`, `recipe: revenue`, `selection: [event_month]`, thì case chỉ yêu cầu trả lời thành công, dùng metric doanh thu và chia theo tháng. Chọn sai nguồn hoặc sai năm vẫn có thể pass vì nguồn/thời gian chưa được khai báo để chấm. Thêm `source_ids`, `start`, `end` vào `expect` sẽ kiểm tra thêm những phần đó. Bộ chấm hiện chưa kiểm tra trực tiếp `shape`, `limit`, `contract_version`, `time_range.field`, operator của filter hay cấm mọi filter dư. Các kiểm tra hợp lệ của validator là một lớp khác, không thay thế việc đối chiếu với ý định đúng.

Mỗi case được tính pass/fail theo các phép kiểm tra đang triển khai, không cộng điểm lẻ cho từng trường. **Ví dụ giả định** chạy một lượt: 60 case pass, 3 case fail → `60/63 = 95,2%`. Ba case fail là các case bị phát hiện vi phạm ít nhất một điều kiện; log nêu khác biệt cụ thể. Con số này có nghĩa **95,2% case đạt kỳ vọng được kiểm tra trong lần chạy**, không có nghĩa 95,2% mọi số liệu/lời trả lời đều đúng. Xem thêm các giới hạn scoring trong tài liệu chi tiết.

**Câu trả lời ngắn khi thuyết trình/phỏng vấn:** “Texa đánh giá theo lớp: compiler được kiểm tra bằng đối chiếu kết quả thực thi với SQL viết tay; model thật được đánh giá bằng golden cases, so trạng thái và các trường QuerySpec được khai báo trước. Golden chưa so toàn bộ QuerySpec hay kết quả SQL. Điểm là tỷ lệ case đạt các kỳ vọng được kiểm tra.”

Chi tiết: [Evaluation methods](presentation/EVALUATION_METHODS.md), gồm ví dụ chấm từng trường, cách tính điểm, giới hạn và câu hỏi phỏng vấn thường gặp.

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
