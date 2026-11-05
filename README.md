# Texa

Texa là trợ lý hỏi đáp dữ liệu thương mại điện tử cho **PM/PO không chuyên SQL**. LLM hiểu câu hỏi; Python kiểm tra QuerySpec, compile SQL PostgreSQL và lấy kết quả để viết nhận xét có truy vết. Persona chưa được kiểm chứng bằng user study; không cam kết trả lời đúng tuyệt đối.

## Scope hiện tại — 05/11/2026

- Hai nguồn được cấu hình sẵn: **Cosmetics shop và Olist marketplace**. Mỗi câu hỏi dùng **một nguồn**, không cộng hoặc join hai cửa hàng.
- Một engine: PostgreSQL. Catalog sản phẩm: `catalog/product_events.yaml`.
- Tám metric: events, users, sessions, viewers, purchases, buyers, revenue, buyer_conversion_rate. Nguồn phải có dữ liệu phù hợp mới tính được; Olist thiếu sessions và viewers.
- Nested object dưới `ep`/`up`, tối đa hai key, chỉ scalar trong catalog; không expand arrays.
- Không hỗ trợ metric giao trễ/review, order/AOV, retention, FX, suy luận nguyên nhân hay tự chuẩn hóa mọi database. Dữ liệu Olist có các event lifecycle nhưng điều đó không tự bật thêm metric.
- Olist chỉ quan sát khách đã đặt hàng. Buyer/user ratio không phải chuyển đổi visitor thành buyer. Purchases đếm item lines; revenue chỉ cộng giá item mua, loại payment/freight; Olist dùng BRL, Cosmetics dùng USD.

## Tài liệu nên đọc

| Tài liệu | Nội dung |
|---|---|
| [Mục lục tài liệu](docs/README.md) | Điểm vào duy nhất và trạng thái từng tài liệu |
| [Scope](docs/PRODUCT_SCOPE.md) | Người dùng, metric, nguồn và giới hạn |
| [Kiến trúc](docs/ARCHITECTURE.md) | Luồng truy vấn, memory và website dùng chung |
| [Đánh giá](docs/EVALUATION.md) | Baseline, dataset, metric và ablation |
| [Trạng thái triển khai](docs/IMPLEMENTATION_STATUS.md) | Đã có gì, đã kiểm tra gì, còn thiếu gì |
| [Demo và kết quả dev](docs/CLASS_DEMO_CHECKS.md) | Lệnh E2E, vận hành và số liệu có giới hạn |
| [Thuyết trình](presentation/OUTLINE.md) | Dàn ý; script và sơ đồ trong cùng thư mục |

## Chạy local

Tất cả lệnh từ thư mục gốc `Final` trừ khi có `cd`. Cần Docker Desktop, `uv`, Node.js/npm. Cổng dự án: web `15173`, API `18000`, PostgreSQL `15432`, Airflow `18080`.

```sh
test -f .env || cp .env.example .env
# Điền key/model và shared-demo settings nếu cần; không commit .env.
docker compose up -d --wait postgres
docker compose up -d airflow
```

Nếu đã nạp dữ liệu, bỏ qua bước ingest. Nạp mới từng nguồn bằng pipeline được cấu hình sẵn; có thể tốn thời gian/tải nhiều dữ liệu. Lệnh chạy toàn pipeline sẽ dựng lại partition của nguồn tương ứng, không dùng như thao tác refresh nhẹ:

```sh
(
  cd pipeline
  uv run --python 3.12 --with 'psycopg[binary]' python -m texa_etl.run cosmetics_shop
  uv run --python 3.12 --with 'psycopg[binary]' python -m texa_etl.run olist_marketplace
)
```

Pipeline cũ còn tạo cột `revenue_usd`/bảng FX để tương thích regression; catalog sản phẩm chỉ dùng `revenue` theo tiền gốc. Không cần tải tỷ giá để hỏi doanh thu trong scope hiện tại. Không mô tả adapter của hai nguồn này là bộ chuẩn hóa mọi DB.

Publish catalog và chạy API:

```sh
cd backend
uv sync
uv run texa catalog publish ../catalog/product_events.yaml
uv run texa catalog coverage
uv run uvicorn texa.main:app --port 18000
```

Trong terminal khác:

```sh
cd web
npm ci
npm run dev
```

Mở `http://localhost:15173`. Local mặc định cho phép cấu hình model trong Cài đặt; hỗ trợ OpenAI-compatible gateway, Anthropic và Gemini. API key được mã hóa khi lưu DB và không gửi lại trình duyệt. Biến môi trường là fallback nếu DB chưa có model connection. `uv` không tự nạp `.env` khi chạy các lệnh API riêng: cung cấp cấu hình trong môi trường process; `run.sh` và Docker Compose có bước nạp `.env`.

Có thể dùng `./run.sh` sau khi đã chuẩn bị dữ liệu; script khởi động các dịch vụ local, publish catalog, và dừng dịch vụ do script quản lý khi thoát. Với Docker API/web, `docker compose up -d api web`; DB đang có catalog cũ vẫn cần publish bản sản phẩm bằng CLI trong môi trường DB đó.

## Nhiều người dùng một website

Bật `TEXA_SHARED_DEMO=1`, đặt admin token ngẫu nhiên ít nhất 24 ký tự; chỉ công khai web qua HTTPS, API/DB nội bộ. Mỗi browser profile có cookie riêng để tách lịch sử, cấu hình model do người tổ chức quản lý. Một API worker; chưa có đăng nhập hoặc mở rộng nhiều replica. Xem [hướng dẫn demo](docs/CLASS_DEMO_CHECKS.md) trước khi đưa cho lớp dùng.

## Kiểm thử và kết quả

```sh
backend/.venv/bin/python -m pytest backend/tests -q
cd web
npm run build
npm run lint
```

Các test PostgreSQL cần DB riêng `texa_benchmark` và opt-in; không chạy fixture vào warehouse demo. E2E scripted dùng pilot 12 events; v2 và ablation dùng fixture khác. Chi tiết ở [đánh giá](docs/EVALUATION.md).

Kiểm tra mới nhất sau bật Olist: **169 backend test đạt, 23 bỏ qua; 11/11 Playwright E2E đạt**, build/lint đạt. E2E dùng model giả, bao gồm 8 browser sessions đồng thời; không phải kiểm thử tải model thật.

Model thật `gpt-6-luna`, trên synthetic v2 **dev**: baseline 40/41, Texa ban đầu 37/41; sau tinh chỉnh Texa đạt 41/41 câu đơn và 6/6 hội thoại dev ở các vòng riêng. Chưa chạy test độc lập hay đầy đủ ablation nhiều lượt; chưa có bằng chứng Texa vượt baseline hoặc đạt các điểm đó trên Olist. Xem [báo cáo dev](docs/CLASS_DEMO_CHECKS.md).

## Bố cục code

`pipeline/` chứa adapter ETL hai nguồn; `catalog/` chứa định nghĩa nghiệp vụ; `backend/texa/` chứa memory, resolver, validator/compiler, facts, API; `backend/eval/` chứa evaluator; `data/benchmark/` chứa dữ liệu đánh giá synthetic; `web/` là React UI. `catalog/ecommerce.yaml` và `run_golden.py` là công cụ regression cũ, không phải scope hay metric đánh giá chính.
