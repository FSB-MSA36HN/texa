# Kết quả benchmark research-v3 — 09/11/2026

Đã chạy model thật **gpt-6-luna**, cùng model và dữ liệu cho tất cả phiên bản, **hai lần lặp đầy đủ**. Không sửa runtime để tối ưu điểm trong khi đo.

## Quy mô và cách chấm

- 300 câu đơn: 100 dev, **200 test** (40 basic, 100 compositional, 60 semantic); test cân bằng 100 Cosmetics/100 Olist, 140 tiếng Việt/60 tiếng Anh.
- **60 trường hợp hỏi lại**: 30 mơ hồ + 30 câu rõ ràng đối chứng; dùng bản revision1 phù hợp catalog.
- **40 hội thoại**, dài 6–12 lượt, tổng 355 lượt, trong đó 308 lượt có bảng đáp án.
- **40 câu ngoài phạm vi**, chấm hành động xử lý đúng, tách khỏi SQL accuracy.
- Mỗi trường hợp test chạy hai lần cho mỗi phiên bản; 400 lượt câu đơn không có nghĩa là 400 câu độc lập. Không dùng dev làm điểm test.
- SQL đúng khi bảng kết quả khớp gold độc lập, không cần giống chuỗi SQL. Gold có Python oracle và SQL; 2.004 kiểm tra SQL/world đã qua. Model thật chạy trên **base world**; ba worlds không phải ba lần gọi model độc lập.
- **Baseline** cho câu đơn: LLM nhận câu hỏi, schema PostgreSQL và định nghĩa nghiệp vụ dạng văn bản; nếu SQL lỗi khi thực thi, được thử sửa một lần. Texa bổ sung semantic layer và workflow sinh, kiểm tra truy vấn.

## Kết quả chính — gộp hai lần lặp

| Phiên bản | Câu đơn đúng (400 lượt) | Bảng đúng trong hội thoại (616 lượt) | Ngoài scope: hành động đúng (80 lượt) |
|---|---:|---:|---:|
| **Baseline** | **89.00%** | Không đo bằng cấu hình này | Không đo bằng cấu hình này |
| Texa without retrieval and consistency | 87.50% | 91.40% | 83.75% |
| Texa with only consistency | 87.00% | 92.05% | 93.75% |
| Texa with only retrieval | 90.25% | 96.10% | 86.25% |
| Texa | 91.25% | 94.81% | 95.00% |

### Hỏi lại — revision1, 60 trường hợp × 2 lần

| Phiên bản | Hỏi lại đúng chính sách | Bảng kết quả cuối đúng |
|---|---:|---:|
| Texa without retrieval and consistency | 120/120 (100.00%) | 119/120 (99.17%) |
| Texa with only consistency | 120/120 (100.00%) | 120/120 (100.00%) |
| Texa with only retrieval | 119/120 (99.17%) | 119/120 (99.17%) |
| Texa | 120/120 (100.00%) | 120/120 (100.00%) |

Bản clarification gốc có 15 cặp dùng “customers” làm từ mơ hồ, trong khi catalog đã ánh xạ từ này sang users. Không dùng điểm bộ đó làm kết luận. Revision1 giữ 15 cặp thiếu kỳ và thay 15 cặp còn lại bằng “sales/doanh số” có ambiguity revenue/purchases thật trong catalog. Revision1 được đóng băng trước các lượt gọi tính phí riêng, raw cũ vẫn giữ để kiểm toán.

### Ablation memory và clarification (corrected, research-v3)

Các biến thể dưới đây giữ **retrieval và consistency bật**, chỉ thay đúng memory hoặc clarification. Mỗi biến thể có hai repeat; raw shards đã hoàn tất và được merge.

| Phiên bản | Hội thoại business accuracy (616 answer slots) | Clarification business accuracy (120 slots) | Clarification policy accuracy (120 cases) |
|---|---:|---:|---:|
| Texa with structured memory | 521/616 (84,58%) | — | — |
| Texa with only window-6 memory | 527/616 (85,55%) | — | — |
| Texa without memory | 517/616 (83,93%) | — | — |
| Texa with clarification | — | 104/120 (86,67%) | 90/120 (75,00%) |
| Texa without clarification | — | 75/120 (62,50%) | 60/120 (50,00%) |

Structured memory cao hơn without memory 0,65 điểm phần trăm; window-6 cao hơn structured memory 0,97 điểm trên bộ hiện tại. Chênh lệch nhỏ giữa hai cách memory chưa đủ để kết luận ổn định. Clarification tạo chênh lệch lớn hơn: bật hỏi lại cao hơn 24,17 điểm phần trăm ở final-table accuracy và 25 điểm ở policy accuracy. Đây là kết quả exploratory trên dữ liệu tổng hợp; không dùng các con số legacy trước đó vì chúng chạy sai cấu hình hoặc dùng rubric cũ.

## Đọc kết quả cho đúng

Texa đạt **91,25%**, cao hơn Baseline (**89,00%**) 2,25 điểm phần trăm ở câu đơn; đây là chênh lệch quan sát trên benchmark ứng viên, chưa phải bằng chứng holdout đã được review độc lập. So với Texa without retrieval and consistency, Texa tăng 3,75 điểm; so với retrieval-only chỉ tăng 1 điểm. Retrieval-only còn tốt hơn Texa ở hội thoại (96,10% so với 94,81%). Không tuyên bố Texa thắng mọi suite.

Câu đơn theo độ khó (gộp hai lần):

