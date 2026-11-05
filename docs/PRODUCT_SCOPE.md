# Texa — Product scope

Cập nhật 06/11/2026. Kịch bản trình bày hiện hành: [FINAL_PRESENTATION_SCRIPT](FINAL_PRESENTATION_SCRIPT.md).

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

Protocol hiện tại dùng một bộ candidate dev gồm **60 câu đơn (30 dev/30 test), 24 bản ghi hỏi lại, 9 hội thoại và 12 ca chẩn đoán**; có ba fixture worlds (120 dòng base, gồm phần mở rộng synthetic nested cho Olist). Lượt đo hiện tại dùng 30 câu đơn dev, 12 ca hỏi lại dev và bốn hội thoại dev (tám lượt chấm). Đây là **một repeat, bộ đã thấy, chưa có holdout được người thẩm định độc lập và khóa lại**. Score chính là strict business-result correctness theo contract nghiệp vụ; C19 có annotation erratum tường minh, hash-pinned, chỉ sửa điểm dựa trên `result_correct` raw. Kiểm tra robustness bổ sung là posthoc alias-insensitive so sánh full result values; đây là metric riêng, không thay score chính.

Các cấu hình: **B0** là cùng model sinh SQL trực tiếp; **B0R** thêm retrieval ví dụ SQL đã xác minh; **B1** là baseline SQL với history văn bản thuần, không dùng đường QuerySpec/compiler của Texa; **T00/T10/T01/T11** lần lượt tắt cả hai/tăng retrieval/tăng self-consistency/bật cả hai. Bank có 45 ví dụ (42 được agent duyệt, trong đó 7 có SQL được thực thi kiểm chứng độc lập); cùng tập 7 ví dụ này làm nền so sánh retrieval. Self-consistency tối đa 3 mẫu, có giới hạn và không đoán khi thiếu thông tin. Retrieval và consistency là toggle thử nghiệm; không có bằng chứng cải thiện đã được chứng minh, và không bật làm mặc định.

**Single dev đã hiệu chỉnh** (`accuracy-dev-20261106-v2/single-summary-corrected.json`, 30 cases mỗi variant, một lần): B0 **29/30 (96,7%)**, B0R **29/30**, B1 **25/30 (83,3%)**, T00 **27/30 (90,0%)**, T10 **26/30 (86,7%)**, T01 **28/30 (93,3%)**, T11 **27/30 (90,0%)**. Đây là mô tả bộ dev, không chứng minh feature hay Texa cải thiện. Các world robustness v2 cho cùng số ở cả ba worlds; strict/full-value counts lần lượt: B0 29/29, B0R 29/29, B1 25/25 (4 thiếu SQL), T00 27/29 (1 thiếu), T10 26/28 (1 thiếu), T01 28/29 (1 thiếu), T11 27/28 (1 thiếu). Cột sau là full-result values, bỏ qua khác biệt alias output, chỉ là kiểm tra bổ sung sau chấm.

Hỏi lại dev: B1 **9/12**, T00 **10/12**, T10 **12/12**, T01 **11/12**, T11 **10/12**. Hội thoại chạy lại sau sửa adapter: B1 **7/8**, T00/T10/T01 **8/8**, T11 **7/8**, trên bốn hội thoại ngắn và một repeat. Diagnostic có 10 ca chấm action: B1 **2/10**, T00/T01/T11 **7/10**, T10 **6/10**; hai ca còn lại cần rubric review riêng. Nhiều điểm trượt là hỏi lại thay vì từ chối ngay, không đồng nghĩa chạy SQL nguy hiểm. T10 có một lượt trả lời AOV bằng metric khác: regression thật, chặn rollout. Không gộp các nhóm thành một accuracy chung.

Artifacts hiện hành: `accuracy-dev-20261106-v2/`, `accuracy-conversation-20261106-v3/`, `accuracy-diagnostic-20261106-v4/` trong `data/benchmark/results/`. Các lần chạy lỗi/protocol cũ được giữ và có ghi chú; lịch sử xa hơn tại `remediation-20261105/`.

