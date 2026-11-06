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

Nghiên cứu v3 dùng cùng `gpt-6-luna`, câu hỏi và fixture trong hai lần chạy độc lập trên mỗi biến thể. Baseline schema-only nhận câu hỏi, schema PostgreSQL vật lý và nguồn UI; không có catalog, định nghĩa nghiệp vụ, enum/source mapping hay ví dụ. Baseline hội thoại có thêm lịch sử và protocol hội thoại. **Texa** có semantic catalog, phân giải ý định, memory cấu trúc, compiler và kiểm tra SQL. Vì baseline thiếu tri thức nguồn/giá trị có trong catalog, chênh lệch đo cả lợi ích thông tin semantic lẫn workflow; không thể quy toàn bộ mức tăng cho workflow hay một component riêng.

Metric chính cho câu hỏi đơn và các lượt có đáp án trong hội thoại là business accuracy: tỷ lệ khớp toàn bộ bảng chuẩn. Hội thoại báo theo answer slots, không dùng legacy scenario-success (chỉ số này bị ảnh hưởng bởi rubric tham chiếu lượt). Câu ngoài phạm vi chấm riêng bằng diagnostic action accuracy. Bộ candidate gồm 300 câu đơn (100 dev/200 test), 60 tình huống clarification, 40 hội thoại dài 6–12 lượt (355 lượt, 308 answer slots) và 40 câu ngoài phạm vi. Có 200 câu single test được chạy hai lần cho mỗi biến thể; mỗi lần dùng 100 case Cosmetics và 100 Olist. Gold SQL được kiểm tra qua 2.004 SQL/world checks trên ba fixture worlds; các lần gọi model chỉ chạy trên world base, không phải ba phép chạy benchmark độc lập. Hai nguồn và nested extensions là synthetic. Bộ do nhóm xây dựng; family/template overlap còn tồn tại, test chưa human-review hay sealed, nên kết quả exploratory chứ chưa phải holdout độc lập hay production guarantee.

| Suite | LLM baseline (schema-only) | LLM baseline (chat) | Texa without retrieval and consistency | Texa with only retrieval | Texa with only consistency | **Texa** |
|---|---:|---:|---:|---:|---:|---:|
| Single test (200 unique, 400 executions) | 90/400 (22,5%) | — | 350/400 (87,5%) | 361/400 (90,25%) | 348/400 (87,0%) | 365/400 (91,25%) |
| Conversation (40 dialogs; 308 answer slots/run) | — | 91/616 (14,8%) | 563/616 (91,4%) | 592/616 (96,1%) | 567/616 (92,0%) | 584/616 (94,8%) |
| Unsupported (40 cases × 2; action accuracy) | — | 4/80 (5,0%) | 67/80 (83,75%) | 69/80 (86,25%) | 75/80 (93,75%) | 76/80 (95,0%) |
| Clarification final table (60 cases × 2) | — | 33/120 (27,5%) | 119/120 (99,2%) | 119/120 (99,2%) | 120/120 (100%) | 120/120 (100%) |

Clarification có thêm metric hành động “có hỏi lại khi thiếu thông tin không”: baseline đạt 81/120 (67,5%); Texa without retrieval and consistency và Texa with only consistency đạt 120/120; Texa with only retrieval đạt 119/120 (99,2%); Texa đạt 120/120. Đây là bộ thay thế đã chạy; các kết quả clarification cũ có lỗi chú giải và không được dùng. Texa đạt business accuracy single cao nhất (91,25%); Texa with only retrieval đạt 90,25%, Texa with only consistency 87%, Texa without retrieval and consistency 87,5%, còn baseline schema-only đạt 22,5%. Trên hội thoại, Texa đạt 94,8%; Texa with only retrieval cao nhất với 96,1%. Kết quả này cho thấy thành phần không cải thiện đồng đều mọi suite. Kiểm tra consistency được gọi có điều kiện, không áp dụng cho mọi câu. Xem [báo cáo benchmark đầy đủ](../data/benchmark/results/research-v3-20261106/REPORT.md) và raw summary tại `data/benchmark/results/research-v3-20261106/summary.json`.

## Kiểm thử runtime và giới hạn

