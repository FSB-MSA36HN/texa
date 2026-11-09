# Texa — Product scope

Cập nhật 09/11/2026.

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

Đây là tám metric gốc, không phải tám câu hỏi cố định: mỗi metric có thể kết hợp kỳ, filter và breakdown; catalog còn quản lý dimensions, event roles và mapping. Chưa chứng minh độ bao phủ đủ mọi công việc PM/PO. Ngoài scope: delivery/review, order/AOV, retention, FX, causal claims và các truy vấn tự do.

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

## Khó khăn khi mapping hai dataset

Hai nguồn được đưa vào cùng bảng `analytics.event_activity` qua hai mart khác nhau (`pipeline/sql/mart/`). Cosmetics là luồng hành vi (view, cart, purchase), Olist là vòng đời đơn hàng được dựng thành event. Vì vậy cùng một tên metric có nghĩa khác nhau; catalog chỉ nối chúng bằng role `purchase` có `alternatives: true`.

| Điểm lệch | Cosmetics | Olist | Cách xử lý hiện tại | Rủi ro còn lại |
|---|---|---|---|---|
| Từ vựng event | `view`, `cart`, `remove_from_cart`, `purchase` | 7 event vòng đời (`order_purchased`, `order_approved`, …) | Role trong catalog; event không có thì metric không khả dụng | `events` của hai nguồn không so sánh được |
| `user_id` | Định danh duyệt web ẩn danh | `customer_unique_id`, khách đã đặt hàng | Ghi chú nguồn Olist | `users` Olist gồm cả khách chỉ có event giao hàng/thanh toán/đánh giá trong kỳ; conversion bị loãng |
| Session, viewers | Có | Không có | Metric khả dụng/không khả dụng theo cột và role (`sanity.py`) | Đã xử lý đúng |
| Purchases, revenue | Dòng mua, USD | Dòng sản phẩm, BRL, **gồm cả đơn sau đó bị hủy** | Ghi chú metric `purchases`, `buyers`, `revenue` của Olist | Số liệu Olist cao hơn đơn thực giao |
| Thời gian | UTC | Giờ Brazil lưu như UTC; hủy và thanh toán được tính theo ngày đặt | Ghi chú nguồn Olist | Ngày có thể lệch tới 3 giờ |
| Tiền tệ | USD | BRL; `revenue_usd` có trong mart nhưng metric không dùng | Chỉ một nguồn mỗi truy vấn | Cột FX là dữ liệu chết nếu chưa nạp tỷ giá |
| Địa lý, danh mục | Danh mục là đoạn đầu của `category_code`; không có địa lý | Tên danh mục tiếng Anh; có địa lý nhưng catalog chưa mở | Dimension không có dữ liệu thì khả dụng = không | Event vòng đời Olist không có danh mục nên tạo nhóm NULL khi nhóm theo danh mục |
| Dữ liệu nested | `ep.category_path`, … | `ep.order_status`, `ep.freight_value`, … | Chỉ các path khai báo | `device_type`, `campaign_channel` chỉ tồn tại trong fixture tổng hợp, không có ở dữ liệu thật |

**Đã sửa (không đổi định nghĩa metric):** thêm `data_notes` theo nguồn và theo metric để cảnh báo hiện cùng kết quả; xóa mục `scope` mồ côi trong catalog; thêm quality check `07_revenue_only_on_money_events` (revenue chỉ nằm ở event mua/thanh toán) và `quality/olist_marketplace/01_purchase_rows_match_items` (số dòng `order_purchased` bằng số item trong staging); cập nhật fingerprint của example bank vì bank gắn với nội dung catalog.

**Đề xuất, chưa làm** vì đổi định nghĩa sẽ đổi đáp án chuẩn và buộc đo lại benchmark: loại đơn hủy/không khả dụng khỏi role `purchase` của Olist qua `ep.order_status`; dùng mẫu số theo sự kiện đặt hàng cho conversion Olist; đổi Olist sang `America/Sao_Paulo`; mở địa lý Olist; biến `revenue_usd` thành metric riêng hoặc bỏ cột; thêm check bắt buộc nạp tỷ giá trước khi nạp cửa hàng.

## Benchmark và mức bằng chứng

Nghiên cứu v3 dùng cùng `gpt-6-luna`, câu hỏi và fixture. **Baseline** nhận câu hỏi, schema PostgreSQL và cùng các định nghĩa nghiệp vụ dạng văn bản; nếu SQL lỗi khi thực thi, được sửa một lần dựa trên loại lỗi an toàn. Baseline không dùng QuerySpec, compiler hay validator của Texa. **Texa** dùng semantic catalog, phân giải ý định, memory cấu trúc, compiler và kiểm tra SQL. Baseline câu đơn không được chấm trong hội thoại, clarification hay ngoài phạm vi.

