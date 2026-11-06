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
  → Truy hồi ví dụ SQL đã xác minh theo câu hỏi và nguồn
  → LLM đề xuất ý định/tham chiếu + adaptive consistency khi cần
  → binder/clarification giải nghĩa metric, filter, nguồn và kỳ
  → QuerySpec + kiểm tra capability/semantic values
  → compiler Python sinh SQL tham số hóa
  → PostgreSQL reader → facts có provenance → nhận xét có kiểm tra placeholder
```

LLM không tự viết SQL trong pipeline sản phẩm. Filter business label có thể được ánh xạ sang raw value theo source qua catalog; event name và nhãn hiển thị không được tự dịch thành SQL literal. Giao diện hoặc câu hỏi nêu nguồn khác nhau thì Texa hỏi người dùng trước khi chạy. Giá trị mở/high-cardinality vẫn có thể được dùng sau kiểm tra field; vocabulary đóng thì phải resolve được.

Memory giữ tham chiếu kết quả theo ID và các slot QuerySpec; slot chỉ được server kế thừa/đổi/xóa sau khi kiểm tra result, snapshot và catalog. Registry prompt có giới hạn token; nếu view bị cắt thì follow-up mơ hồ phải hỏi chọn target từ registry đầy đủ, không đoán theo phần mới nhất. Không phải memory vô hạn hay bảo đảm hiểu mọi cách nói.

## Benchmark và mức bằng chứng

Đánh giá v6 dùng cùng `gpt-6-luna`, câu hỏi và fixture. **B0** nhận câu hỏi, schema PostgreSQL vật lý và nguồn UI nếu đã chọn; không có catalog, định nghĩa nghiệp vụ, enum/source mapping hay ví dụ. **B1** thêm history văn bản và xử lý hỏi lại/thử lại khi cần. **Texa** có semantic catalog, phân giải ý định, memory cấu trúc, compiler và kiểm tra SQL. Vì B0 thiếu tri thức nguồn/giá trị có trong catalog, chênh lệch đo cả lợi ích thông tin semantic lẫn workflow; đây không phải so sánh chất lượng model hay bằng chứng riêng cho một component.

Metric chính là tỷ lệ khớp toàn bộ bảng kết quả chuẩn, bỏ qua alias nhưng giữ số cột, thứ tự/vai trò cột, hàng và giá trị. Từ chối sai hoặc không có kết quả tính sai. Strict contract/alias là metric phụ. Hội thoại tính theo lượt đã định trước; latency và chi phí báo riêng. Bộ candidate có 60 câu đơn (30 dev/30 test), 24 record clarification (12 cặp query/control), 9 hội thoại (8 lượt dev, 24 lượt test) và 12 diagnostic; fixture gồm ba worlds, nền 120 event tổng hợp. Candidate 60 câu đơn/9 hội thoại còn dưới mục tiêu thiết kế 180 câu đơn/24 hội thoại. Bộ do nhóm xây dựng, test split chưa được thẩm định độc lập và khóa kín, nên kết quả còn exploratory, không phải holdout độc lập hay production guarantee.

| Suite | B0 | B1 | Ablation bỏ cả hai · T00 | Bỏ consistency · T10 | Bỏ retrieval · T01 | **Texa mặc định · T11** |
|---|---:|---:|---:|---:|---:|---:|
| Single dev (30) | 3/30 (10,0%) | 2/30 (6,7%) | 29/30 (96,7%) | 29/30 (96,7%) | 29/30 (96,7%) | 29/30 (96,7%) |
| Single test (30) | 1/30 (3,3%) | 1/30 (3,3%) | 28/30 (93,3%) | 27/30 (90,0%) | 27/30 (90,0%) | 30/30 (100%) |
| Clarification test (12) | — | 1/12 (8,3%) | 12/12 (100%) | 11/12 (91,7%) | 11/12 (91,7%) | 11/12 (91,7%) |
| Conversation test (24 turns) | — | 1/24 (4,2%) | 22/24 (91,7%) | 19/24 (79,2%) | 20/24 (83,3%) | 22/24 (91,7%) |

**Texa đầy đủ (T11)** bật retrieval ví dụ SQL đã xác minh và adaptive self-consistency. Ablation **T00** bỏ cả hai; **T10** bỏ consistency; **T01** bỏ retrieval. T11 đạt 30/30 single test trong một lần chạy trên 30 câu candidate; đây không phải accuracy tổng thể hay cam kết production. Texa mặc định là **T11**, bật retrieval + adaptive consistency; T00/T10/T01 chỉ dùng cho ablation. Đây là lựa chọn hướng sản phẩm, không phải kết luận T11 tốt nhất ở mọi suite: T11 chỉ kích hoạt thêm mẫu consistency ở 1/30 câu single test, và chênh lệch trong một lần chạy chưa chứng minh lợi ích chung. Single dev: các biến thể Texa đều 29/30, so với B0 3/30. B0R thêm ví dụ SQL đã kiểm chứng đạt 11/30 dev và 16/30 test; đây là đối chứng few-shot riêng, không phải baseline thuần. Đối chứng trên cùng 30 câu dev, cùng chọn sẵn nguồn, đạt B0 13/30 (43,3%) và T00 28/30 (93,3%); baseline thấp hơn trong phép thử này, nhưng vẫn chưa tách riêng tác động workflow khỏi tri thức catalog. Replay các SQL đã đóng băng trên ba fixture worlds cho cùng số câu đúng (B0 1/30, B0R 16/30, B1 1/30, T00 28/30, T10/T01 27/30, T11 30/30); đây là kiểm tra độ bền của cùng SQL, không phải ba lần chạy độc lập hay thêm mẫu. Artifacts: `accuracy-schema-only-20261106-v6-dev/`, `accuracy-schema-only-20261106-v6-test/`, `accuracy-source-control-20261106-v6/`.

## Kiểm thử runtime và giới hạn

- Backend **384 passed, 36 skipped**; DB integration **30 passed**; Playwright **15 passed** với provider mô phỏng và 8 session. Các test xác nhận chức năng, không đo accuracy LLM.
- Browser model thật đã đo với cấu hình ablation T00: các luồng chính được thử trực tiếp; 5/6 câu có đáp án khớp, câu đếm view trả 12 thay vì 24. Chuỗi filter mobile+paid trả 62, bỏ mobile vẫn giữ paid trả 204, đổi sang desktop vẫn giữ paid trả 61; unique viewers 12 và Olist revenue 432 BRL/CSV đã đối chiếu. Đây là smoke/regression test nhỏ, không phải holdout.
- Diagnostic: T00 khớp hành động kỳ vọng 7/10, các toggle 8/10; lỗi là hỏi lại thay vì từ chối, không có Texa trả metric khác cho yêu cầu ngoài scope trong lượt này. Hai ca rubric chưa hỗ trợ được giữ riêng; không gộp với SQL accuracy.
- Browser parity benchmark riêng: Texa T00 15/15 câu đơn và 18/19 lượt hội thoại; đó là replay hồi quy trên các câu đã biết, không phải kiểm thử UI hay holdout.
- Với 30 câu single test, median latency B0/T11 là **8,1/13,3 giây**; chi phí ước tính cho mỗi lượt 30 câu là **$0,0062/$0,0280**. Texa chính xác hơn trong bộ này nhưng chậm và tốn hơn; không tuyên bố SLO hoặc sức chứa lớp học.
- Còn giới hạn: ít case và một repeat; test split chưa được human-review/sealed; persona chưa xác thực bằng nghiên cứu người dùng; cold-start schema-only không biết các raw enum/source mappings; diagnostic không phải SQL accuracy; còn trường hợp sai ở browser thật. Cần review gold độc lập, holdout mới, nhiều lần lặp và load test trước khi khẳng định khả năng triển khai rộng.

Cấu hình mặc định: `TEXA_EXAMPLE_RETRIEVAL=1`, `TEXA_CONSISTENCY=1`, `TEXA_EXAMPLE_POLICY=sql_verified`. Các ID benchmark được giữ nguyên để truy vết. Số T11 đã đo trên pipeline bật cả hai; đổi mặc định không tạo ra một lần đo mới. Browser thật 5/6 nêu trên là bằng chứng của T00, chưa phải xác nhận UI T11.

## Memory hội thoại

Memory giữ QuerySpec và result ID đã xác minh. Khi follow-up sửa một filter, mô hình trích xuất trường và thao tác cần thiết; server chỉ thay nhóm điều kiện tương ứng, giữ nguyên filter khác, rồi kiểm tra nguồn, kỳ, metric và snapshot trước khi chạy. Người dùng hỏi tự nhiên, không cần biết định dạng nội bộ. Câu nhiễu không được tự đổi truy vấn; tham chiếu chưa rõ thì hỏi lại. Đây là cơ chế có cấu trúc, không bảo đảm hiểu mọi cách nói hoặc ghi nhớ vô hạn.

## Chạy ứng dụng và dữ liệu

Dùng `./run.sh` cho demo hiện tại. Dừng bằng Ctrl-C hoặc `./run.sh stop`: script dừng API/Web local cùng toàn bộ container của compose project Texa, gồm PostgreSQL, Airflow, API/Web Docker và orphan containers; giữ nguyên container, image, volume và cache để lần sau khởi động nhanh. TERM/HUP hoặc lỗi startup cũng chạy cleanup; container khai báo `restart: "no"`. SIGKILL không thể được trap; nếu script bị buộc tắt, `./run.sh stop` vẫn dừng được container còn sót. Docker Desktop và các container project khác có vòng đời riêng.

Nếu chạy thủ công, publish catalog đã chọn vào đúng DB app rồi khởi động API/frontend. Benchmark phải dùng DB `texa_benchmark` riêng; không nạp fixture vào warehouse demo. `TEXA_SOURCE_PROFILE=evaluation` chỉ dùng trong runner đánh giá để mở source fixture `event_benchmark`; ứng dụng demo mặc định chỉ công bố Cosmetics/Olist. Không commit credential hoặc key; DSN demo thật giữ ngoài Git.