| Nhóm | Baseline | Texa |
|---|---:|---:|
| basic | 71/80 | 80/80 |
| compositional | 192/200 | 177/200 |
| semantic | 93/120 | 108/120 |

Lỗi còn thấy: từ chối câu compositional vẫn hợp lệ, bỏ sót yêu cầu group-by, hiểu sai một số metric/grain. Ví dụ truy vết: `rv3_test_compositional_cosmetics_shop_003`, `rv3_test_compositional_olist_marketplace_024`, `rv3_test_compositional_cosmetics_shop_019`. Đây là phân loại từ đầu ra, chưa chứng minh root cause bên trong. Lượt đầu, Texa và retrieval-only cùng 181/200 nhưng sửa được 6 ca và làm sai thêm 6 ca khác.

Hội thoại lấy **bảng kết quả từng lượt** làm metric chính. Legacy scenario-success còn phạt tham chiếu ngầm thiếu nhãn referenced_turn; số đó giữ nguyên trong artifacts nhưng không dùng làm headline. Chỉ số toàn hội thoại đúng bảng + hành động được tính lại hậu kiểm từ trace và phải xem là exploratory, không thay rubric âm thầm.

Kiểm thử hồi quy sau đo: **398 passed, 36 skipped**. Không có benchmark/app process còn chạy sau khi hoàn tất.

## Chi phí, tái lập và giới hạn

- Baseline: median câu đơn 6,27 giây; chi phí ước tính $0,2076/400 lượt. Có 402 lần gọi do SQL repair; chi phí được ước tính theo token.
- Texa with only retrieval: median câu đơn 14.40s; tổng chi phí ước tính 400 lượt $0.3433.
- Texa: median câu đơn 13.79s; tổng chi phí ước tính 400 lượt $0.4014.
- Ledger gateway cộng dồn sau phép đo: **$12,6382 đã ghi nhận** và **$9,5475 reservation chưa giải phóng**, tổng bảo thủ khoảng **$22,1857/$150**. Đây là số ledger ước tính, không phải hóa đơn provider; bao gồm các lượt trước đó.
- Benchmark dùng database riêng; PostgreSQL native đã dừng. Không khởi động Texa hay Docker sau phép đo; lần này không chạy mới browser E2E.
- Dữ liệu là fixture tổng hợp hai nguồn, nested có phần mở rộng giả lập; không đại diện toàn bộ dữ liệu thật của Olist/Cosmetics. Dev/test có chung family và đã lộ nhãn cho người xây; chưa human-review độc lập hoặc sealed. Hai repeats đo dao động model, không nhân đôi cỡ mẫu độc lập. Đây là bằng chứng exploratory cho sản phẩm trong scope, chưa phải benchmark nghiên cứu xác nhận.

Artifacts: `summary.json`, các `*-summary.json`, `r1/`, `r2/`, `clarification-revision1/`, `audit-shards/`. Summary giữ CI/bootstrap theo family và chi tiết nguồn/độ khó. Raw shards giữ byte gốc. Khi merge r2, chỉ metadata commit được chuẩn hóa do commit thêm dataset khác giữa lượt chạy; hash runtime/evaluator/catalog/active dataset giống nhau, raw không bị sửa. Nguồn chuẩn hóa và lý do được ghi trong manifest/summary.

### Thiết lập Baseline (09/11/2026)

Baseline được chạy trên 200 câu test đơn research-v3, cùng `gpt-6-luna`, hai lần (400 câu trả lời), base world, schema và snapshot catalog/verified examples giống cấu hình Texa đã đo. Chấm theo bảng kết quả, không so chuỗi SQL. Baseline nhận định nghĩa nghiệp vụ dạng văn bản; nếu SQL lỗi khi thực thi, được thử sửa một lần theo loại lỗi an toàn. Baseline không dùng QuerySpec, compiler, validator hay hỏi làm rõ của Texa.

| Cấu hình câu đơn | Đúng / tổng | Accuracy | Basic | Compositional | Semantic |
|---|---:|---:|---:|---:|---:|
| **Baseline** | **356/400** | **89.00%** | **71/80** | **192/200** | **93/120** |
| Texa — semantic layer và workflow đầy đủ | 365/400 | 91.25% | 80/80 | 177/200 | 108/120 |

Texa cao hơn Baseline 9/400 câu trả lời (2,25 điểm phần trăm). Đây là kết quả exploratory vì bộ v3 chưa được human-review/sealed.

Kết quả và summary có thể kiểm toán trong [`research-v3-baselines-20261109/`](../research-v3-baselines-20261109/). Snapshot catalog và examples khớp với context Texa trong phép đo. Baseline câu đơn không được chấm trên hội thoại, clarification hay ngoài phạm vi; không gán các kết quả Texa của những suite đó cho Baseline.

Tái lập (cần credentials riêng, ngân sách và PostgreSQL native đã chuẩn bị):

```sh
backend/.venv/bin/python backend/eval/run_v3_baseline_queue.py --run-dir .runtime/baselines-v3-1109 --workers 4
# Kết quả Texa dùng raw run đóng băng trong backend/eval/results/research-v3-20261106/r1/ và r2/.
```

Commit đóng băng dataset chính: `83d008d`; runner sharding: `8fbdcef`; clarification revision1: `37adb62`. Report utilities `report_research_v3.py` rồi `finalize_research_v3.py` tái tạo báo cáo máy từ kết quả lưu local. Không có credential trong artifacts.
