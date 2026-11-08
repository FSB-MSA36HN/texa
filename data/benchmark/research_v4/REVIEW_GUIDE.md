# Hướng dẫn review bộ test research_v4 (dành cho hai reviewer độc lập)

Mục tiêu: xác nhận bằng người rằng *đáp án chuẩn (gold)* đúng với câu hỏi. Máy đã kiểm tra gold SQL trên warehouse
khớp với oracle tính từ CSV thô (`backend/eval/validate_research_v4.py`), nhưng máy không đánh giá được câu hỏi có
mơ hồ hay quy ước nghiệp vụ có hợp lý hay không. Đó là việc của người review.

## Cách làm

1. Mỗi reviewer chỉ mở file của mình (`AUDIT_A.csv` hoặc `AUDIT_B.csv`). **Không trao đổi và không xem file của người kia.**
2. Đọc `GLOSSARY.md` một lần. Với mỗi dòng, đọc `question`, rồi đối chiếu với `gold_columns` và `gold_rows`.
   `gold_sql` chỉ để tham khảo; đánh giá dựa trên việc bảng kết quả có trả lời đúng câu hỏi hay không.
3. Điền cột `verdict` bằng đúng một trong ba giá trị:
   - `correct`: câu hỏi có một cách hiểu hợp lý duy nhất và bảng gold trả lời đúng.
   - `ambiguous`: một người đọc hợp lý có thể mong đợi bảng khác (ghi lý do vào `notes`).
   - `wrong`: bảng gold không trả lời câu hỏi.
4. Cột `flags` chỉ ra các trường hợp hay gây tranh cãi:
   - `null_group`: bảng có nhóm giá trị thiếu (NULL), ví dụ event vòng đời của Olist không có danh mục sản phẩm.
     Hãy cho biết có hợp lý khi một người dùng nghiệp vụ thấy nhóm này trong kết quả không.
   - `top_k`: xếp hạng, kiểm tra cách xử lý đồng hạng và việc có ít hơn k dòng.
   - `single_row`: một con số; kiểm tra khoảng thời gian và bộ lọc được hiểu đúng.
5. Chạy `python backend/eval/audit_stats.py data/benchmark/research_v4/AUDIT_A.csv data/benchmark/research_v4/AUDIT_B.csv`
   để lấy tỷ lệ đồng thuận, Cohen's kappa và khoảng tin cậy Wilson. Các ca bất đồng được người thứ ba phân xử.

## Sau khi review

- Case bị `wrong`/phân xử là sai: sửa generator hoặc loại case, sinh lại, chạy lại validator và lấy mẫu review lại.
- Chỉ khi có đủ hai reviewer độc lập, kết quả thống kê chấp nhận được và bộ test được đóng băng (SHA256SUMS), mới được
  đổi `manifest.yaml` sang `status: sealed`, `review_status: human_reviewed_sealed` và điền `human_reviewers`.
  Trước đó bộ test vẫn là *exploratory*.
