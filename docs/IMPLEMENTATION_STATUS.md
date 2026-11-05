# Trạng thái triển khai — 05/11/2026

Đây là trạng thái hiện hành, thay bản kế hoạch và snapshot triển khai cũ. Scope ở [PRODUCT_SCOPE](PRODUCT_SCOPE.md), luồng code ở [ARCHITECTURE](ARCHITECTURE.md), số liệu chi tiết ở [CLASS_DEMO_CHECKS](CLASS_DEMO_CHECKS.md).

## Đã triển khai

- Catalog sản phẩm 8 metric, PostgreSQL, một nguồn mỗi query; cho phép Cosmetics và Olist. Ánh xạ purchase item của từng nguồn, không cộng trùng payment vào revenue.
- Coverage theo event/field; Olist không có sessions/viewers. Hiện cảnh báo về quần thể khách Olist và buyer/user ratio, giữ tiền gốc mỗi nguồn.
- Nested object tối đa hai key, scalar text/numeric khai báo, missing/null và dữ liệu numeric lỗi xử lý có kiểm soát; không arrays.
- LLM diễn giải candidate; resolver hỏi lại; QuerySpec validator và deterministic SQL compiler; reader role, timeout và giới hạn dòng; top-k giữ phạm vi khi tải full result.
- Structured memory với provenance, snapshot guard, tham chiếu kết quả/câu theo vị trí, xử lý noise, replay sau retry/edit.
- React/API/SSE, bảng kết quả, phạm vi/định nghĩa, SQL, retry/cancel/history; shared-demo tách browser session và khóa settings cho người tổ chức.
- Bộ v2, evaluator so kết quả thực thi, baseline direct SQL; biến thể ablation F/M6/M0/C0, protocol freeze và reporter đã có tooling.

## Bằng chứng kiểm tra

| Lớp | Kết quả đã ghi nhận | Giới hạn |
|---|---|---|
| Backend với product/metadata/shared DB opt-in | 169 đạt, 23 bỏ qua sau thêm Olist | DB riêng PostgreSQL 16.2; skips không phải passes |
| Olist contract và SQL | 5 test mới đạt, gồm query PostgreSQL trên dữ liệu nhỏ rollback | Không đo accuracy LLM trên warehouse Olist |
| Chromium E2E | 11/11; có 8 browser contexts đồng thời | Provider scripted, không phải load test model thật |
| Frontend | Build và ESLint đạt | Không xác nhận triển khai public |
| Model thật, v2 dev | Ban đầu baseline 40/41, Texa 37/41; sau tuning Texa 41/41; hội thoại 1/6 → 6/6 ở các vòng riêng | Tập dev đã dùng chỉnh prompt/memory; chưa có điểm test/ablation chính thức |

## Chưa hoàn tất hoặc chưa được chứng minh

1. Freeze phiên bản hiện tại và chạy test v2 độc lập, ablation nhiều lượt theo protocol; không dùng điểm dev như bằng chứng superiority.
2. Review độc lập dataset/gold và walkthrough với PM/PO; chưa có user study xác nhận persona.
3. Đánh giá model thật trên các câu hỏi Olist/Cosmetics thực tế, tách khỏi synthetic benchmark.
4. Triển khai website HTTPS cho lớp, đặt budget gateway và kiểm thử tải bằng provider thật; chưa cam kết số người dùng tối đa.
5. Xác nhận môi trường Docker PostgreSQL 17 nếu triển khai bản đó; lần xác minh DB local dùng 16.2.

Không nằm trong roadmap hiện tại: mở mọi DB, cross-store joins/totals, delivery/review metric, order/AOV, retention, FX, arrays, DuckDB hoặc free-SQL self-correction. Các khả năng cũ còn trong code/catalog legacy không tự trở thành scope sản phẩm.
