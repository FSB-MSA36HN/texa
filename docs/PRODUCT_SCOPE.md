# Texa — Product scope

Cập nhật 05/11/2026. Kịch bản trình bày hiện hành: [FINAL_PRESENTATION_SCRIPT](FINAL_PRESENTATION_SCRIPT.md).

## Sản phẩm và người dùng

Texa hỗ trợ PM/PO và người quản lý không chuyên SQL tự xem số liệu thương mại điện tử: hỏi bằng tiếng Việt hoặc tiếng Anh, xem bảng, lọc/chia nhóm, đổi kỳ và hỏi tiếp. Kết quả có thể hỗ trợ ra quyết định, không thay thế phân tích chuyên môn hoặc xác minh nghiệp vụ. Persona này là định hướng sản phẩm, chưa được xác nhận bằng nghiên cứu người dùng; LLM không được đảm bảo đúng tuyệt đối.

## Phạm vi hiện tại

- Một engine: PostgreSQL; hai nguồn được cấu hình sẵn: Cosmetics Shop và Olist.
- Mỗi truy vấn chỉ dùng một nguồn; không join/cộng gộp hai nguồn, không hướng tới chuẩn hóa mọi database hay kiến trúc data của mọi công ty.
- Dữ liệu là event rows qua ETL adapter hiện có và catalog semantic được quản trị trong `catalog/product_events.yaml`.
- Nested scalar chỉ trong các path được khai báo, sâu tối đa hai key dưới `ep`/`up`; không bung array. Thiếu field/event là unavailable, không được báo thành zero.
- Hỗ trợ aggregate, ngày/tuần/tháng, filter, breakdown và top-k một metric trong phạm vi catalog. Relative date tính từ ngày mới nhất của nguồn.

| Metric | Ý nghĩa ngắn | Cosmetics | Olist |
|---|---|---|---|
| Events | Số event được ghi nhận | Có | Có |
| Users | User duy nhất được quan sát trong kỳ | Có | Khách đã đặt hàng, không phải toàn bộ visitor |
| Sessions | Session duy nhất | Có | Không ghi nhận |
| Viewers | User duy nhất đã xem sản phẩm | Có | Không ghi nhận |
| Purchases | Item lines được mua, không phải số order | Có | Có |
| Buyers | User duy nhất có item purchase | Có | Có |
| Revenue | Tổng giá trị item purchase theo tiền tệ nguồn | USD | BRL; không cộng payment/freight |
| Buyer conversion rate | Buyers/users quan sát trong kỳ; không phải funnel tuần tự | Có | Không phải visitor conversion |

Đây là tám metric, không phải tám câu hỏi: có thể kết hợp kỳ, filter và breakdown. Chưa chứng minh độ bao phủ đủ mọi công việc PM/PO. Ngoài scope: delivery/review, order/AOV, retention, FX, causal claims và các truy vấn tự do.

## Cách Texa xử lý yêu cầu

```text
Câu hỏi + nguồn đã chọn
  → LLM đề xuất ý định và tham chiếu hội thoại có cấu trúc
  → binder/clarification giải nghĩa metric, filter, nguồn và kỳ
  → QuerySpec + kiểm tra capability/semantic values
  → compiler Python sinh SQL tham số hóa
  → PostgreSQL reader → facts có provenance → nhận xét có kiểm tra placeholder
```

LLM không tự viết SQL trong pipeline sản phẩm. Filter business label có thể được ánh xạ sang raw value theo source qua catalog; event name và nhãn hiển thị không được tự dịch thành SQL literal. Giao diện hoặc câu hỏi nêu nguồn khác nhau thì Texa hỏi người dùng trước khi chạy. Giá trị mở/high-cardinality vẫn có thể được dùng sau kiểm tra field; vocabulary đóng thì phải resolve được.

Memory giữ tham chiếu kết quả theo ID và các slot QuerySpec; slot chỉ được server kế thừa/đổi/xóa sau khi kiểm tra result, snapshot và catalog. Registry prompt có giới hạn token; nếu view bị cắt thì follow-up mơ hồ phải hỏi chọn target từ registry đầy đủ, không đoán theo phần mới nhất. Không phải memory vô hạn hay bảo đảm hiểu mọi cách nói.

## Benchmark và mức bằng chứng

Baseline B0 là cùng model sinh SQL trực tiếp từ câu hỏi/schema/định nghĩa nghiệp vụ. Texa dùng cùng model và thêm semantic resolver, clarification, memory, catalog validation và compiler. Metric chính protocol v2 là business-result correctness theo output contract đã khai báo; metric phụ là output-contract compliance. Không so chuỗi SQL và không thay điểm lịch sử bằng protocol mới.

