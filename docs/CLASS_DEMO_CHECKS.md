# Kiểm thử demo lớp học — 04/11/2026

Tách hai mục tiêu: E2E kiểm tra website hoạt động; benchmark model thật kiểm tra hiểu câu hỏi và kết quả truy vấn. E2E dùng model giả không chứng minh độ chính xác của LLM.

## Website và dùng đồng thời

Playwright Chromium: **11/11 test đạt**, đã chạy lại sau sửa memory. Bao phủ câu hỏi → SSE → SQL/kết quả; làm rõ rồi chạy; hỏi tiếp sau một câu xã giao có memory; lỗi model rồi retry; hủy; cài đặt chỉ đọc; lịch sử riêng giữa hai browser contexts; chặn đổi cấu hình; reload lịch sử; chuyển chat khi câu cũ đang chạy; **8 phiên browser hỏi đồng thời**, có kết quả và conversation riêng.

Provider của vòng này là scripted, còn UI/API/SSE/compiler/PostgreSQL là thật. Đây là smoke test đồng thời 8 phiên, chưa phải kiểm thử tải với model thật hoặc cam kết chịu tải cho cả lớp. Screenshot local: `.runtime/e2e-artifacts/demo-success.png`.

## Kết quả model thật ban đầu

Cùng `gpt-6-luna`, cùng gateway, schema, định nghĩa metric và fixture v2 96 events; chấm 41 câu **dev**, một lần chạy mỗi phương pháp. Gold và scorer không thay đổi.

| Phương pháp | Kết quả truy vấn đúng | Trung vị | p95 |
|---|---:|---:|---:|
| Direct LLM → SQL | 40/41 (97,6%) | 5,925 giây | 7,989 giây |
| Texa trước điều chỉnh prompt | 37/41 (90,2%) | 9,986 giây | 13,055 giây |

SQL của cả hai bên đều thực thi được ở 41/41 câu. Bốn lỗi Texa đều thêm cột/chia nhóm khi câu hỏi chỉ yêu cầu lọc; kết quả vì thế không khớp cấu trúc đáp án chuẩn. Baseline sai một câu do trả theo ngày thay vì tổng trong khoảng ngày. Texa có thêm bước viết insight nên latency không chỉ là thời gian sinh SQL.

Vòng hội thoại ban đầu của Texa chỉ đạt **1/6 hội thoại dev hoàn toàn đúng**. Chấm thành công toàn hội thoại đòi hỏi mọi lượt đúng action, các slot được khai báo, kết quả và tham chiếu theo quy tắc evaluator. Không được đổi chỉ số này thành tỷ lệ “nhớ đúng” đơn thuần. Runner đã được bổ sung mã lỗi/trạng thái để chẩn đoán những lượt lỗi hoặc từ chối.

Đây là kết quả thăm dò trên dev; chưa chạy test 63 câu, chưa chạy đủ F/M6/M0/C0 nhiều seed theo protocol ablation. **Vòng đầu không chứng minh Texa tốt hơn baseline**. Prompt sau đó được bổ sung quy tắc chung phân biệt filter và breakdown; cần báo cáo lượt chạy sau sửa riêng, không thay thế kết quả ban đầu.

Raw JSONL giữ ở `backend/eval/results/` (Git ignored): `luna-direct-dev-20261104.jsonl`, `luna-texa-dev-20261104-migrated.jsonl`, `luna-texa-dialogue-dev-20261104.jsonl`. PostgreSQL local: 16.2; chưa xác nhận Docker PostgreSQL 17 trong vòng này.

## Chẩn đoán, sửa và chạy lại trên dev

Không sửa câu hỏi, SQL gold hoặc scorer. Đã bổ sung hướng dẫn chung: điều kiện lọc không tự tạo breakdown; ngày/khoảng ngày không tự tạo trend. Sửa memory để nhận “kết quả đó”, yêu cầu thêm điều kiện, và tham chiếu rõ “câu đầu / câu thứ N / kết quả thứ N”. Câu hỏi và kết quả có cách đếm riêng; câu thất bại hoặc dữ liệu cũ không được tự thay thế bằng một kết quả khác. Nhiều tham chiếu hoặc tham chiếu không hợp lệ vẫn yêu cầu làm rõ.

| Vòng chạy lại | Kết quả | Artifact JSONL |
|---|---:|---|
| Texa sau hướng dẫn filter/breakdown, trước thay đổi date/memory | 41/41 câu đơn dev (100%); p50 8,967 giây, p95 11,804 giây | `luna-texa-dev-20261104-filter-prompt.jsonl` |
| Hội thoại sau hướng dẫn filter, có log chẩn đoán | 3/6 hội thoại dev | `luna-texa-dialogue-dev-20261104-diagnostic.jsonl` |
| Hội thoại sau hướng dẫn date và sửa memory | 6/6 hội thoại dev; 19/19 lượt đạt tiêu chí, gồm một hội thoại dài 8 lượt | `luna-texa-dialogue-dev-20261104-memory-fix.jsonl` |

Các con số sau tinh chỉnh là **development checks**, không thay thế vòng ban đầu và không phải so sánh công bằng trên tập test chưa xem. Không gán toàn bộ thay đổi điểm cho một component: model có biến thiên giữa các lần gọi. Muốn kết luận hiệu quả kiến trúc phải đóng băng phiên bản, chạy test và ablation nhiều lượt theo protocol.

