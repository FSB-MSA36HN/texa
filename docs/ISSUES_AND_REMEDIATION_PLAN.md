# Texa — Vấn đề tồn đọng và kế hoạch sửa tận gốc

Cập nhật: 05/11/2026. Trạng thái: **đã implement các phần code chính; các gate đánh giá còn mở được ghi rõ bên dưới**. Phân tích root cause ban đầu tại `4bde1ac`; kết quả code mới được tách riêng trong bảng tiến độ và artifacts dưới đây. File này được bổ sung theo yêu cầu tracking, bên cạnh hai tài liệu sản phẩm hiện hành.

## Bổ sung ngày 06/11/2026

### Vòng sửa theo yêu cầu baseline chỉ nhận schema

**Giao thức được chốt trước lần đo tiếp theo:** B0 nhận câu hỏi và schema vật lý PostgreSQL; không nhận catalog, định nghĩa metric, event-role mapping, gold SQL, tên cột đáp án hay business contract. B1 dùng cùng đầu vào, thêm lịch sử câu hỏi/kết quả thực tế và quyền hỏi người dùng làm rõ; cùng các tình huống hội thoại, nguồn mâu thuẫn, yêu cầu ngoài phạm vi với Texa. B0R là đối chứng riêng có ví dụ đã kiểm chứng, không gọi nó là baseline thuần. Texa nhận semantic catalog vì đó là một thành phần của sản phẩm. Đây là so sánh hai hệ thống có lượng tri thức khác nhau, không phải chứng minh cùng một LLM trở nên thông minh hơn.

**Không so trực tiếp với 96,7% cũ:** prompt cũ còn nhận định nghĩa nghiệp vụ, catalog và output aliases từ annotation. Giữ nguyên artifact cũ và ghi rõ giao thức. Không sửa gold hoặc chọn câu chỉ để baseline thấp. Phép đo mới phải dùng cùng model, dữ liệu, câu hỏi, thời điểm và rubric kết quả. Chấm toàn bộ bảng, giữ số cột/thứ tự vai trò, duplicate, NULL, tolerance và ordering khi được yêu cầu; không bắt tên alias giống nhau. Compliance tên cột được báo riêng. Không chiếu bỏ cột sai để tăng điểm.

**Các lỗi đã kiểm tra trực tiếp trên raw trace:**

| Bằng chứng | Kết luận cần sửa |
|---|---|
| `c16`, `c37`: SQL có `WHERE event_name='purchase'`, output alias `events` thay vì `purchases`; supplementary full-table đúng | Đây là khác alias, **không phải** compiler đếm toàn bộ event. Giữ riêng lỗi output contract, tránh sửa compiler đang đúng. |
| `c49`: tự thêm `item_category='Cosmetics'`, bỏ category breakdown; binder từ chối vì giá trị không tồn tại | Diễn giải vai trò nguồn/dimension sai. Cần ground các ràng buộc vào catalog và dữ liệu, trả lỗi có cấu trúc cho bounded re-resolution; không xóa filter người dùng chỉ để truy vấn chạy. |
| Browser: hai câu đếm lượt xem/người xem Cosmetics bị từ chối | Refusal chưa có bằng chứng capability. Query và refusal phải dùng chung capability contract; không tự biến một spec hợp lệ thành bằng chứng đúng ý. |
| `x02`, T10/v4: SQL trả revenue/purchases; writer được yêu cầu tính AOV bằng revenue/purchases | Sai grain: purchase rows là item lines, không phải orders. Cần requested measure contract độc lập với selected metric và kiểm trước query/writer. |
| `x11`, T01/T11: source conflict bị từ chối | Policy bắt buộc hỏi nguồn phải được quyết định ngoài voting và trước nhánh refusal. |
| `q03`, `q10`: hỏi thêm kỳ nhưng oracle chỉ có nguồn | Phân loại protocol/oracle mismatch riêng; không tự coi đây là bằng chứng Texa hiểu sai hoặc bỏ lỗi khỏi mẫu số. |

