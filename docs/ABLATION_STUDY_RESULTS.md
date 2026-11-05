# Trạng thái ablation study

Ngày cập nhật: 05/11/2026. Xem [tổng quan đánh giá](EVALUATION.md) và [kết quả kiểm tra demo](CLASS_DEMO_CHECKS.md) để biết kết quả model thật mới nhất. Hướng dẫn CLI và protocol còn hiệu lực nằm trong [ABLATION_README](../backend/eval/ABLATION_README.md).

## Đã hoàn tất

- Đã triển khai F/M6/M0/C0, suite synthetic, runner live/gold/dry-run, protocol freeze và reporter. Giữ nguyên hành vi mặc định F, QuerySpec/compiler/validation và giới hạn dữ liệu.
- Gold SQL và backend integration được kiểm tra offline; đây là kiểm chứng fixture/code, không phải model accuracy.
- Latest full backend regression: **169 passed, 23 skipped**; scripted Playwright E2E: **11 passed**. Các lượt dùng model giả không phải kết quả độ chính xác model.

## Model thật trên dev — exploratory, các phiên bản riêng

Cùng `gpt-6-luna`, gateway và benchmark v2 synthetic (96 events, 41 dev cases), direct SQL đạt **40/41** và Texa ban đầu **37/41**; cả hai SQL thực thi 41/41. Texa đạt **1/6** hội thoại dev hoàn toàn đúng ở vòng ban đầu. Sau hướng dẫn chung phân biệt filter/breakdown, Texa đạt **41/41** câu đơn dev và **3/6** hội thoại ở lần chẩn đoán; sau cập nhật date/reference-memory riêng, đạt **6/6** hội thoại dev, **19/19** lượt. Đây là các phiên bản/chạy khác nhau, không gộp thành một phép so sánh trực tiếp; ngày/memory được cập nhật sau vòng prompt filter. Xem bảng, artifacts và giới hạn diễn giải ở `CLASS_DEMO_CHECKS.md`.

## Chưa hoàn tất

- Chưa chạy holdout **63 câu test** với model thật.
- Chưa chạy controlled full ablation **F/M6/M0/C0** với repeats theo protocol trên test. Dev exploratory không thay thế ma trận này.
- Chưa có xác nhận PM/PO độc lập cho nghĩa nghiệp vụ/gold.

Không diễn giải các số benchmark synthetic là accuracy trên Olist: fixture không phải dữ liệu Olist. Phạm vi sản phẩm cấu hình là Cosmetics + Olist, một source, tám metric và nested scalar tối đa hai cấp khóa.
