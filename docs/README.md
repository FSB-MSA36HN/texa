# Tài liệu Texa — 05/11/2026

Scope thống nhất: Cosmetics + Olist đã cấu hình trước, một nguồn mỗi query, PostgreSQL, 8 metric, nested scalar tối đa hai key. Không mở lại hướng chuẩn hóa mọi DB hoặc metric giao hàng/review.

| Đọc theo thứ tự | Mục đích |
|---|---|
| [PRODUCT_SCOPE](PRODUCT_SCOPE.md) | Hợp đồng sản phẩm hiện tại |
| [ARCHITECTURE](ARCHITECTURE.md) | Luồng code thực sự đang chạy, memory và giới hạn |
| [IMPLEMENTATION_STATUS](IMPLEMENTATION_STATUS.md) | Tính năng có sẵn và việc còn lại |
| [EVALUATION](EVALUATION.md) | Baseline, execution accuracy, dataset và cách đọc kết quả |
| [CLASS_DEMO_CHECKS](CLASS_DEMO_CHECKS.md) | Chạy demo/E2E và chi tiết các vòng dev thực tế |
| [ABLATION_STUDY_PLAN](ABLATION_STUDY_PLAN.md) | Thiết kế thí nghiệm component và việc cần làm |
| [ABLATION_STUDY_RESULTS](ABLATION_STUDY_RESULTS.md) | Phân biệt tooling/offline/dev với ablation chưa chạy |
| [Hướng dẫn CLI ablation](../backend/eval/ABLATION_README.md) | Lệnh chạy/freeze/report |
| [Presentation](../presentation/OUTLINE.md) | Dàn ý và kịch bản hiện hành |

Kế hoạch cũ `PLAN.md`, `PLAN_REFINEMENT_EVENT_CONVERSATIONAL_QA.md` và PDF proposal cũ đã được bỏ khỏi cây tài liệu hiện hành; lịch sử vẫn xem được qua Git. Không dùng các mô tả cũ về đa nguồn, FX hoặc golden-only để trình bày sản phẩm hiện tại.

Số liệu model thật ở đây là các vòng phát triển ngày 04/11/2026, trước khi bật lại Olist ngày 05/11. Các bước tối ưu trên dev chưa được đánh giá bằng test độc lập. Tài liệu cập nhật không đồng nghĩa vừa chạy lại benchmark hoặc thay đổi dữ liệu/gold.