**Căn cứ kiến trúc đã đọc lại:** [dbt Semantic Layer architecture](https://docs.getdbt.com/docs/use-dbt-semantic-layer/sl-architecture) tập trung metric/semantic model trong YAML và dịch metric query thành SQL; [Snowflake Semantic Views overview](https://docs.snowflake.com/en/user-guide/views-semantic/overview) tách ý nghĩa nghiệp vụ khỏi schema vật lý, giữ định nghĩa nhất quán. Texa áp dụng contract/version/capability dùng chung ở ranh giới diễn giải → bind → compiler. Requested intent, refusal evidence và bounded repair là thiết kế cụ thể của Texa dựa trên các nguyên tắc này, **không phải** tính năng được khẳng định có nguyên xi ở hai nhà cung cấp. LLM vẫn có thể diễn giải sai; contract không thay thế đánh giá độc lập.

**Nghiệm thu:** hồi quy trên measure/grain không tương thích, supported composition, source conflict dù model/voting chọn refusal, nguồn đổi tên và biến thể metric; chạy lại cùng các câu browser thực tế cho cả B1 và Texa, giữ lỗi/timeout trong mẫu số, báo accuracy/clarification/refusal/latency/cost riêng. Các câu đã xem là regression, chưa phải holdout. Retrieval/consistency vẫn tắt mặc định đến khi có bằng chứng qua gate.

- Hoàn tất compiler metric-support domain, retrieval bank và selective self-consistency có cờ tắt mặc định; chi tiết tại `TEXT2SQL_ACCURACY_IMPLEMENTATION_PLAN.md`, mục 10.
- Công cụ đánh giá đã thêm preflight typed business contract, mẫu số theo authored answer slots kể cả khi lỗi, JSON hóa kết quả PostgreSQL trong baseline history, trace mọi lượt và hash-pinned annotation erratum. Giữ nguyên raw và snapshot; không sửa gold để tăng điểm.
- Câu đơn dev mới: B0 29/30, T00 27/30, T10 26/30, T01 28/30, T11 27/30 theo primary protocol sau erratum. Alias-insensitive supplemental: B0/T00/T01 cùng 29/30. Chưa chứng minh hai thành phần mới tăng accuracy; chưa bật mặc định.
- Raw conversation comparison đầu không hợp lệ do lỗi adapter Decimal/date và mẫu số. Chạy lại riêng sau sửa; không dùng lỗi adapter làm bằng chứng model baseline kém.
- Còn mở: human-reviewed sealed holdout/cỡ mẫu đủ, ambiguity ngoài glossary, B1 clarification oracle coverage, long-memory/generalization, classroom load và triển khai nhiều worker. Không đưa kết quả dev một lượt thành production accuracy.

### Lỗi còn mở sau dev matrix và browser thật

| Vấn đề đã quan sát | Root cause/phạm vi bằng chứng | Hướng sửa hệ thống tiếp theo |
|---|---|---|
| Browser từ chối sai hai câu view/viewers của Cosmetics | Primary interpretation có thể nhận ra metric/composition sai hoặc tự khẳng định capability thiếu. Guard kiểm QuerySpec khi có spec; không chứng minh lý do refusal bằng metadata khi model chỉ trả unsupported. Hai ca SQL độc lập xác nhận dữ liệu có đáp án. | Chuẩn hóa IntentContract gồm measure, grain, source, period và evidence; refusal cũng phải có reason code + capability evidence được server xác minh. Dùng cùng catalog/binder cho query lẫn refusal; positive capability mâu thuẫn thì yêu cầu resolve lại/hỏi rõ trong budget, không phát thông báo thiếu dữ liệu do LLM bịa. Composition events + event filter phải được adjudicate bằng catalog, không regex riêng cho câu benchmark. |
| Retrieval-only trả lời AOV bằng metric khác ở diagnostic x02 | Ví dụ có thể làm model chọn một metric hợp lệ nhưng sai yêu cầu. Compiler/SQL validation chứng minh query an toàn và hợp lệ, không chứng minh metric đúng với câu hỏi. Hiện tượng đã quan sát trong một lượt, chưa xác định toàn bộ causal attribution. | Governed semantic operation/grain contract, gồm cả operation chưa hỗ trợ như order-level average; tách requested intent khỏi bound plan và kiểm entailment/coverage trước compile. Mismatch phải hỏi rõ/từ chối có bằng chứng. Review relevance theo nhãn, contrastive supported/unsupported pairs, giữ retrieval tắt đến khi qua regression và holdout. Không hardcode thay AOV thành một con số/SQL hay thêm điều kiện chỉ cho x02. |
| Consistency có ca nguồn xung đột chuyển sang refusal thay vì form | Action correctness của candidate/conservative fallback chưa bảo toàn mọi policy hỏi lại; cùng model có thể đồng thuận sai. Có regression unit bảo vệ clarification hợp lệ khỏi query majority, nhưng không bảo đảm mọi primary sẽ đề xuất đúng action. | Tách policy quyết định bắt buộc từ catalog/UI/text constraints khỏi sampling; consistency chỉ chọn giữa những plan đáp ứng policy đó. Bổ sung contract tests từ metadata biến đổi và human-adjudicated ambiguity suite, không xem majority là bằng chứng đúng. Giữ consistency tắt. |
| Một số B1 oracle mismatches; diagnostic hỏi lại bị chấm trượt | Adapter chỉ có choices cho source/metric/period; artifact cũ không lưu trường đang hỏi. Diagnostic chấm action đầu tiên theo rubric nghiêm, hỏi lại an toàn không bằng refusal đúng contract. | Oracle tổng quát dựa trên authored user-intent contract, chỉ trả field được hỏi; không suy ý định từ kết quả gold. Lưu ask fields và reason theo loại protocol/model/policy. Review rubric trước seal và báo riêng failure types; không âm thầm loại ca trượt hoặc sửa rubric sau khi biết bên nào thắng. |
| Candidate nhỏ, nested Olist synthetic, chưa có người thẩm định | 60 câu đơn/24 clarification records/9 hội thoại/12 diagnostics dưới cỡ mẫu thiết kế; test đã được người viết nhìn thấy. | Thu câu hỏi thực tế theo strata chốt trước, review domain/gold độc lập, seal holdout mới và chạy ba repeats. Không tạo câu khó chỉ để baseline thấp hoặc xem 3 worlds là 3 lần số mẫu độc lập. |

Kết quả hiện hành: backend **323 passed, 36 skipped**; Playwright **15/15** với mock. Browser thật: **19/21** câu có đáp án bảng khớp SQL viết độc lập trên 23 lượt hỏi; memory ordinal đúng sau 13 kết quả + noise. Đây là scripted diagnostic, không phải production accuracy. Các lỗi trên là rollout blockers, không được bù bằng điểm trung bình. Chi tiết bằng chứng ở `accuracy-browser-20261106/browser-check.json`, `accuracy-conversation-20261106-v3/` và `accuracy-diagnostic-20261106-v4/`.

## Tiến độ sau implementation

Các root cause/file:line phía dưới mô tả mốc trước sửa; dùng bảng này để đọc trạng thái hiện tại. Các artifact cũ giữ nguyên. Các commit được tách theo semantic contract, provider/budget, memory/UX, regression và evaluation trên `main`.

| Vấn đề | Đã thực hiện | Gate còn mở |
|---|---|---|
| 01–02 Semantic/capability | Binder dùng chung cho model/form/QuerySpec; enum complete/open/absent; concept → raw value theo nguồn; filter trace; demo/evaluation profiles | Gold cần reviewer thứ hai; thêm biến thể thực tế từ user traffic |
| 03 Memory | Structured reference + reducer keep/set/clear; registry đầy đủ phía server, prompt có budget; ordinal không renumber; version/edit guards | Không cam kết hiểu mọi paraphrase; chưa có holdout memory mới được thẩm định |
| 04 Clarification | Policy mơ hồ từ catalog, thiếu kỳ và xung đột nguồn phải hỏi lại | Policy nghiệp vụ vẫn hữu hạn; cần review các ambiguity ngoài glossary |
| 05–06 Suggestions/source | Gợi ý qua validation/capability; tên nguồn không tự ghi đè ý nghĩa; bất đồng UI/model/text phải chọn; đồng bộ picker | Tiếp tục thu thập câu hỏi thật; việc LLM hiểu sai vẫn có thể xảy ra |
| 07–08 Evaluation | Business result vs output contract tách riêng; frozen provenance; oracle chỉ cấp field đang được hỏi; raw run gián đoạn giữ nguyên | Bộ regression đã nhìn thấy, chưa phải holdout; câu trả lời discussion chưa có contract chấm tự động |
| 09 Reliability | Guard chi phí dùng chung theo attempt/process, giữ reservation khi usage chưa rõ; SDK retry tắt; timeout/admission hữu hạn | Single worker; RUNS/SSE và semaphore chưa phải hệ phân tán |
| 10 Latency | Có đo queue, SQL-ready và end-to-end; thử 8 phiên model thật | Chưa tối ưu latency hoặc chốt SLO; SQL-ready chưa đồng nghĩa UI đã render |
| 11 Locale | Locale theo hội thoại; label và ba loại cảnh báo availability có renderer từ code/params | Một số lỗi/caveat legacy ngoài đường sản phẩm chính còn fallback English |
| 12 Title | Edit cập nhật title tự sinh; giữ title người dùng đặt | Giữ regression khi thay persistence/rewind |

Bằng chứng mới nằm tại `data/benchmark/results/remediation-20261105/`:

- Backend full suite: **261 passed, 12 skipped**; kết quả cuối ghi trong `verification.json`.
- Playwright: **15/15 passed**, gồm tám phiên browser dùng provider mô phỏng; không dùng số này làm accuracy của LLM.
- Model thật: tám request đồng thời đều đúng số/tiền tệ, tám lượt đọc chéo phiên đều trả 404; end-to-end p50 **21,2 giây**, p95 **36,5 giây**. Chỉ là sanity test một lượt, chưa phải sức chứa production.
- Model thật, một hội thoại: **12/12** truy vấn trả đúng; sau câu xã giao, “kết quả thứ hai” quay lại Olist 01/2018, đủ **31/31 dòng** khớp SQL độc lập. Không biến một hội thoại thành tỷ lệ chính xác tổng quát.
- Benchmark mới: **v3: Texa 35/48 = 72,9%; B0 41/48 = 85,4%** trên 16 câu test × 3 lần; regression đã nhìn thấy, không phải holdout. Memory comparison không hợp lệ vì discussion chưa chấm được; clarification v3 không hợp lệ do thiếu oracle kỳ. Clarification v4: **F 6/6 (100%), C0 1/6 (16,7%) trên hai tình huống × ba lần; chỉ là regression nhỏ đã nhìn thấy, không suy rộng**. Không gộp với formal cũ. Lượt `initial-protocol-attempt/` không đủ điều kiện so sánh: thiếu oracle kỳ báo cáo, discussion chưa có SQL-result contract, và single/F/r2 bị timeout nên matrix chưa hoàn tất. Không xóa lần chạy này.

## 1. Kết luận và phạm vi

Luồng truy vấn rõ nguồn/kỳ/metric hoạt động trên các mẫu warehouse đã đối chiếu. Điểm yếu chính nằm ở **liên kết ngôn ngữ với semantic contract**, **phân giải tham chiếu hội thoại**, **các đường vào không dùng chung kiểm tra**, và **mức bằng chứng đánh giá**. Chỉ demo có hướng dẫn trong phạm vi đã kiểm tra; chưa khẳng định tải toàn lớp hoặc độ đúng trên mọi câu hỏi.

Giữ nguyên PostgreSQL, Cosmetics + Olist, một nguồn mỗi truy vấn, tám metric, nested scalar có giới hạn. Tận dụng catalog, QuerySpec, compiler và PostgreSQL hiện có; chưa cần thay bằng framework agent, vector database hay bộ chuẩn hóa mọi database.

Mục tiêu là ngăn cả **lớp lỗi** bằng contract và kiểm tra bắt buộc. Các bất định ngôn ngữ phải chuyển thành hỏi lại có kiểm soát; không hứa LLM sẽ hiểu đúng mọi câu sau khi sửa.

### Bằng chứng cần giữ nguyên

| Lần đo | Kết quả và giới hạn |
|---|---|
| Formal: 63 câu test × 3 lần | Texa 143/189 = 75,7%; baseline 130/189 = 68,8%. CI95% chênh lệch −14,5…+26,1 điểm %, chưa chứng minh Texa hơn. |
| Audit bảng kết quả | 40/59 lỗi baseline chỉ do cột thừa; phép chiếu cột hậu nghiệm đưa baseline lên 170/189 = 89,9%. Không thay ngược metric chính. |
| Memory: 12 hội thoại × 3 lần | Scenario success F/M6/M0 = 63,9%/66,7%/19,4%; F chưa thắng cửa sổ sáu lượt. |
| Clarification: 20 scenario × 3 lần | F 85%; C0 51,7%; lợi ích chủ yếu từ hỏi kỳ báo cáo. |
| Diagnostic đa nguồn | Texa 31/33, baseline 19/33; dev tiếng Anh, fixture 17 dòng, một lần chạy. Điểm hội thoại của runner này chưa so sánh công bằng. |
| Hai vòng browser E2E | Truy vấn mẫu, CSV 31 dòng, edit, cancel/retry, lịch sử và chuyển chat đã có bằng chứng. Tham chiếu tiếng Việt, gợi ý và một số UX còn lỗi; chưa đo tải cả lớp. |

Artifacts: `data/benchmark/results/study-20261105/`, `multisource-20261105/`, `live-e2e-20261105/`, `live-e2e-extended-20261105/`.

**Quy ước:** P0 = nguy cơ sai nghĩa/sai kết luận đánh giá; P1 = cần xử lý trước demo tự do; P2 = cải thiện trải nghiệm/vận hành. “Đã xác nhận” có trace/code; “cần điều tra” chưa đủ bằng chứng kết luận nguyên nhân.

## 2. Thiết kế đích dùng chung

```text
User message + UI source + locale + result registry
  → Structured intent/reference resolver
  → Semantic binder: metric/dimension/event/value → catalog IDs + source values
  → Dialogue reducer: target result + keep/set/clear từng slot
  → Capability + ambiguity policy
      ├─ thiếu/mâu thuẫn/mơ hồ → clarification có lựa chọn hợp lệ
      ├─ ngoài scope/thiếu dữ liệu được ghi nhận → giải thích bằng reason code
      └─ đủ điều kiện → QuerySpec đã validate → compiler → PostgreSQL read-only
  → facts có provenance → bảng/nhận xét + scope hiển thị thống nhất
```

- Resolver có thể dùng LLM với output schema; **code quyết định** ID nào tồn tại, trường nào được kế thừa và truy vấn nào hợp lệ. Structured output không chứng minh đúng nghĩa [S1, S2]. Ưu tiên tích hợp vào lượt interpret hiện có; chỉ thêm lượt resolve riêng nếu đo được lợi ích chất lượng tương xứng chi phí.
- Catalog là nguồn định nghĩa chung cho execution, clarification, suggestions và UI [S5, S6]. Không tạo một bộ rule riêng cho mỗi đường vào.
- Giữ result registry gọn trong PostgreSQL: `result_id`, thứ tự kết quả thành công, question/turn ID, QuerySpec, source/catalog/snapshot, locale và lineage. Không nhét mọi bảng kết quả vào prompt.
- Các guard về một nguồn, tiền tệ, grain item/order, coverage, nested path, SQL read-only vẫn bắt buộc, kể cả khi người dùng chọn form hoặc dùng ví dụ đã duyệt.

## 3. Backlog theo nguyên nhân

### TEXA-01 · P0 · Giá trị ngôn ngữ lọt vào SQL như raw value

- **Bằng chứng đã xác nhận:** `single-test-F-r1.jsonl:22`, case `v2_test_break_revenue_item_category`, có filter `event_name = 'mua hàng'` và kết quả 0 dòng. Đây không phải raw event `purchase`/`order_purchased`.
- **Root cause:** `sanity.py:73–86` cho literal đi qua khi không có value vocabulary; `spec.py:143–159` kiểm tra field/operator/type nhưng không xác lập nghĩa của text value. `clarify.py:163–165` còn bỏ qua đối chiếu lại khi nhận giá trị từ form/“Other”. Compiler bind tham số đúng kỹ thuật nhưng không thể sửa ý nghĩa sai.
- **Fix hệ thống:** thêm semantic binding trước QuerySpec: label/synonym → canonical concept → raw value theo nguồn. Tách `display_label`, semantic ID và physical value. Vocabulary phải có trạng thái **đầy đủ / mẫu / chưa có**; không xem top values là enum đầy đủ. Enum đóng bắt buộc resolve; trường mở/high-cardinality dùng literal có provenance và kiểm tra phù hợp, không từ chối mọi giá trị ngoài mẫu. Mọi đầu vào, kể cả form, chạy cùng binder. Không xác định được hoặc alias có nhiều nghĩa thì hỏi lại.
- **Không làm:** thay chuỗi `mua hàng` bằng `purchase` trong SQL; thêm dictionary riêng trong prompt/compiler; biến mọi kết quả rỗng thành lỗi.
- **Nghiệm thu:** đổi label/ngôn ngữ không đổi QuerySpec đã bind; cùng ý purchase ánh xạ đúng hai nguồn; thử alias xung đột, metadata thiếu/stale, form Other, giá trị high-cardinality hợp lệ, và kết quả rỗng thật. Trace phải chỉ được nguồn gốc của từng filter đã bind: câu người dùng, kế thừa đã xác nhận hay policy. Không thêm filter chỉ vì mô tả metric nhắc tới một event; event role của metric do compiler áp dụng theo catalog.
- **Điểm sửa:** `catalog.py`, `interpret.py`, `sanity.py`, `clarify.py`, `spec.py`; compiler chỉ nhận giá trị đã bind. Metadata/fixture phải được kiểm tra cùng contract.
- [x] Core đã triển khai; xem gate còn mở trong bảng tiến độ.

### TEXA-02 · P1 · Mô tả nguồn và khả năng truy vấn chưa là một contract nhất quán

- **Đã xác nhận:** catalog chứa mô tả “sessions cosmetics shop only” và cả `event_benchmark` trong allowed sources. Formal có refusal trên synthetic source vốn có session data. **Chưa xác nhận** mô tả là nguyên nhân trực tiếp của từng refusal, hoặc nguồn eval đang lộ ra UI.
- **Root cause đã thấy trong thiết kế:** thông tin capability nằm ở prose, catalog và metadata nguồn; nguồn eval dùng chung cấu hình với nguồn demo. Cần bổ sung trace quyết định refusal để xác minh liên hệ nhân quả.
- **Fix:** capability được suy ra từ định nghĩa metric/event roles/field coverage của từng source, có version; prose được dựng từ đó. Tách registry/config môi trường eval khỏi demo, dùng cùng engine contract. Eval vẫn được khai báo nguồn fixture riêng; demo chỉ công bố Cosmetics/Olist. Thêm kiểm tra publish catalog ↔ metadata trước khi chạy, không nới whitelist toàn cục để test xanh.
- **Nghiệm thu:** cùng metric trên hai nguồn có/không có event/field được phân biệt đúng; Olist sessions luôn unavailable; fixture có session không bị từ chối chỉ vì tên nguồn. API/UI demo không công bố source eval. Missing column metadata trong fixture phải bị báo rõ khi setup.
- **Điểm sửa:** `catalog/product_events.yaml`, `catalog.py`, `sanity.py`, `interpret.py`, setup/publish fixture trong `backend/eval/`.
- [x] Core đã triển khai; nghiệm thu nghiên cứu/coverage theo bảng tiến độ.

### TEXA-03 · P1 · Memory có lưu nhưng phân giải tham chiếu bằng heuristic yếu

- **Đã xác nhận:** “chia doanh thu đó theo từng tháng”, “kết quả … vừa rồi” bị coi là `new_topic`. Sau tám kết quả, “kết quả thứ hai” thất bại/thiếu lựa chọn đúng, còn “kết quả 2” tìm đúng cả filter accessories.
- **Root cause:** `memory.py:73–107,180–261` dùng cue/prefix, regex chỉ nhận số và overlap với ngưỡng cố định. Sau đó `prompts.py:61–65` cấm inherit khi `new_topic`; `_reference_form` (`answer.py:247–256`) chỉ đưa lựa chọn từ candidate set đã chọn sai. Không phải thiếu khả năng lưu tám lượt.
- **Fix:** resolver trả cấu trúc `new_query | continue | reference | discuss | clarify | social`, target ID và patch từng slot `keep/set/clear`. Chỉ reducer phía server được merge slot từ một result tồn tại, thuộc đúng phiên/hội thoại và còn hợp lệ theo snapshot/catalog/edit lineage. Chuẩn hóa số thứ tự thành reference có kiểu — phân biệt “câu hỏi thứ hai” với “kết quả thứ hai” — rồi kiểm tra registry. Với tham chiếu ngôn ngữ, resolver dùng question + compact QuerySpec/provenance; retrieval chỉ giúp tìm, không tự cho phép inherit.
- **Ứng xử khi mơ hồ:** không tự đổi thành chủ đề mới để đoán metric/kỳ. Form phải truy xuất từ toàn bộ registry kết quả tương thích của hội thoại, độc lập với phần lịch sử bị cắt khỏi prompt; cho tìm/xem thêm, không làm mất target vì top-k pruning; cho thấy số thứ tự, nguồn, metric, kỳ và filter. Tham chiếu ID/ordinal rõ ràng được ưu tiên trước giới hạn prompt. Không tăng sáu lượt thành một số tùy ý khác.
- **Nghiệm thu:** paraphrase Việt/Anh, số và chữ, 2/8/12+ kết quả, social noise, quay lại chủ đề cũ, sửa điều kiện và xóa filter, đổi nguồn, reference mơ hồ, edit/retry, snapshot/catalog đổi. Chấm cả target ID, QuerySpec cuối và kết quả SQL; test phải bắt được chọn nhầm lượt dù hai lượt tình cờ cùng con số.
- **Điểm sửa:** `memory.py`, `interpret.py`, `prompts.py`, `_reference_form`/state handling trong `answer.py`, form UI và tests memory.
- [x] Core đã triển khai; xem gate còn mở trong bảng tiến độ.

### TEXA-04 · P1 · Clarification phụ thuộc quá nhiều vào việc LLM tự khai báo mơ hồ

- **Bằng chứng:** clarification tăng điểm nhưng metric mơ hồ vẫn khó. `clarify.py:73–91` chỉ hỏi theo `recipe_alternatives` và `recipe_stated` do candidate cung cấp. Chưa có phân tích đủ để quy mọi lỗi clarification về cùng nguyên nhân.
- **Fix:** lập ambiguity policy từ metric contract: định nghĩa, grain, denominator, nguồn và trường bắt buộc. Nếu request có nhiều cách hiểu hợp lệ dẫn tới phép tính khác nhau, resolver trả các lựa chọn có ID; server kiểm tra và buộc hỏi khi còn unresolved. Không coi số confidence tự khai báo của LLM là xác suất đã hiệu chỉnh. Lựa chọn phải được tạo theo capability và giữ phần yêu cầu đã chắc chắn.
- **Nghiệm thu:** thiếu kỳ, metric thực sự mơ hồ, metric đã nói rõ, missing/unsupported field và xung đột nguồn; đo đúng-kết-quả-cuối, clarification precision/recall và số lượt hỏi. Không ép mọi câu phải hỏi để tăng recall; C0 được chấm đúng khi tự trả lời đúng.
- **Điểm sửa:** `clarify.py`, candidate schema trong `interpret.py`, metric catalog, memory pending state; mở rộng lát cắt clarification dev.
- [x] Core đã triển khai; policy chỉ mở rộng theo lỗi có bằng chứng.

### TEXA-05 · P1 · Gợi ý không đi qua semantic/capability validator

- **Root cause đã xác nhận:** `web/src/App.tsx:285–292` hardcode delivery/funnel/AOV hai nguồn và lấy bốn mục đầu, che cả examples từ catalog. `answer.py:310–314` đưa suggestions của LLM ra UI mà không có bước kiểm tra tính khả thi.
- **Fix:** một suggestion service trả candidate intent/QuerySpec kèm câu diễn đạt, dựa trên catalog và coverage đang chọn. Trước khi hiển thị phải qua cùng binder/validator như query thực; thiếu ngày thì dùng kỳ hợp lệ xác định từ nguồn. Chỉ hiển thị suggestion đã kiểm tra. Dùng tập ví dụ đã duyệt có version [S7] làm seed; không lưu câu SQL/đáp án theo exact question để trả tắt.
- **Nghiệm thu:** mọi gợi ý home/social/refusal chạy được hoặc mở clarification hợp lệ, không quảng bá tính năng ngoài scope; thay source/ngày/field/catalog thì gợi ý cập nhật. Không cần gọi truy vấn warehouse thật mỗi lần mở trang: kiểm contract khi publish/cache theo version, rồi kiểm lại khi thực thi.
- **Điểm sửa:** `App.tsx`, bootstrap/suggestion API, `answer.py`, catalog verified questions và shared validation service.
- [x] Core đã triển khai; xem gate còn mở trong bảng tiến độ.

### TEXA-06 · P1 · UI source và nguồn trong câu hỏi có thể mâu thuẫn

- **Đã xác nhận:** dropdown Olist, câu hỏi Cosmetics → trả Cosmetics đúng nhưng dropdown vẫn Olist. `App.tsx:102` gửi scope riêng với text; chưa có quy tắc xung đột được hiển thị.
- **Quyết định sản phẩm đề xuất** (không phải kết luận benchmark về bên nào nên thắng): nguồn được người dùng chọn rõ trên dropdown là **ràng buộc**; câu hỏi nêu nguồn khác thì hiện form giải quyết xung đột trước SQL. “Mọi nguồn” nghĩa là chưa chọn nguồn, không phải quyền gộp hai nguồn. Lưu provenance riêng cho UI selection, source được nhắc trong text và source đã resolve; chỉ có một `effective_source` được dùng cho QuerySpec/scope chip.
- **Nghiệm thu:** đủ tổ hợp UI A/text A, UI A/text B, UI A/không nêu, Mọi nguồn/text A, text nêu hai nguồn và follow-up đổi nguồn. Không thực thi khi conflict chưa giải quyết; chọn xong picker/scope/query phải thống nhất.
- **Điểm sửa:** request schema/API, `interpret.py`, `clarify.py`, `answer.py`, `App.tsx`.
- [x] Core đã triển khai; xem gate còn mở trong bảng tiến độ.

### TEXA-07 · P0 · Metric đánh giá chưa đủ để chứng minh ưu thế về hiểu đúng

- **Root cause đã xác nhận:** `benchmark.py:71–95` đòi exact column tuple + toàn bảng. Đây là contract hợp lệ nếu đã công bố, nhưng cột thừa giải thích 40 lỗi baseline; điểm strict không tách được lỗi trình bày và sai số liệu. Dataset nhỏ/ít cluster và câu synthetic chưa đại diện câu hỏi tiếng Việt của PM/PO; ba lần chạy không tạo thêm intent độc lập.
- **Fix quy trình:** giữ nguyên báo cáo cũ. Với phiên bản đánh giá mới, đăng ký trước **(a) metric chính:** accuracy của kết quả nghiệp vụ được yêu cầu và **(b) metric phụ:** tuân thủ output contract. Công bố rõ đây là protocol v2 có đổi cách chấm chính và chạy cả hai bên theo cùng rubric; vẫn báo strict score riêng, không so chéo với điểm cũ. Phân giải cột bằng metric/dimension ID đã quy định, không chọn cột vì giá trị trùng gold. Giữ grain, đủ chiều nhóm, số dòng/duplicate, NULL, tolerance và thứ tự khi yêu cầu; không tùy tiện bỏ cột group-by để làm baseline đúng.
- **Dataset mới:** lấy job-to-be-done PM/PO và câu diễn đạt tự nhiên Việt/Anh trên cả hai nguồn; aggregate/trend/filter/top-k, multi-metric phù hợp scope, item/order/payment, dữ liệu thiếu/rỗng/NULL, nested có/không có coverage, ambiguity, sửa sai và hội thoại nhiễu. Tăng **intent/template độc lập** và số tình huống phân biệt được, thay vì chỉ paraphrase cùng đáp án. Gold do người viết SQL độc lập, review thứ hai, chạy trên fixture có counterexample; không lấy compiler đang kiểm làm oracle.
- **Chống overfit:** toàn bộ holdout đã xem lỗi được xem là regression/dev cho vòng sửa; tạo holdout mới theo intent/template/dialogue family, đóng băng trước chạy [S3]. Ví dụ đã duyệt không được lấy từ holdout mới. Dataset diagnostic 17 dòng và các mẫu UI chỉ là bằng chứng chức năng.
- **Nghiệm thu:** scorecard có error taxonomy và lát cắt nguồn/ngôn ngữ/intent/độ dài; cùng model/snapshot/schema/định nghĩa/budget đã công bố cho B0/F; CI paired theo cluster và đủ mẫu độc lập để đọc được. Không yêu cầu Texa phải thắng mới coi runner đúng.
- **Điểm sửa:** `backend/eval/benchmark.py`, `report_ablation.py`, protocol/data manifests và dataset mới; giữ raw artifact cũ bất biến.
- [x] Scoring/protocol đã triển khai; chưa đóng gate holdout/review độc lập.

### TEXA-08 · P1 · Runner hội thoại diagnostic chấm khác tiêu chí giữa hai bên

- **Đã xác nhận:** report đa nguồn đã ghi Texa 7/7 và direct 4/7 có private slot/reference criteria khác nhau; không dùng chúng làm fair comparison. Đường chạy Texa/direct riêng trong `run_benchmark.py` là nơi cần hợp nhất adapter và scorer.
- **Fix:** mỗi phương pháp xuất một observation chung: action, kết quả thực thi, câu hỏi làm rõ và reference có thể quan sát. Scorer dùng một rubric bên ngoài cho tất cả. Internal QuerySpec/slot accuracy là chẩn đoán riêng của Texa; không bắt baseline không có QuerySpec phải khớp object nội bộ. Oracle cung cấp cùng thông tin khi clarification hợp lệ. Tiếp tục ablation F/M6/M0, F/C0; ghi rõ số model calls/cost và overhead của resolver mới.
- **Nghiệm thu:** hai observation tương đương cho cùng tình huống phải cùng điểm; đáp án đúng nhưng reference sai được phát hiện bằng counterexample; error/timeout không bị loại mẫu số. Chỉ công bố so sánh hội thoại mới sau khi scorer parity qua kiểm thử.
- **Điểm sửa:** `run_benchmark.py`, adapter ablation, comparator/scorer dùng chung, tests runner.
- [x] Core đã triển khai; xem gate còn mở trong bảng tiến độ.

### TEXA-09 · P1 · Reliability và budget chưa được bảo vệ thống nhất tại runtime

- **Đã xác nhận:** formal có bốn scenario F-r3 bị gián đoạn gateway; vẫn giữ trong mẫu số. Cost guard hiện là launcher cục bộ; `--matrix --execute` tạo process con có thể bỏ wrapper. `answer.py:37` giữ RUNS/SSE trong một process. **Chưa chứng minh** hệ thống chịu được tải lớp, retry sau outage hoặc restart phục hồi đúng.
- **Fix:** đưa call accounting, timeout, retry policy và reservation budget vào adapter LLM dùng chung của app/eval/CLI, không phụ thuộc cách launch. Dùng ID cho logical call/attempt, reserve/settle nguyên tử và concurrency-safe; tách usage đã biết với khoản chưa biết. Retry có giới hạn/backoff cho lỗi transient, không retry lỗi semantic để săn đáp án đúng. Thêm queue/concurrency limit trong triển khai một worker hiện tại; trạng thái job bền vững và restart reconciliation để không để turn chạy mãi. Chưa cần mở multi-replica khi chưa có nhu cầu.
- **Nghiệm thu:** kiểm đồng thời nhiều process, request đang bay lúc gần hết budget, 429/5xx/timeout, ngắt SSE, cancel/retry và restart. Không vượt giới hạn admission đã thiết kế; ghi rõ chi phí failed call chưa được provider xác nhận, không cam kết biết chính xác hóa đơn chỉ từ token thiếu. Matrix/CLI/UI phải đi cùng guard. Phiên người dùng vẫn tách biệt.
- **Điểm sửa:** `llm.py`, provider adapters, `answer.py`, runtime configuration, `backend/eval/run_gateway_check.py` và orchestration. Inject fault trên môi trường test, không gây outage cho buổi demo thật.
- [x] Guard/fault tests và sanity tải tám phiên đã có; chưa đóng gate tải cả lớp.

### TEXA-10 · P2 · Có mẫu trả lời chậm, chưa xác định bottleneck

- **Bằng chứng:** E2E có mẫu 20–29 giây; formal p50 Texa 9,554 giây, B0 5,952 giây nhưng Texa gồm insight còn B0 chỉ sinh SQL. Không đủ cơ sở kết luận do model hay thiếu index.
- **Fix đúng thứ tự:** trace cùng ID theo queue → context/interpret → bind/clarify → DB → facts → insight → SSE/render; ghi token, DB plan và p50/p95 theo loại câu. Chỉ sau đó tối ưu stage chiếm thời gian: SQL/index sau EXPLAIN, giảm context/calls dư, deterministic rendering cho tổng đơn giản, cache có khóa source/snapshot/catalog/spec/permission hoặc chạy song song tác vụ độc lập [S4]. Không cache theo câu hỏi thuần hay bỏ validation.
- **Nghiệm thu:** báo first-result và end-to-end riêng, so chất lượng trước/sau, cache invalidation và isolation; load test theo số người dự kiến cùng dùng, công bố concurrency. Chốt SLO sau baseline tải, không bịa ngưỡng để tuyên bố đã đạt.
- **Điểm sửa:** instrumentation trong `answer.py`, `llm.py`, `db.py`, pipeline insight và frontend trace; SQL/ETL chỉ sửa khi plan chỉ ra nguyên nhân.
- [x] Đã có instrumentation và đo queue/end-to-end; tối ưu và SLO còn mở.

### TEXA-11 · P2 · Thông báo và caveat lẫn ngôn ngữ

- **Root cause:** `_lang` (`answer.py:144–148`) dựa vào candidate/default English; message trong `sanity.py` và mô tả catalog có prose tiếng Anh. Chỉ yêu cầu LLM “nói tiếng Việt” không kiểm soát các nhánh deterministic.
- **Fix:** locale là state của request/hội thoại; lỗi/caveat dùng reason code + typed parameters và renderer i18n. Catalog tách label/description theo locale khỏi expression/ID. Insight sử dụng facts theo ID và locale, có fallback đã dịch. Không sửa prose của catalog để đổi nghĩa metric.
- **Nghiệm thu:** query, clarification, refusal, missing field, timeout và CSV header có locale nhất quán; raw event value không bị dịch thành SQL literal. Việt/Anh đổi ngôn ngữ không làm thay đổi kết quả.
- **Điểm sửa:** catalog display metadata, `answer.py`, `clarify.py`, `sanity.py`, insight/UI renderer.
- [x] Core đã triển khai; xem gate còn mở trong bảng tiến độ.

### TEXA-12 · P2 · Sửa câu hỏi nhưng tiêu đề lịch sử không cập nhật

- **Root cause đã xác nhận:** title tạo từ câu đầu tại `answer.py:224–226`; edit chỉ cập nhật turn và conversation timestamp (`383–405`).
- **Fix:** quy định title là title người dùng đặt hoặc title suy ra từ first surviving turn. Recompute title suy ra trong cùng transaction edit/rewind; giữ title người dùng đã đặt nếu sau này có chức năng đó. API và sidebar lấy cùng giá trị.
- **Nghiệm thu:** sửa câu đầu/câu sau, reload/mở lịch sử, edit có lượt sau; không nhân đôi turn, không đổi nhầm title chat khác và không dùng title làm reference ID.
- **Điểm sửa:** `answer.py`, conversation persistence/list response, sidebar tests.
- [x] Core đã triển khai; xem gate còn mở trong bảng tiến độ.

## 4. Thứ tự implement và tracking

Mỗi bước lớn commit trên `main` theo yêu cầu hiện hành. Chỉ cập nhật trạng thái khi có artifact/test chứng minh; không tick vì đã sửa prompt.

| Bước | Công việc | Điều kiện đi tiếp |
|---|---|---|
| 0 | Giữ artifacts cũ; thống nhất rubric/protocol mới, tạo regression tái hiện lỗi; bổ sung trace cho nguyên nhân chưa rõ (07,08,10) | Chạy lại regression thấy đúng lỗi, scorer parity được xác định; chưa dùng holdout mới để tune |
| 1 | Semantic contract/binder/capability và validation cho mọi entry point (01,02) | Không còn display label lọt vào raw enum; fixture/catalog publish hợp lệ; không nhầm unavailable với zero |
| 2 | Structured reference resolver + reducer + pending clarification (03,04) | Chọn đúng target và giữ/đổi/xóa slot trên paraphrase, hội thoại dài, noise, snapshot/edit |
| 3 | Suggestions và source conflict dùng chung contract (05,06) | Không có gợi ý ngoài scope; không thực thi source conflict chưa giải quyết |
| 4 | Locale/title cùng regression UX (11,12) | UI/API/reload nhất quán, không làm đổi semantic result |
| 5 | Provider guard, bounded concurrency, fault tests; đo và tối ưu bottleneck đã xác nhận (09,10) | UI/CLI/matrix không bỏ budget guard; có load/fault report và SLO thực tế |
| 6 | Đóng băng phiên bản; chạy B0/F + ablation theo protocol mới, rồi browser E2E nâng cao | Công bố cả lỗi/CI/chi phí; không đổi scorer sau khi thấy kết quả; có quyết định go/no-go demo |

### Gate nghiệm thu cuối

- [ ] Corpus regression bao gồm **lớp lỗi**: paraphrase/locale, thay source và vocabulary, empty vs unavailable, ordinal/ngôn ngữ, noise/correction, stale snapshot, edit/retry, source conflict, suggestions, provider failures và concurrency.
- [ ] Property/metamorphic checks: đổi nhãn không đổi canonical query; cùng nghĩa giữa các cách nói giữ kết quả; thêm filter chỉ đổi slot được yêu cầu; unresolved reference không được tự inherit; suggestion hiển thị phải qua validation.
- [ ] Oracle SQL độc lập; kiểm cả ý định/grain/target lẫn bảng kết quả, không chỉ JSON hợp lệ hay HTTP 200.
- [ ] E2E dùng LLM thật trên cả nguồn, có CSV/pagination/history/cancel/edit/source switching; test tải theo quy mô demo và ghi phạm vi chưa test.
- [ ] Không sửa golden, loại case khó hoặc retry đến khi đúng để tăng điểm; báo dữ liệu thiếu/timeout/usage chưa biết minh bạch.
- [ ] Không coi CSV là bug còn tồn: tải thực tế top-3, ratio và 31 dòng ngày đã khớp gold. Không cần sửa phần này khi chưa có bằng chứng lỗi mới.

## 5. Tài liệu kiến trúc đã tham khảo

Đã mở và đọc các trang chính thức ngày 05/11/2026. Đây là **nguyên tắc được tài liệu hỗ trợ**; thiết kế resolver/reducer ở trên là đề xuất cho Texa, không phải khẳng định vendor nào triển khai nội bộ y hệt.

| Nguồn | Nguyên tắc áp dụng và giới hạn |
|---|---|
| [S1 — OpenAI Conversation state](https://developers.openai.com/api/docs/guides/conversation-state) | Có thể quản lý/persist context hội thoại. Persist messages không tự giải quyết chọn đúng kết quả và kế thừa slot nghiệp vụ; Texa phải chịu trách nhiệm phần đó. Không bắt buộc chuyển sang API state riêng của một vendor. |
| [S2 — OpenAI Structured Outputs](https://developers.openai.com/api/docs/guides/structured-outputs) | Dùng schema để kiểm soát shape/type/enums; vẫn phải kiểm nghĩa, ID, refusal và bất định phía ứng dụng. Kiểm tra gateway/model hỗ trợ strict schema trước khi bật; luôn có local validation, không giả định tương thích đầy đủ. |
| [S3 — OpenAI Evaluation best practices](https://developers.openai.com/api/docs/guides/evaluation-best-practices) | Eval theo task thực, dữ liệu đại diện, tiêu chí rõ và lặp lại liên tục; mở rộng từ lỗi/user traffic, tách bộ dùng tune khỏi bộ đánh giá. |
| [S4 — OpenAI Latency optimization](https://developers.openai.com/api/docs/guides/latency-optimization) | Giảm token/request dư, tận dụng song song tác vụ độc lập; tối ưu theo đo đạc và đánh đổi chất lượng. Không phải lý do bỏ guard hoặc đổi model chỉ để giảm số giây. |
| [S5 — dbt Semantic Layer architecture](https://docs.getdbt.com/docs/use-dbt-semantic-layer/sl-architecture) | Định nghĩa semantic models/metrics tập trung; lớp dịch query sinh SQL. Texa giữ compiler và catalog trung tâm, không mở scope sang mọi DB/join. |
| [S6 — Snowflake Semantic Views](https://docs.snowflake.com/en/user-guide/views-semantic/overview) | Mô tả semantic của dữ liệu/metric trong một lớp được quản trị. Áp dụng ý tưởng contract có version; không cần chuyển engine sang Snowflake. |
| [S7 — Snowflake Verified Query Repository](https://docs.snowflake.com/en/user-guide/views-semantic/verified-query-repository) | Cặp câu hỏi–query đã kiểm chứng là ví dụ liên quan cho quá trình sinh truy vấn. Với Texa, dùng ví dụ semantic đã review để hướng dẫn/kiểm thử và onboarding; không fuzzy-match rồi trả đáp án cố định, không đưa holdout vào kho ví dụ. |

**Tiêu chí “sửa chuẩn”:** có bằng chứng nguyên nhân → sửa tại đúng ranh giới contract/state → giữ invariant khi dữ liệu/ngôn ngữ thay đổi → regression trên biến thể độc lập → đánh giá holdout mới. Một ví dụ từng sai nay đúng chưa đủ để đóng issue.