Gateway báo giá input $0,10/triệu token, output $0,50/triệu token; wrapper không trừ cache discount. Tổng ledger kiểm tra: 292 lượt provider thành công có usage, 459.058 input tokens, 34.731 output tokens; chi phí ước tính **$0,06328**, cộng **$0,00774** dự trữ giữ lại cho lượt lỗi/không chắc chắn. Tổng bảo thủ dưới $0,08, thấp hơn trần $10. Chưa đối soát hóa đơn tài khoản gateway. Các thông tin này chỉ nói về vòng kiểm thử, không đặt giới hạn chi tiêu cho website khi công khai.

Backend regression sau sửa memory: **164 passed, 23 skipped**, với product/metadata/shared-session PostgreSQL tests bật. Các skip không được tính là test đạt. Các bộ test cần ablation fixture hoặc warehouse cũ được giữ riêng, không nạp các fixture đó đè lên pilot trong vòng kiểm tra này. Frontend build và lint đạt.

## Chạy website cho nhiều người

Chạy một API worker, web và API cùng origin qua reverse proxy. RUNS/SSE hiện nằm trong bộ nhớ của worker; chưa hỗ trợ nhiều worker/replica. Docker nginx có sẵn proxy `/api/` và tắt buffering SSE. Docker API mặc định dùng catalog sản phẩm; database đã tồn tại vẫn cần publish catalog sản phẩm.

Đặt cấu hình phía server qua secret store hoặc file `.env` được Git bỏ qua:

```dotenv
TEXA_SHARED_DEMO=1
TEXA_ADMIN_TOKEN=<chuỗi ngẫu nhiên ít nhất 24 ký tự>
TEXA_COOKIE_SECURE=1
TEXA_DEFAULT_MODEL=gpt-6-luna
TEXA_BASE_URL=<gateway tương thích OpenAI, kết thúc /v1>
OPENAI_API_KEY=<key của người tổ chức>
```

`TEXA_COOKIE_SECURE=1` yêu cầu HTTPS; khi chạy localhost HTTP để kiểm thử dùng `0`. Không đưa key hoặc admin token vào frontend. Nếu DB đã có model connection thì cấu hình đó được ưu tiên hơn biến môi trường; người tổ chức cần kiểm tra model thực tế trong bootstrap. API quản trị yêu cầu `Authorization: Bearer <TEXA_ADMIN_TOKEN>` khi bật shared mode.

Mỗi trình duyệt nhận cookie HttpOnly; server lưu hash để tách lịch sử. Người tham gia chỉ xem model đang dùng; không đổi/xóa cấu hình hoặc xem usage tổng. Đây là phiên ẩn danh: người dùng chung một browser profile sẽ chung lịch sử; xóa cookie mất quyền truy cập lịch sử cũ. Không phải hệ thống đăng nhập/tài khoản.

Khi đưa lên máy chủ, chỉ công khai web qua HTTPS; giữ DB và API nội bộ. Cấu hình giới hạn chi phí tại gateway cho buổi demo. Giới hạn $10 của script đánh giá dưới đây không tự áp dụng cho website.

## Chạy kiểm thử

Backend mặc định chạy offline và bỏ qua các test cần DB:

```sh
backend/.venv/bin/python -m pytest backend/tests -q
```

E2E cần PostgreSQL riêng tên `texa_benchmark`, fixture **pilot 12 events** và catalog sản phẩm đã publish. Không dùng DB demo thật; fixture v2/ablation có kết quả khác. Dùng `backend/eval/setup_benchmark.py` để nạp pilot, chỉ sau khi mọi benchmark khác đã kết thúc.

```sh
export TEXA_DB_DSN='postgresql://OWNER@127.0.0.1:PORT/texa_benchmark'
export TEXA_READER_DSN='postgresql://texa_reader:PASSWORD@127.0.0.1:PORT/texa_benchmark'
export TEXA_E2E_TEST_DSN=1
export TEXA_SHARED_DEMO=1
export TEXA_ADMIN_TOKEN='e2e-only-admin-token-not-a-secret-12345'
export TEXA_COOKIE_SECURE=0
cd web
npm ci
npx playwright install chromium
npm run test:e2e
```

Server E2E chặn toàn bộ provider thật, giữ nguyên API/SSE/compiler/PostgreSQL và dùng phản hồi model có kịch bản. Không dùng entry point `tests.e2e_server` để triển khai demo thật. Trace và screenshot được ghi dưới `.runtime/e2e-artifacts` và không commit.

## Kiểm tra model thật có giới hạn chi phí

`backend/eval/run_gateway_check.py` đọc credentials JSON owner-only dưới `.runtime`, lấy đơn giá gateway, dự trữ chi phí trước mỗi lượt gọi và ghi ledger dùng chung có lock. File chứa `model`, `base_url`, `api_key`, `max_usd`; không commit hoặc in file ra log. Script không lưu connection này vào DB. Chi phí là ước tính theo usage/đơn giá gateway, không phải hóa đơn đã đối soát.

```sh
backend/.venv/bin/python backend/eval/run_gateway_check.py \
  --credentials .runtime/class-demo-gateway.json \
  --method texa --dataset-dir data/benchmark/v2 --split dev \
  --output backend/eval/results/local-dev.jsonl
```

Đặt thêm `TEXA_BENCHMARK_DSN` tới reader của DB benchmark, nạp fixture v2 trước vòng này. Cùng model/dataset cho direct baseline và Texa. Không thay đổi fixture trong khi runner đang chạy. Dev dùng để phát hiện lỗi; không coi đây là kết quả cuối trên test hoặc bằng chứng ablation.
