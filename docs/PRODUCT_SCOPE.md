# Texa — Product scope

Cập nhật 05/11/2026. Kịch bản thuyết trình: [FINAL_PRESENTATION_SCRIPT](FINAL_PRESENTATION_SCRIPT.md).

## Sản phẩm cho ai, giải quyết gì?

PM/PO không chuyên SQL hỏi dữ liệu thương mại điện tử bằng ngôn ngữ tự nhiên: xem số liệu, đổi kỳ, lọc/chia nhóm và hỏi tiếp. Texa trả bảng, nhận xét, định nghĩa và phạm vi truy vấn để kiểm tra. Persona chưa được xác nhận bằng user study; không cam kết LLM đúng tuyệt đối.

## Phạm vi cố định

- **PostgreSQL; Cosmetics + Olist đã cấu hình sẵn. Mỗi câu hỏi chỉ dùng một nguồn.** Không gộp/join hai nguồn hoặc chuẩn hóa mọi database.
- Event rows do adapter ETL cụ thể tạo; semantic catalog `catalog/product_events.yaml` định nghĩa metric và ánh xạ event. Olist `order_purchased` và Cosmetics `purchase` cùng là purchase item.
- Nested scalar dưới `ep`/`up`: tối đa hai key, chỉ field được khai báo; không expand array. Dữ liệu nguồn nào thiếu field/event thì báo không hỗ trợ, không tự trả 0.
- Hỗ trợ aggregate, trend theo ngày/tuần/tháng, filter/breakdown trong catalog và top-k theo một metric. Relative date tính từ ngày dữ liệu mới nhất của nguồn.

| Metric | Cách tính | Cosmetics | Olist |
|---|---|---|---|
| events | Đếm event được ghi nhận | Có | Có, gồm lifecycle/payment/review |
| users | User duy nhất có event trong kỳ | Có | Chỉ khách đã đặt hàng |
| sessions | Session duy nhất | Có | Không ghi nhận |
| viewers | User duy nhất có product view | Có | Không ghi nhận |
| purchases | Đếm item purchase events | Có | Có; không phải số order |
| buyers | User duy nhất có item purchase | Có | Có |
| revenue | Cộng revenue trên item purchase | USD | BRL, loại payment/freight |
| buyer_conversion_rate | buyers/users quan sát trong kỳ | Không phải funnel tuần tự | Không phải visitor conversion |

Tám metric tạo ra nhiều câu hỏi nhờ kết hợp kỳ/filter/breakdown; không phải chỉ tám câu hỏi. Chưa xác nhận chúng bao phủ đủ công việc PM/PO. Không hỗ trợ metric delivery/review, order/AOV, retention, FX hoặc kết luận nhân quả, dù kho dữ liệu có một số field liên quan.

## Luồng AI và kiểm soát

Câu hỏi + nguồn + memory → LLM hiểu thành candidate → resolver hỏi lại nếu thiếu/mơ hồ → QuerySpec → validator và kiểm tra coverage → compiler Python sinh SQL có tham số → PostgreSQL reader role → facts/phép tính server → LLM viết nhận xét bằng fact references → giao diện hiển thị bảng, scope, SQL.

LLM chọn ý định và diễn giải, không tự viết SQL trong pipeline Texa. Baseline đánh giá mới là LLM sinh SQL trực tiếp. Không có DuckDB/AST sandbox/free-SQL self-correction trong scope này. QuerySpec hợp lệ vẫn có thể sai ý người hỏi, nên đánh giá chính phải so kết quả truy vấn.

Memory lưu metric, nguồn, kỳ, filter, breakdown và provenance của truy vấn thành công. Chọn ngữ cảnh liên quan thay vì chỉ sáu lượt gần nhất; hiểu “kết quả đó”, thêm điều kiện và tham chiếu câu/kết quả theo vị trí. Câu xã giao không ghi đè truy vấn; mơ hồ thì hỏi lại. Context vẫn có budget, không nhớ vô hạn; snapshot/catalog đổi thì không thừa kế kết quả cũ. Retry/edit replay state để tránh lưu trùng.

## Đánh giá và mức bằng chứng

Baseline B0 dùng cùng model, schema và định nghĩa nghiệp vụ để sinh SQL trực tiếp. Metric chính là tỷ lệ yêu cầu có **bảng kết quả đúng** so gold; không so chuỗi SQL. Chấm thêm action, slot, tham chiếu, scenario success, latency/token. QuerySpec chỉ là chẩn đoán, không thay thế execution accuracy.

Bộ v2: 96 events tổng hợp, 104 câu đơn (41 dev/63 test), 12 hội thoại. Ablation: 24 hội thoại/77 lượt trả lời và 20 câu mơ hồ + 20 control. Bộ `multisource_v1` là diagnostic trên dev, không phải holdout; gold SQL đã được kiểm tra với PostgreSQL. Không gán điểm synthetic thành accuracy trên warehouse thật.

