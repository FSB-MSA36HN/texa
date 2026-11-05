# Product contract: conversational product analytics

Cập nhật 05/11/2026. Đây là scope hiện hành; [kiến trúc](ARCHITECTURE.md) và [đánh giá](EVALUATION.md) mô tả cách triển khai/kiểm chứng.

## Người dùng và công việc

PM/PO theo dõi một sản phẩm thương mại điện tử: hỏi số người dùng/người mua, lượt xem/lượt mua, doanh thu ghi nhận; đổi kỳ, filter hoặc breakdown qua hội thoại. Persona là giả thuyết, chưa có user study. Câu trả lời cần hiện định nghĩa, nguồn, kỳ thời gian và filter. Không suy luận nguyên nhân nhân quả từ tương quan.

## Capabilities

- PostgreSQL, một dataset mỗi query trong catalog sản phẩm; Cosmetics và Olist là hai nguồn dữ liệu thật được cấu hình trước; `event_benchmark` là fixture tổng hợp. Người dùng chọn một nguồn cho mỗi câu hỏi; không cộng hoặc join hai nguồn.
- 8 metric: `events`, `users`, `sessions`, `viewers`, `buyers`, `purchases`, `revenue`, `buyer_conversion_rate`.
- Olist dùng các event lifecycle đã được ETL thành event rows; không thêm cơ chế chuẩn hóa DB tự động. `order_purchased` ánh xạ sang purchase item. Olist không có session hoặc product view nên từ chối hai metric đó, không trả 0.
- `purchases` đếm item events, không phải orders. `sessions` chỉ có khi nguồn có ID. Buyer/user ratio là tỷ lệ trong kỳ, không phải funnel có thứ tự. Olist chỉ có khách đã đặt hàng, không có toàn bộ visitor; tỷ lệ này không đo chuyển đổi visitor thành buyer. Doanh thu Olist chỉ cộng giá item trên `order_purchased` (BRL), không cộng thêm payment hoặc freight.
- Event grain cố định: một hàng/một event; ID event duy nhất trong nguồn. Import phải báo lỗi duplicate, không âm thầm nhân đôi.
- Nested object dưới `ep`/`up`: tối đa hai key, ví dụ `ep.device.type`. Chỉ path trong catalog; scalar text hoặc numeric có khai báo cast. Missing và JSON null trở thành SQL NULL. Không expand array.
- Top-k hỗ trợ một metric và breakdown không phải thời gian: metric giảm dần, key tăng dần khi hòa. Top-k là phạm vi truy vấn, không phải cắt preview; tổng trên kết quả chỉ là tổng trong các nhóm top-k.
- Thời gian theo event UTC date. QuerySpec `between` dùng start/end DATE bao gồm cả ngày cuối để tương thích UI hiện có; tương đương `[start, end + 1 ngày)`. Benchmark phải cố định mốc dữ liệu cho relative date.
- Không có order/AOV, FX, retention, Olist delivery/review, join đa doanh nghiệp, tự sinh catalog từ tài liệu hoặc tích hợp nhiều DB trong bản đầu.

### Tám metric nghĩa là gì?

Đây là tám phép đo được định nghĩa sẵn, không phải chỉ tám câu hỏi. Mỗi phép đo có thể hỏi theo kỳ, filter hoặc breakdown được hỗ trợ. Không phải mọi nguồn đều có đủ tám phép đo.

| Metric | Cách hiểu | Cosmetics | Olist |
|---|---|---|---|
| events | Số event được ghi nhận | Có | Có, gồm lifecycle/payment/review event |
| users | Số user duy nhất có event trong kỳ | Có | Có, chỉ quần thể khách đã đặt hàng |
| sessions | Số session duy nhất | Có | Không ghi nhận |
| viewers | Số user đã xem sản phẩm | Có | Không ghi nhận |
| purchases | Số purchase item events | Có | Có, không phải số order |
| buyers | Số user duy nhất có item purchase | Có | Có |
| revenue | Tổng revenue trên item purchase | USD | BRL, không cộng payment/freight |
| buyer_conversion_rate | buyers/users được quan sát trong kỳ | Có, không phải funnel tuần tự | Tính được tỷ lệ quan sát; không phải visitor conversion |

Các phép so sánh giữa hai nguồn không cùng quần thể/event/currency; phiên bản này không thực hiện truy vấn so sánh/gộp hai nguồn. Tám metric là phạm vi có thể kiểm thử của đồ án; mức đủ cho công việc PM/PO vẫn cần walkthrough xác nhận.

## Vận hành

### Bật lại Olist trên website đã có dữ liệu

Thay đổi catalog không xóa hoặc nạp lại event. Nếu Olist đã có trong `analytics.source_registry` và có metadata, publish catalog sản phẩm mới rồi tải lại trang. `run.sh` có bước publish khi khởi động; nếu chạy API riêng, chạy lệnh publish bên dưới trong cùng môi trường cấu hình DB với API. Nếu Olist chưa được nạp, dùng pipeline Olist hiện có trong README; không nạp benchmark tổng hợp vào DB demo.

Ví dụ trong scope: doanh thu Olist theo tháng hoặc danh mục; số item mua, người mua, khách được quan sát, số event. Không bật lại metric giao trễ, review, order/AOV hoặc truy vấn gộp hai cửa hàng. “Mọi nguồn” là chưa chọn nguồn; câu hỏi phải nêu một nguồn hoặc Texa hỏi lại, không ngầm cộng cả hai.

Catalog mới không tự thay catalog đã publish trong DB. Sau khi kiểm tra workload/dữ liệu, publish rõ ràng:

```sh
cd backend
uv run texa catalog publish ../catalog/product_events.yaml
```

Regression nguồn cũ cần publish `../catalog/ecommerce.yaml` trong DB regression riêng; không dùng điểm golden cũ làm SQL result accuracy. Không thay catalog trên DB có lượt chat đang chạy.

Kiểm tra catalog không cần DB:

```sh
backend/.venv/bin/python -c "import yaml; from texa.catalog import validate_catalog; validate_catalog(yaml.safe_load(open('catalog/product_events.yaml')))"
```

## Đánh giá và giới hạn tuyên bố

Benchmark versioned gồm schema/snapshot, câu hỏi, action, SQL và kết quả chuẩn; dev/test không chia paraphrase cùng scenario family. Direct LLM baseline nhận cùng schema/metric definitions. SQL lỗi, timeout và false refusal không bị loại khỏi mẫu số.

Kết quả tổng hợp là bằng chứng cho fixture/workload được công bố; không chứng minh đúng cho mọi DB hoặc người dùng. Kết quả model thật trên dev được ghi trong `CLASS_DEMO_CHECKS.md`; chưa phải điểm test độc lập. Dataset tổng hợp không được mô tả là quan sát người dùng thật.