- Backend **398 passed, 36 skipped**; DB integration **30 passed**; Playwright **15 passed** với provider mô phỏng và 8 session. Các test xác nhận chức năng, không đo accuracy LLM.
- Browser model thật đã đo với cấu hình Texa without retrieval and consistency: các luồng chính được thử trực tiếp; 5/6 câu có đáp án khớp, câu đếm view trả 12 thay vì 24. Chuỗi filter mobile+paid trả 62, bỏ mobile vẫn giữ paid trả 204, đổi sang desktop vẫn giữ paid trả 61; unique viewers 12 và Olist revenue 432 BRL/CSV đã đối chiếu. Đây là smoke/regression test nhỏ, không phải holdout.
- Diagnostic ngoài phạm vi: Texa đạt action accuracy 95%; các biến thể còn lại đạt 83,75–93,75%. Đây là chẩn đoán hành động (từ chối/hỏi lại/giải thích), không gộp vào SQL accuracy.
- Browser parity benchmark riêng: Texa without retrieval and consistency 15/15 câu đơn và 18/19 lượt hội thoại; đó là replay hồi quy trên các câu đã biết, không phải kiểm thử UI hay holdout.
- Với 400 lần chạy single, median latency baseline/Texa là **7,7/13,8 giây**; tổng chi phí ước tính lần lượt **$0,074/$0,401**. Đây là đo trên fixture và mức giá gateway hiện tại, không phải cam kết SLO hoặc dự báo chi phí production.
- Còn giới hạn: test split chưa được human-review/sealed và có family overlap; persona chưa xác thực bằng nghiên cứu người dùng; baseline schema-only không biết raw enum/source mappings; diagnostic không phải SQL accuracy. Các quan sát browser cũ là lịch sử, không thuộc benchmark v3 và không xác nhận phiên bản hiện tại. Cần review gold độc lập, holdout mới và load test trước khi khẳng định khả năng triển khai rộng.

Cấu hình mặc định: `TEXA_EXAMPLE_RETRIEVAL=1`, `TEXA_CONSISTENCY=1`, `TEXA_EXAMPLE_POLICY=sql_verified`. Số liệu v3 đo Texa với cả hai thành phần bật; các ablation chỉ dùng để so sánh. Các quan sát browser trước đây là lịch sử và không phải xác nhận E2E cho kết quả v3.

## Memory hội thoại

Memory giữ QuerySpec và result ID đã xác minh. Khi follow-up sửa một filter, mô hình trích xuất trường và thao tác cần thiết; server chỉ thay nhóm điều kiện tương ứng, giữ nguyên filter khác, rồi kiểm tra nguồn, kỳ, metric và snapshot trước khi chạy. Người dùng hỏi tự nhiên, không cần biết định dạng nội bộ. Câu nhiễu không được tự đổi truy vấn; tham chiếu chưa rõ thì hỏi lại. Đây là cơ chế có cấu trúc, không bảo đảm hiểu mọi cách nói hoặc ghi nhớ vô hạn.

## Chạy ứng dụng và dữ liệu

Dùng `./run.sh` cho demo hiện tại. Dừng bằng Ctrl-C hoặc `./run.sh stop`: script dừng API/Web local cùng toàn bộ container của compose project Texa, gồm PostgreSQL, Airflow, API/Web Docker và orphan containers; giữ nguyên container, image, volume và cache để lần sau khởi động nhanh. TERM/HUP hoặc lỗi startup cũng chạy cleanup; container khai báo `restart: "no"`. SIGKILL không thể được trap; nếu script bị buộc tắt, `./run.sh stop` vẫn dừng được container còn sót. Docker Desktop và các container project khác có vòng đời riêng.

Nếu chạy thủ công, publish catalog đã chọn vào đúng DB app rồi khởi động API/frontend. Benchmark phải dùng DB `texa_benchmark` riêng; không nạp fixture vào warehouse demo. `TEXA_SOURCE_PROFILE=evaluation` chỉ dùng trong runner đánh giá để mở source fixture `event_benchmark`; ứng dụng demo mặc định chỉ công bố Cosmetics/Olist. Không commit credential hoặc key; DSN demo thật giữ ngoài Git.