**Kết quả formal đã chạy** (`gpt-6-luna`, cùng code/dữ liệu đóng băng, ba lần lặp): trên 63 câu test, Texa đúng 143/189 = **75,7%**, B0 (LLM sinh SQL trực tiếp) đúng 130/189 = **68,8%**. CI95% ghép theo nhóm câu hỏi/hội thoại cho chênh lệch là **−14,5 đến +26,1 điểm %**, nên chưa đủ bằng chứng kết luận Texa tốt hơn. Chấm chính yêu cầu toàn bộ bảng kết quả khớp; phép chiếu cột hậu nghiệm cho thấy B0 đạt 89,9%, nhưng đó chỉ là chẩn đoán về lỗi cột thừa, không phải metric chính. Median latency lần lượt 9,554 và 5,952 giây; Texa bao gồm sinh insight còn B0 chỉ sinh SQL.

Ablation memory (12 hội thoại holdout, 39 lượt gold, ba lần lặp): scenario success F/M6/M0 là **63,9% / 66,7% / 19,4%**; độ đúng lượt trả lời **70,9% / 81,2% / 65,0%**. CI95% F–M6 là −27,8 đến +22,2 điểm %, chưa cho thấy memory cấu trúc tốt hơn cửa sổ sáu lượt; F–M0 là +16,7 đến +69,4 điểm %. Bốn scenario F-r3 bị gián đoạn gateway nên usage là cận dưới, nhưng kết quả vẫn nằm trong điểm số. Ablation clarification (20 scenario holdout, 10 mơ hồ + 10 control, ba lần lặp): F **85,0%**, C0 **51,7%**, CI95% ghép **+15 đến +50 điểm %**; cải thiện chủ yếu ở trường hợp thiếu kỳ báo cáo, còn metric mơ hồ vẫn khó.

Diagnostic đa nguồn trên dev (English, một lần chạy; không phải holdout): fixture gồm **17 dòng**, **33 câu đơn**, **7 hội thoại**; 36 gold SQL được kiểm tra đúng trên PostgreSQL. Trên so sánh đơn lượt công bằng, Texa đúng **31/33 (93,9%)**, direct baseline đúng **19/33 (57,6%)**; median lần lượt 8,76 và 6,11 giây. Đây chỉ là tín hiệu ban đầu trên fixture nhỏ, không được gộp với test holdout hay coi là accuracy production. Runner hội thoại thô cho Texa 7/7 và baseline 4/7 nhưng có tiêu chí slot/reference khác nhau theo phương pháp, nên không dùng để tuyên bố baseline so sánh công bằng. Chi tiết: `data/benchmark/results/multisource-20261105/report.json`.

Đây là bằng chứng trên benchmark tổng hợp, không phải người dùng thật hay warehouse production; chưa chứng minh ưu thế tổng quát. Kết quả formal và diagnostic cần được đọc riêng. Chi tiết formal: `data/benchmark/results/study-20261105/report.json`; sự cố gateway: `data/benchmark/results/study-20261105/provider-incident.json`.

## Kiểm thử trực tiếp trên website

Sau benchmark, đã chạy `run.sh` và dùng trình điều khiển trình duyệt hỏi thật bằng `gpt-6-luna` trên warehouse Cosmetics/Olist. Các mẫu tổng doanh thu, item purchases Olist, nhóm tháng, top 3 và lọc danh mục khớp SQL đối chiếu độc lập; clarification chọn kỳ hoạt động. Đã quan sát dừng/hỏi lại, phân trang, khôi phục lịch sử, settings chỉ đọc và hai phiên browser riêng chạy đồng thời. Đây là kiểm tra chức năng trên mẫu nhỏ, không phải accuracy production hay kiểm thử tải cả lớp.

**Chưa nên mở demo tự do cho cả lớp:** hai cách nói tiếp nối tiếng Việt (“chia kết quả doanh thu vừa rồi…”, “chia doanh thu đó theo từng tháng”) bị phân loại thành chủ đề mới, mất nguồn/kỳ dù đã có kết quả. Gợi ý ở trang đầu vẫn quảng bá delivery, funnel và AOV hai nguồn ngoài scope; gợi ý sau từ chối cũng có câu không khả thi. Cần sửa nhận diện follow-up và các gợi ý, rồi kiểm tra lại trên dev/regression mới. Không sửa product/prompt sau khi đã xem holdout để làm đẹp số đo này. Vòng E2E mở rộng đã thử 8 kết quả liên tiếp: “kết quả 2” giữ đúng nguồn/kỳ/filter, còn “kết quả thứ hai” hỏi lại và không đưa kết quả cần chọn vào danh sách. Đã xác minh file CSV tải thật (top 3, tỷ lệ và đủ 31 dòng ngày, từng số khớp SQL), sửa câu hỏi và chuyển chat lúc đang chạy; kết quả không lẫn hội thoại. Mẫu trả lời có lúc mất 20–29 giây. Khi dropdown Olist mâu thuẫn câu hỏi Cosmetics, câu hỏi thắng nhưng dropdown không đổi/cảnh báo. Lỗi provider có chủ ý và tải cả lớp chưa kiểm tra. Bằng chứng hai vòng: `data/benchmark/results/live-e2e-20261105/` và `data/benchmark/results/live-e2e-extended-20261105/report.json`.

