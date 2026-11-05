# Chạy ablation study Texa

Trạng thái và các kết quả model thật hiện có được tổng hợp tại [docs/EVALUATION.md](../../docs/EVALUATION.md) và [docs/CLASS_DEMO_CHECKS.md](../../docs/CLASS_DEMO_CHECKS.md). Benchmark là fixture event tổng hợp, không phải dữ liệu Olist hoặc độ chính xác đo trên Olist. Phạm vi sản phẩm được cấu hình hiện tại là Cosmetics + Olist, một nguồn, tám metric và nested scalar tối đa hai cấp; suite này không mở rộng phạm vi đó.

Các biến thể đã triển khai:

| ID | Thay đổi | Suite |
|---|---|---|
| F | Texa đầy đủ | memory, clarification, single |
| M6 | Chỉ đưa sáu lượt gần nhất vào ngữ cảnh, kể cả lựa chọn tham chiếu | memory |
| M0 | Không đọc lịch sử, không thừa kế slot hoặc lấy lại kết quả cũ | memory |
| C0 | Không hỏi lại về một kỳ báo cáo/metric mơ hồ; một lượt LLM chọn từ lựa chọn hợp lệ hoặc từ chối | clarification |
| B0 | Cùng LLM sinh SQL trực tiếp từ schema/định nghĩa nghiệp vụ | single |

C0 chỉ áp dụng khi resolver thực sự tạo form **một trường** `time_range` hoặc `recipe`. Form kết hợp hoặc trường khác vẫn xử lý như F và có trace `out_of_scope`; không tắt kiểm tra QuerySpec, nguồn dữ liệu, snapshot hoặc compiler. Mỗi lượt chỉ được đoán một lần. C0 không đọc oracle hoặc gold. Nếu LLM đã tự điền kỳ/metric và không tạo form, component chưa được kích hoạt: báo cáo trace thay vì giả định đã có một thử nghiệm hỏi lại hợp lệ.

F là mặc định của sản phẩm. `TEXA_ABLATION_VARIANT` chỉ bật rõ ràng trong process thử nghiệm. `TEXA_MEMORY_MODE=window6` cũ vẫn được nhận là M6 khi không khai báo variant; hai cấu hình mâu thuẫn bị từ chối ở runtime. Runner mới tự thiết lập variant và xóa chế độ legacy để tránh rò environment.

## 1. Dataset và DB riêng

Thực hiện các lệnh từ thư mục gốc `Final`. `data/benchmark/ablation_v1` có 24 hội thoại memory và 20 câu mơ hồ kèm 20 câu đối chứng. `cases.yaml` trống có chủ đích: so sánh B0–F dùng dataset v2 riêng.

Chỉ sử dụng DB tên **texa_benchmark**; app owner ghi `app.*`, reader là role không phải superuser để đọc analytics. Khởi tạo DB/role trước, rồi cấu hình ba DSN dưới đây cho đúng DB riêng của bạn. Không dùng DSN warehouse của ứng dụng đang sử dụng bình thường.

```sh
export TEXA_DB_DSN='postgresql://OWNER@HOST:PORT/texa_benchmark'
export TEXA_READER_DSN='postgresql://READER:PASSWORD@HOST:PORT/texa_benchmark'
export TEXA_BENCHMARK_DSN="$TEXA_READER_DSN"

backend/.venv/bin/python backend/eval/validate_dataset.py data/benchmark/ablation_v1 --ablation
backend/.venv/bin/python backend/eval/setup_benchmark.py \
  --dataset-dir data/benchmark/ablation_v1 --initialize --dsn "$TEXA_DB_DSN"
backend/.venv/bin/python -c 'from texa import catalog; catalog.publish()'
```

Ba kết nối phải nhìn thấy cùng event fixture. Runner kiểm tra dữ liệu thực theo canonical digest, registry min/max/count, catalog và gold trước khi có model call. Mỗi log ghi fingerprint dữ liệu/metadata, catalog, tài nguyên prompt, commit và cấu hình provider, không ghi API key/DSN. Các prompt thực gọi có hash riêng ở scenario; không đòi chúng giống nhau giữa các ablation vì thay context chính là treatment.

