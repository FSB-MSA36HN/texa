# Product contract: conversational product analytics

## Người dùng và công việc

PM/PO theo dõi một sản phẩm thương mại điện tử: hỏi số người dùng/người mua, lượt xem/lượt mua, doanh thu ghi nhận; đổi kỳ, filter hoặc breakdown qua hội thoại. Persona là giả thuyết, chưa có user study. Câu trả lời cần hiện định nghĩa, nguồn, kỳ thời gian và filter. Không suy luận nguyên nhân nhân quả từ tương quan.

## Capabilities

- PostgreSQL, một dataset mỗi query trong catalog sản phẩm; Cosmetics cho dữ liệu thật, `event_benchmark` cho fixture tổng hợp, không cộng hai nguồn.
- 8 metric: `events`, `users`, `sessions`, `viewers`, `buyers`, `purchases`, `revenue`, `buyer_conversion_rate`.
- `purchases` đếm item events, không phải orders. `sessions` chỉ có khi nguồn có ID. Buyer/user ratio là tỷ lệ trong kỳ, không phải funnel có thứ tự.
- Event grain cố định: một hàng/một event; ID event duy nhất trong nguồn. Import phải báo lỗi duplicate, không âm thầm nhân đôi.
- Nested object dưới `ep`/`up`: tối đa hai key, ví dụ `ep.device.type`. Chỉ path trong catalog; scalar text hoặc numeric có khai báo cast. Missing và JSON null trở thành SQL NULL. Không expand array.
- Top-k hỗ trợ một metric và breakdown không phải thời gian: metric giảm dần, key tăng dần khi hòa. Top-k là phạm vi truy vấn, không phải cắt preview; tổng trên kết quả chỉ là tổng trong các nhóm top-k.
- Thời gian theo event UTC date. QuerySpec `between` dùng start/end DATE bao gồm cả ngày cuối để tương thích UI hiện có; tương đương `[start, end + 1 ngày)`. Benchmark phải cố định mốc dữ liệu cho relative date.
- Không có order/AOV, FX, retention, Olist delivery/review, join đa doanh nghiệp, tự sinh catalog từ tài liệu hoặc tích hợp nhiều DB trong bản đầu.

## Vận hành

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

Kết quả tổng hợp là bằng chứng cho fixture/workload được công bố; không chứng minh đúng cho mọi DB hoặc người dùng. Chưa có điểm model thật cho đến khi chạy và lưu thí nghiệm. Dataset tổng hợp không được mô tả là quan sát người dùng thật.