Lượt mới dùng `data/benchmark/remediation_v3_regression/`: **24 câu đơn** (8 dev/16 test nhìn thấy), **4 hội thoại**, **4 tình huống clarification**, trên **17 dòng tổng hợp cho hai nguồn**. Mỗi cấu hình lặp ba lần. Protocol 3 sửa phần oracle/tiêu chí thứ tự dòng của bộ candidate đã kiểm tra; câu hỏi, gold SQL và bảng đáp án giữ nguyên. Oracle chỉ trả các field hệ thống thực sự hỏi, theo ý định khai báo trước; không đưa số gold vào prompt. Vì đã nhìn thấy bộ này và chưa có reviewer thứ hai, đây là **regression diagnostic**, không phải holdout hay accuracy production.

**Kết quả câu đơn v3:** Texa 35/48 = 72,9%; B0 41/48 = 85,4% (16 câu test × 3 lần). Baseline cao hơn 12,5 điểm phần trăm trong lượt regression này; chưa chứng minh Texa tốt hơn. Clarification được chạy lại riêng bằng protocol 4 vì v3 thiếu oracle kỳ báo cáo: F 6/6 (100%), C0 1/6 (16,7%) trên hai tình huống × ba lần; chỉ là regression nhỏ đã nhìn thấy, không suy rộng. Memory có một task trả lời bằng lời từ bảng trước, chưa có contract chấm bằng SQL-result; báo cáo đánh dấu so sánh đó không hợp lệ và công bố coverage, không tự suy ra đúng từ một con số trong câu trả lời. Lượt candidate trước bị thiếu oracle kỳ và gián đoạn timeout được giữ nguyên trong `initial-protocol-attempt/`.

Các formal scores protocol cũ (63 câu × 3 lần: Texa 143/189 = 75,7%, B0 130/189 = 68,8%; CI95% chênh lệch −14,5…+26,1 điểm %) vẫn là bằng chứng lịch sử của code/scorer cũ. Không so trực tiếp với lượt regression mới. Formal cũ chưa chứng minh Texa hơn baseline.

## Kiểm thử runtime

- Backend: **261 passed, 12 skipped**; Playwright **15/15**. Playwright dùng provider mô phỏng, gồm tám phiên browser và kiểm tra isolation; không dùng nó làm accuracy của LLM.
- Model thật: tám request đồng thời đều đúng số và tiền tệ; tám lượt đọc chéo phiên đều trả 404. End-to-end p50 **21,2 giây**, p95 **36,5 giây**; queue p50/p95 **6,3/16,3 giây**. Đây là sanity test một lượt, chưa phải sức chứa lớp học.
- Một hội thoại model thật có **12/12** kết quả đúng; sau social noise, “kết quả thứ hai” quay lại đúng Olist 01/2018. Cả **31 dòng theo ngày** khớp SQL độc lập. Browser cũng đã kiểm nguồn xung đột, chọn lại nguồn, ordinal bằng chữ và cả Cosmetics/Olist.
- Bằng chứng: `data/benchmark/results/remediation-20261105/`. Không suy rộng các ví dụ đúng thành cam kết mọi câu đều đúng.
- Một API worker; RUNS/SSE và semaphore là process-local. Mặc định tối đa bốn lượt xử lý, 16 lượt chờ, timeout hàng đợi 30 giây. Startup đánh dấu lượt dở là INTERRUPTED. `first_result_ms` đo SQL-ready phía server; UI hiện vẫn chờ phần nhận xét để hiển thị trọn câu trả lời.

## Còn phải xác minh trước khi mở demo rộng

1. Thẩm định gold độc lập lần hai, tạo holdout mới không nhìn thấy trước và chạy frozen B0/F + ablation theo protocol đã đăng ký trước.
2. Mở rộng nhiều hội thoại độc lập và paraphrase, sửa/xóa filter, stale snapshot; một hội thoại 12 kết quả chưa đại diện toàn bộ memory. Bổ sung scorer cho discussion bằng contract rõ ràng.
3. Đo stage latency p50/p95 theo truy vấn và tải thực tế; chưa chọn tối ưu hoặc tuyên bố đạt SLO.
4. Đánh giá rủi ro process-local SSE/admission nếu lớp mở nhiều kết nối hơn khả năng một worker; chưa có multi-worker test.
5. Kiểm tiếp các lỗi legacy ngoài luồng chính và export Việt/Anh. Ba loại cảnh báo availability và các note của catalog sản phẩm đã có bản Việt; một số fallback legacy vẫn cần kiểm tra.

## Chạy ứng dụng và dữ liệu

Dùng `run.sh` cho demo hiện tại. Nếu chạy thủ công, publish catalog đã chọn vào đúng DB app rồi khởi động API/frontend theo README. Benchmark phải dùng DB `texa_benchmark` riêng; không nạp fixture vào warehouse demo. `TEXA_SOURCE_PROFILE=evaluation` chỉ dùng trong runner đánh giá để mở source fixture `event_benchmark`; ứng dụng demo mặc định chỉ công bố Cosmetics/Olist. Không commit credential hoặc key; DSN demo thật giữ ngoài Git.