Loading fixture ablation thay partition `event_benchmark`. Không chạy test pilot hoặc v2 trên fixture này. Khi cần v2, reload `data/benchmark/v2`; khi cần các integration test cũ, reload pilot `data/benchmark`.

## 2. Kiểm tra không gọi model

Các lệnh sau chỉ kiểm tra gold hoặc in lịch dự kiến, không gọi provider:

```sh
backend/.venv/bin/python backend/eval/run_ablation.py --gold --suite memory --split dev
backend/.venv/bin/python backend/eval/run_ablation.py --gold --suite memory --split test
backend/.venv/bin/python backend/eval/run_ablation.py --gold --suite clarification --split dev
backend/.venv/bin/python backend/eval/run_ablation.py --gold --suite clarification --split test
backend/.venv/bin/python backend/eval/run_ablation.py --suite memory --matrix
```

Mặc định runner luôn dry-run. `--gold` kiểm tra SQL với literal reference, không chấm model. Kiểm tra cấu trúc, oracle và checksum bằng validator ở bước 1. Regenerate dataset không tự cập nhật validation lock; cần review rồi mới `--write-lock`.

## 3. Pilot dev và khóa cấu hình

Cấu hình provider qua cơ chế hiện có của Texa. Chọn model cụ thể thay `MODEL_ID` và ngân sách `CALL_BUDGET` trước khi chạy. Hai giá trị này dưới đây là placeholder, không phải kết quả hay cấu hình đã được thử nghiệm.

```sh
backend/.venv/bin/python backend/eval/run_ablation.py \
  --suite memory --split dev --matrix --repeats 3 --execute \
  --model MODEL_ID --max-model-calls CALL_BUDGET \
  --output-dir backend/eval/results/memory-dev-01
```

`--max-model-calls` giới hạn số lần gọi API ứng dụng trong **mỗi process/variant/repeat**, không phải tiền hoặc token cứng, cũng không giới hạn retry bên trong SDK. Mặc định tổng output dùng cấu hình provider; các bước có giới hạn riêng ghi trong provenance và per-call trace. Dữ liệu lớn hơn có thể cần budget lớn hơn; ước tính bằng pilot, không tự tăng budget sau khi nhìn test. Thiếu budget hoặc timeout để lại log **incomplete**, reporter sẽ từ chối. Chạy lại cả block vào thư mục mới, không ghi đè hoặc ghép thêm vào log cũ.

Sau khi chốt implementation/prompt trên dev, commit code rồi đóng băng cấu hình. Freeze chỉ đọc DB/config và kiểm tra gold, không gọi model:

```sh
backend/.venv/bin/python backend/eval/run_ablation.py \
  --suite memory --split dev --model MODEL_ID --max-model-calls CALL_BUDGET \
  --freeze-protocol backend/eval/results/memory-protocol.json
```

Protocol khóa suite/model, giới hạn tài nguyên, commit, dataset, metadata/catalog và prompt assets. Dùng cùng protocol cho các variant của suite. Đổi input sau khi đã xem test phải được ghi là một vòng thử nghiệm mới; runner không chấp nhận âm thầm dùng protocol cũ.

## 4. Vòng test có model thật

```sh
backend/.venv/bin/python backend/eval/run_ablation.py \
  --suite memory --split test --matrix --repeats 3 --execute \
  --model MODEL_ID --max-model-calls CALL_BUDGET \
  --protocol backend/eval/results/memory-protocol.json \
  --output-dir backend/eval/results/memory-test-01
```

Mỗi repeat chạy các variant trong subprocess riêng, xoay thứ tự F/M6/M0. Hội thoại mới cho mỗi scenario, không kế thừa output của variant khác. Test live bắt buộc protocol đã freeze. Không có API để tự chọn lần chạy đẹp nhất.