## Demo và vận hành tối thiểu

Publish catalog sản phẩm vào đúng DB ứng dụng sau khi đã nạp nguồn; file YAML thay đổi không tự thay catalog đã publish. Từ thư mục gốc:

```sh
cd backend
uv sync
uv run texa catalog publish ../catalog/product_events.yaml
uv run uvicorn texa.main:app --port 18000
```

Terminal khác từ thư mục gốc: `cd web && npm ci && npm run dev` (web `15173`). API riêng cần nhận cấu hình DB/key/model qua môi trường; `run.sh` có bước nạp `.env`, khởi động local services và publish catalog. Không commit `.env`/key.

Website lớp học bật `TEXA_SHARED_DEMO=1`, admin token ngẫu nhiên ≥24 ký tự, HTTPS với cookie secure; settings do host quản lý, lịch sử tách theo browser cookie. Đây là phiên ẩn danh, chưa có login. Một API worker vì RUNS/SSE nằm trong process; chưa có multi-replica hoặc kiểm thử tải model thật. Budget script đánh giá không tự áp dụng cho website; riêng phiên E2E này dùng launcher cục bộ để mọi lần gọi UI vào cùng ledger giới hạn 10 USD. Localhost dùng HTTP/cookie không secure; khi chia sẻ qua mạng cần cấu hình HTTPS như trên.

Lần kiểm tra offline khi thu gọn tài liệu: **161 passed, 31 skipped** (các kiểm thử cần DB không được tính là đạt). Lệnh: `backend/.venv/bin/python -m pytest backend/tests -q`; frontend `npm run build`, `npm run lint`. DB integration/E2E chỉ dùng DB riêng `texa_benchmark`; không nạp fixture vào warehouse demo. Không chạy chồng fixture pilot/v2/ablation/diagnostic. Các file benchmark và mã runner được giữ trong `data/benchmark/` và `backend/eval/`; repository chỉ giữ hai tài liệu hiện hành này.


## Chạy đánh giá và ablation

Thiết lập `TEXA_DB_DSN` (owner), `TEXA_READER_DSN` và `TEXA_BENCHMARK_DSN` (reader) cùng trỏ DB riêng `texa_benchmark`. Không dùng warehouse demo. Nạp **một** fixture bằng `backend/eval/setup_benchmark.py --dataset-dir <thư_mục_bộ> --dsn "$TEXA_DB_DSN"`, rồi publish đúng catalog vào DB đó. Không đưa DSN/key vào tài liệu hoặc Git.

- v2: `backend/.venv/bin/python backend/eval/validate_dataset.py data/benchmark/v2`; runner `backend/eval/run_benchmark.py --dataset-dir data/benchmark/v2 --method gold --split test` chỉ kiểm tra gold, không chấm model. Thay `gold` bằng `direct` hoặc `texa`, thêm `--model` để chạy model đã cấu hình.
- Ablation: `backend/.venv/bin/python backend/eval/validate_dataset.py data/benchmark/ablation_v1 --ablation`. `backend/eval/run_ablation.py --suite memory --matrix` mặc định dry-run; F/M6/M0 kiểm tra memory. `--suite clarification --matrix` so F/C0; `--suite single --dataset-dir data/benchmark/v2 --matrix` so F/B0 và cần fixture v2.
- Khi dùng gateway wrapper có trần USD, **không dùng `--matrix --execute`**: tiến trình con hiện bỏ qua wrapper. Chạy từng `--variant`/`--repeat` qua `run_gateway_check.py --runner ablation`, dùng chung ledger. Vòng đo đã làm theo cách này.
- Sau dev, chốt code/model/prompt/budget và tạo `--freeze-protocol <file.json>`. Live test dùng `--protocol <file.json> --split test --matrix --repeats 3 --execute --model <model> --max-model-calls <budget>` với runner ablation. Call budget tính cho mỗi process/variant/repeat, không phải trần USD.
- Tổng hợp bằng `backend/eval/report_ablation.py --inputs <logs.jsonl...> --output <report.json>`. Báo mean/sd, chênh lệch và CI theo scenario; không bỏ lỗi/timeout khỏi mẫu số. Hỏi lại được chấm theo ý định và kết quả cuối; C0 không tự động bị tính sai vì không hỏi.

Lệnh runner phía trên chạy bằng `backend/.venv/bin/python`. Provider cần được cấu hình riêng; thêm `--execute` sẽ gọi model có phí. Không lấy gold validation hoặc test dùng provider mô phỏng làm accuracy của LLM. Số liệu formal phía trên là từ lần chạy đã đóng băng; mọi lần chạy diagnostic mới cần được báo riêng, không gộp vào kết quả holdout.