Metric chính cho câu hỏi đơn và các lượt có đáp án trong hội thoại là business accuracy: tỷ lệ khớp toàn bộ bảng chuẩn. Hội thoại báo theo answer slots, không dùng legacy scenario-success (chỉ số này bị ảnh hưởng bởi rubric tham chiếu lượt). Câu ngoài phạm vi chấm riêng bằng diagnostic action accuracy. Bộ candidate gồm 300 câu đơn (100 dev/200 test), 60 tình huống clarification, 40 hội thoại dài 6–12 lượt (355 lượt, 308 answer slots) và 40 câu ngoài phạm vi. Có 200 câu single test được chạy hai lần cho mỗi biến thể; mỗi lần dùng 100 case Cosmetics và 100 Olist. Gold SQL được kiểm tra qua 2.004 SQL/world checks trên ba fixture worlds; các lần gọi model chỉ chạy trên world base, không phải ba phép chạy benchmark độc lập. Hai nguồn và nested extensions là synthetic. Bộ do nhóm xây dựng; family/template overlap còn tồn tại, test chưa human-review hay sealed, nên kết quả exploratory chứ chưa phải holdout độc lập hay production guarantee.

| Suite | Baseline | Texa without retrieval and consistency | Texa with only retrieval | Texa with only consistency | **Texa** |
|---|---:|---:|---:|---:|---:|
| Single test (200 unique, 400 executions) | 356/400 (89,0%) | 350/400 (87,5%) | 361/400 (90,25%) | 348/400 (87,0%) | 365/400 (91,25%) |
| Conversation (40 dialogs; 308 answer slots/run) | Không đo bằng cấu hình này | 563/616 (91,4%) | 592/616 (96,1%) | 567/616 (92,0%) | 584/616 (94,8%) |
| Unsupported (40 cases × 2; action accuracy) | Không đo bằng cấu hình này | 67/80 (83,75%) | 69/80 (86,25%) | 75/80 (93,75%) | 76/80 (95,0%) |
| Clarification final table (60 cases × 2) | Không đo bằng cấu hình này | 119/120 (99,2%) | 119/120 (99,2%) | 120/120 (100%) | 120/120 (100%) |

Clarification có metric hành động riêng (có hỏi lại khi thiếu thông tin không); các số liệu đó chỉ áp dụng cho biến thể Texa được chạy trên suite này. Ở câu đơn, Texa đạt 91,25%, Baseline đạt 89,00%, chênh 2,25 điểm phần trăm. Trên hội thoại, Texa đạt 94,8%; Texa with only retrieval đạt 96,1%. Những kết quả này cho thấy thành phần không cải thiện đồng đều mọi suite. Xem [báo cáo benchmark đầy đủ](../data/benchmark/results/research-v3-20261106/REPORT.md).

### Cách chấm, Baseline và bộ test sau phản hồi (cập nhật 09/11/2026)

**Cách chấm.** Chấm theo bảng kết quả, không so chuỗi SQL: `benchmark.results_equal` so toàn bộ bảng (cùng số cột và thứ tự cột, bỏ qua alias; dòng so như multiset, chỉ so thứ tự khi là top-k; số trong dung sai 1e-6; NULL và duplicate được giữ).

**Điểm yếu của bộ v3 (đã biết).** Gold SQL và oracle Python do cùng một tác giả/agent viết từ cùng đặc tả (`research_v3/generate.py`); chưa có người review (`human_review: pending`); 164/200 câu test cùng mẫu SQL với dev (11 family); fixture khoảng 120 dòng tổng hợp; 20 gold rỗng và 10 gold `[[0]]`; 182/200 gold không đổi giữa ba world nên phép kiểm tra nhiều world ít phân biệt.

**Baseline câu đơn.** Trên 200 câu test × hai lần chạy đạt 356/400 (89,00%); Texa đạt 365/400 (91,25%). Cùng model `gpt-6-luna`, cùng câu hỏi và dữ liệu; Baseline nhận schema và các định nghĩa nghiệp vụ được cung cấp dưới dạng văn bản, với một lần thử sửa SQL nếu truy vấn lỗi. Kết quả v3 là exploratory; bộ test chưa được người độc lập review/seal. Baseline câu đơn không được áp dụng vào suite tương tác.

**Bộ test v4 (`data/benchmark/research_v4/`, chỉ suite câu đơn).** Chưa dùng để báo cáo điểm: hai CSV Cosmetics hiện tại không khớp hash và gold được đóng băng trong v4. Kiểm thử oracle thất bại ít nhất một câu, do đó cần khôi phục dữ liệu đúng hoặc xây lại và kiểm định bộ đáp án trước khi chạy.

### Ablation riêng cho memory và clarification

Đây là phép đo mới trên cùng research-v3, với retrieval và consistency được giữ bật cho tất cả biến thể; mỗi bảng có hai repeat. Kết quả hội thoại tính trên 308 answer slots mỗi repeat (616 slots tổng): **Texa with structured memory 84,58% (521/616)**, **Texa with only window-6 memory 85,55% (527/616)** và **Texa without memory 83,93% (517/616)**. Kết quả này chỉ cho thấy memory có ảnh hưởng nhưng window-6 chưa bị chứng minh kém hơn structured memory trên bộ hiện tại; cần bộ hội thoại lớn hơn để kết luận chắc chắn.