## Kiểm thử runtime

- Backend: **323 passed, 36 skipped**; Playwright **15/15** với provider mô phỏng. Đây là test chức năng/isolation, không phải accuracy của LLM.
- Model thật: tám request đồng thời đều đúng số và tiền tệ; tám lượt đọc chéo phiên đều trả 404. End-to-end p50 **21,2 giây**, p95 **36,5 giây**; queue p50/p95 **6,3/16,3 giây**. Đây là sanity test một lượt, chưa phải sức chứa lớp học.
- Browser thật lượt mới: 23 lượt hỏi, 21 câu có đáp án bảng; **19/21** khớp SQL viết độc lập, hai câu về view/viewers bị từ chối sai. Đã kiểm SQL/CSV, hỏi lại, xung đột nguồn, nested filters/xóa filter, cancel/retry, cài đặt demo và reload lịch sử. Sau 13 kết quả thành công + noise, tham chiếu kết quả thứ hai chọn đúng Olist và chia tháng đúng. Dùng synthetic fixture cô lập, cờ mới tắt; không phải holdout hoặc kiểm tải lớp học. Evidence: `accuracy-browser-20261106/browser-check.json`.
- Bằng chứng mới: `data/benchmark/results/accuracy-dev-20261106-v2/`; lịch sử: `data/benchmark/results/remediation-20261105/`. Không suy rộng ví dụ đúng thành cam kết mọi câu đều đúng.
- Một API worker; RUNS/SSE và semaphore là process-local. Mặc định tối đa bốn lượt xử lý, 16 lượt chờ, timeout hàng đợi 30 giây. Startup đánh dấu lượt dở là INTERRUPTED. `first_result_ms` đo SQL-ready phía server; UI hiện vẫn chờ phần nhận xét để hiển thị trọn câu trả lời.

## Còn phải xác minh trước khi mở demo rộng

1. Thẩm định gold độc lập lần hai, tạo holdout mới không nhìn thấy trước và chạy frozen B0/F + ablation theo protocol đã đăng ký trước.
2. Mở rộng nhiều hội thoại độc lập và paraphrase, sửa/xóa filter, stale snapshot; một hội thoại 12 kết quả chưa đại diện toàn bộ memory. Bổ sung scorer cho discussion bằng contract rõ ràng.
3. Đo stage latency p50/p95 theo truy vấn và tải thực tế; chưa chọn tối ưu hoặc tuyên bố đạt SLO.
4. Đánh giá rủi ro process-local SSE/admission nếu lớp mở nhiều kết nối hơn khả năng một worker; chưa có multi-worker test.
5. Kiểm tiếp các lỗi legacy ngoài luồng chính và export Việt/Anh. Ba loại cảnh báo availability và các note của catalog sản phẩm đã có bản Việt; một số fallback legacy vẫn cần kiểm tra.

## Chạy ứng dụng và dữ liệu

Dùng `./run.sh` cho demo hiện tại. Dừng bằng Ctrl-C hoặc `./run.sh stop`: script dừng API/Web local cùng toàn bộ container của compose project Texa, gồm PostgreSQL, Airflow, API/Web Docker và orphan containers; giữ nguyên container, image, volume và cache để lần sau khởi động nhanh. TERM/HUP hoặc lỗi startup cũng chạy cleanup; container khai báo `restart: "no"`. SIGKILL không thể được trap; nếu script bị buộc tắt, `./run.sh stop` vẫn dừng được container còn sót. Docker Desktop và các container project khác có vòng đời riêng.

Nếu chạy thủ công, publish catalog đã chọn vào đúng DB app rồi khởi động API/frontend. Benchmark phải dùng DB `texa_benchmark` riêng; không nạp fixture vào warehouse demo. `TEXA_SOURCE_PROFILE=evaluation` chỉ dùng trong runner đánh giá để mở source fixture `event_benchmark`; ứng dụng demo mặc định chỉ công bố Cosmetics/Olist. Không commit credential hoặc key; DSN demo thật giữ ngoài Git.