Suite clarification dùng cùng các bước, thay `--suite clarification` và tên protocol/thư mục. Matrix sẽ chạy F/C0. Với mỗi tình huống, chỉ gửi oracle khi hệ thống thực sự hỏi đúng trường và đưa đúng lựa chọn. C0 trả lời luôn thì không có lượt oracle. Chấm **kết quả cuối theo ý định người dùng**, không tự chấm C0 sai chỉ vì không hỏi. Các câu đối chứng không được cấp oracle để cứu việc hỏi thừa. Giới hạn mặc định hai lượt làm rõ.

Suite single: reload fixture v2, dùng `--dataset-dir data/benchmark/v2 --suite single`. Matrix F/B0; protocol riêng, cùng model/schema/định nghĩa metric/data. Đây là baseline toàn hệ thống, không quy mọi chênh lệch cho compiler. Thời gian Texa bao gồm phần viết insight; B0 chỉ sinh SQL, nên phải diễn giải chi phí theo toàn pipeline chứ không gọi là thời gian sinh SQL thuần.

## 5. Báo cáo kết quả

```sh
backend/.venv/bin/python backend/eval/report_ablation.py \
  --inputs backend/eval/results/memory-test-01/*.jsonl \
  --output backend/eval/results/memory-report.json \
  --markdown backend/eval/results/memory-report.md
```

Reporter từ chối log thiếu `run_complete`, trùng repeat, thiếu scenario, khác dataset/model/commit/config, khác số câu phải trả lời hoặc sai cluster labels.

Báo cáo tách:

- **Execution Accuracy:** số câu SQL cho đúng kết quả trên tất cả yêu cầu có đáp án, lỗi/không trả lời vẫn nằm trong mẫu số.
- **Scenario success:** toàn bộ hành động bắt buộc và trả lời trong hội thoại đều đúng; không đồng nghĩa SQL accuracy.
- Kết quả cuối tình huống hỏi lại, sai/thiếu/hỏi thừa các trường, slot đúng/sai và kết quả theo từng nhóm.
- Mean/sd giữa repeat, chênh lệch F–variant và CI95% theo whole scenario cluster, giữ tất cả repeats trong một cụm. Câu mơ hồ và control chung cụm, không coi repeat là mẫu mới.
- p50/p95, số call, token và số lượt hỏi lại. Không đo thời gian người dùng thật; thời gian oracle chỉ là xử lý máy. Failed provider call có thể không trả token: `usage_complete=false` và báo token là lower bound, không gán token 0 là chi phí thực 0. Không quy đổi tiền khi chưa có bảng giá/version.

M6 có thể trả đúng mà không có `context.references`: đó là metadata chẩn đoán, không phải điều kiện thắng/thua. Không gọi P/R là 100% khi mẫu số bằng 0; báo N/A. F–M6 là so sánh chính, các arm còn lại bổ sung; số scenario ít và dữ liệu synthetic nên CI cần diễn giải thận trọng.

## 6. Kiểm thử implementation

```sh
backend/.venv/bin/python -m pytest \
  backend/tests/test_ablation_runtime.py backend/tests/test_ablation_dataset.py \
  backend/tests/test_ablation_runner.py backend/tests/test_ablation_report.py -q

TEXA_PRODUCT_TEST_DSN=1 TEXA_ABLATION_TEST_DSN=1 \
  backend/.venv/bin/python -m pytest backend/tests/test_ablation_integration.py -q
```

Integration ablation yêu cầu đúng fixture ablation và DSN bước 1; mọi model call được mô phỏng. Những kiểm tra này xác nhận code/protocol/gold, không cung cấp số liệu model accuracy.

Các lệnh chạy live ở trên là workflow giao thức còn dùng được; chúng chưa đồng nghĩa với một full ablation đã hoàn tất. Mọi lần chạy holdout 63 câu và full F/M6/M0/C0 nhiều repeat vẫn pending. Kết quả dev exploratory, cùng phiên bản/model/cấu hình và giới hạn của chúng, được ghi trong báo cáo đánh giá canonical.