Clarification gồm 60 tình huống × 2 repeat (120 answer slots): **Texa with clarification 86,67% (104/120)** và **Texa without clarification 62,50% (75/120)**. Nếu chỉ xét việc hỏi đúng lúc, lần lượt là **75,00% (90/120)** và **50,00% (60/120)**. Đây là ablation exploratory trên dữ liệu tổng hợp; không dùng các con số ablation cũ vì chúng chạy sai cấu hình hoặc dùng rubric legacy.

## Kiểm thử runtime và giới hạn

- Backend **398 passed, 36 skipped**; DB integration **30 passed**; Playwright **15 passed** với provider mô phỏng và 8 session. Các test xác nhận chức năng, không đo accuracy LLM.
- Browser model thật đã đo với cấu hình Texa without retrieval and consistency: các luồng chính được thử trực tiếp; 5/6 câu có đáp án khớp, câu đếm view trả 12 thay vì 24. Chuỗi filter mobile+paid trả 62, bỏ mobile vẫn giữ paid trả 204, đổi sang desktop vẫn giữ paid trả 61; unique viewers 12 và Olist revenue 432 BRL/CSV đã đối chiếu. Đây là smoke/regression test nhỏ, không phải holdout.
- Diagnostic ngoài phạm vi: Texa đạt action accuracy 95%; các biến thể còn lại đạt 83,75–93,75%. Đây là chẩn đoán hành động (từ chối/hỏi lại/giải thích), không gộp vào SQL accuracy.
- Browser parity benchmark riêng: Texa without retrieval and consistency 15/15 câu đơn và 18/19 lượt hội thoại; đó là replay hồi quy trên các câu đã biết, không phải kiểm thử UI hay holdout.
- Với 400 lượt single, median latency Baseline/Texa lần lượt là **6,27/13,79 giây**; tổng chi phí ước tính **$0,208/$0,401**. Đây là đo trên fixture và mức giá gateway tại thời điểm chạy, không phải cam kết SLO hay dự báo chi phí production.
- Còn giới hạn: test split v3 chưa được human-review/sealed và có family overlap; v4 khắc phục overlap nhưng dữ liệu Cosmetics hiện không khớp đáp án chuẩn và chưa được review độc lập. Persona chưa xác thực bằng nghiên cứu người dùng; diagnostic không phải SQL accuracy. Cần review gold độc lập, holdout mới và load test trước khi khẳng định khả năng triển khai rộng.

Cấu hình mặc định: `TEXA_EXAMPLE_RETRIEVAL=1`, `TEXA_CONSISTENCY=1`, `TEXA_EXAMPLE_POLICY=sql_verified`. Số liệu v3 đo Texa với cả hai thành phần bật; các ablation chỉ dùng để so sánh. Các quan sát browser trước đây là lịch sử và không phải xác nhận E2E cho kết quả v3.

## Memory hội thoại

Memory giữ QuerySpec và result ID đã xác minh. Khi follow-up sửa một filter, mô hình trích xuất trường và thao tác cần thiết; server chỉ thay nhóm điều kiện tương ứng, giữ nguyên filter khác, rồi kiểm tra nguồn, kỳ, metric và snapshot trước khi chạy. Người dùng hỏi tự nhiên, không cần biết định dạng nội bộ. Câu nhiễu không được tự đổi truy vấn; tham chiếu chưa rõ thì hỏi lại. Đây là cơ chế có cấu trúc, không bảo đảm hiểu mọi cách nói hoặc ghi nhớ vô hạn.

## Chạy ứng dụng và dữ liệu

Dùng `./run.sh` cho demo hiện tại. Dừng bằng Ctrl-C hoặc `./run.sh stop`: script dừng API/Web local cùng toàn bộ container của compose project Texa, gồm PostgreSQL, Airflow, API/Web Docker và orphan containers; giữ nguyên container, image, volume và cache để lần sau khởi động nhanh. TERM/HUP hoặc lỗi startup cũng chạy cleanup; container khai báo `restart: "no"`. SIGKILL không thể được trap; nếu script bị buộc tắt, `./run.sh stop` vẫn dừng được container còn sót. Docker Desktop và các container project khác có vòng đời riêng.

Nếu chạy thủ công, publish catalog đã chọn vào đúng DB app rồi khởi động API/frontend. Benchmark phải dùng DB `texa_benchmark` riêng; không nạp fixture vào warehouse demo. `TEXA_SOURCE_PROFILE=evaluation` chỉ dùng trong runner đánh giá để mở source fixture `event_benchmark`; ứng dụng demo mặc định chỉ công bố Cosmetics/Olist. Không commit credential hoặc key; DSN demo thật giữ ngoài Git.
