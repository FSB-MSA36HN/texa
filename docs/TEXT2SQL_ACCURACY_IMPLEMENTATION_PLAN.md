# Texa — Plan tăng độ đúng bằng ví dụ đã kiểm chứng và self-consistency

Cập nhật 05/11/2026, bổ sung thiết kế benchmark theo yêu cầu mới. **Chưa triển khai retrieval/consistency. Bắt đầu chuẩn bị contract/blueprint benchmark trước.** Mốc code sản phẩm trước thay đổi: `83403e3`. Giữ PostgreSQL, Cosmetics + Olist, một nguồn/truy vấn, tám metric và nested scalar theo catalog. Không mở rộng engine, domain hoặc SQL tự do.

## 1. Kết luận nghiên cứu

Hai ý tưởng có cơ sở, nhưng cần gọi đúng tên và áp dụng đúng tầng:

| Mô tả | Tên và cách hiểu chính xác | Hướng cho Texa |
|---|---|---|
| Cho model tham khảo câu hỏi và truy vấn đúng | **Few-shot in-context learning (ICL)**. Nếu lấy ví dụ phù hợp từ kho theo từng câu hỏi: **retrieval-augmented few-shot prompting / demonstration retrieval**. Snowflake gọi kho nghiệp vụ này là **Verified Query Repository (VQR)**. | Kho ví dụ đã kiểm chứng, truy hồi ít ví dụ liên quan; chủ yếu dạy `câu hỏi → candidate intent`, kèm QuerySpec chuẩn để kiểm tra. |
| Gọi cùng model nhiều lần rồi chọn phương án được đồng thuận | **Self-consistency / multi-sample consistency selection**, lấy nhiều mẫu đủ đa dạng rồi tổng hợp đáp án. | Chỉ lấy thêm mẫu ở yêu cầu khó; so sánh ý định có cấu trúc, giữ compiler hiện có. |
| Gọi các model khác nhau | **Multi-model ensemble**; không đồng nghĩa với self-consistency cùng model. | Chưa ưu tiên: thêm cấu hình, kiểm soát chi phí và khó tách hiệu quả của model khỏi hệ thống. |
| Model kiểm tra/chấm các phương án | **Verifier / reranker**. Có nhiều vòng phản biện qua lại mới là debate. | Chưa đưa vào bản đầu; kiểm tra bằng catalog/code trước, đo nhu cầu rồi mới thử verifier. |

Đây không phải fine-tuning: không cập nhật trọng số model. Ví dụ trong prompt hướng dẫn cách xử lý yêu cầu mới, không được trở thành bảng tra câu trả lời theo câu hỏi.

### Nguồn chính đã đọc và điều rút ra

1. [OpenAI — Prompt engineering, “Few-shot learning”](https://developers.openai.com/api/docs/guides/prompt-engineering): đưa một số cặp input/output đa dạng vào prompt để hướng dẫn tác vụ, khác fine-tuning.
2. [Gao và cộng sự — DAIL-SQL](https://arxiv.org/abs/2308.15363), phần example selection/organization và Appendix A.2: chọn ví dụ dựa trên câu hỏi và cấu trúc truy vấn; có masking để giảm lệ thuộc tên schema/value. Bản mở rộng dùng voting **năm truy vấn**, temperature 1.0. Paper báo Spider EX từ **86,2% lên 86,6%**, đồng thời cảnh báo rất tốn thời gian và chi phí nhiều lần. Đây là **0,4 điểm phần trăm trong thiết lập đó**, không phải bảo đảm tăng mạnh cho Texa. Đoạn này không đủ xác định vote theo SQL text hay execution result; không gán cách vote của Texa cho paper.
3. [Snowflake — Cortex Analyst VQR](https://docs.snowflake.com/en/user-guide/views-semantic/verified-query-repository): lưu câu hỏi và SQL đã kiểm chứng, dùng truy vấn liên quan cho câu hỏi tương tự; SQL dùng tên logical của semantic model. Tài liệu yêu cầu kiểm tra SQL/kết quả và cảnh báo ví dụ sai có thể giảm độ chính xác.
4. [Wang và cộng sự — Self-Consistency, ICLR 2023](https://arxiv.org/abs/2203.11171), §2: cùng model lấy nhiều reasoning paths và tổng hợp đáp án cuối. Bằng chứng gốc trên reasoning benchmarks; không tự chứng minh hiệu quả Text2SQL hay Texa.
5. [Sun và cộng sự — SQL-PaLM](https://arxiv.org/abs/2306.00739), §6.2–6.3: consistency decoding có lọc lỗi thực thi; test-time selection còn dùng đa số execution outcomes giữa các phương án. SQL chạy được vẫn chưa chắc đúng nghiệp vụ.
6. [Databricks — Tune Genie quality](https://docs.databricks.com/aws/en/genie-agents/tune-quality): example SQL/instructions là kiến thức được quản trị; đây là một ví dụ sản phẩm tương tự, không phải tên khác của VQR.
7. [OpenAI — Evaluation best practices](https://developers.openai.com/api/docs/guides/evaluation-best-practices): đánh giá theo tác vụ thật, có ca thường/biên/đối kháng, gold và human review; đánh giá từng điểm có tính bất định.
8. [OpenAI — Latency optimization](https://developers.openai.com/api/docs/guides/latency-optimization): giảm lượt gọi, giới hạn output và chạy song song phần độc lập. Song song giảm đường chờ so với chạy tuần tự, không làm các lượt gọi miễn phí.

**Phần Texa đề xuất dưới đây là thiết kế thích nghi**, không phải tái hiện nguyên bản DAIL-SQL/SQL-PaLM và không được mượn điểm của các paper làm điểm sản phẩm.

## 2. Điểm xuất phát và việc phải xử lý trước

### Bằng chứng hiện có

- Regression v3: 16 câu × ba lần, Texa **35/48 = 72,9%**, B0 **41/48 = 85,4%**. Đây là bộ đã nhìn thấy, có cả PT stress ngoài ngôn ngữ sản phẩm chính Việt/Anh; không phải holdout.
- 13 lượt lỗi của Texa gồm **bảy refusal** và **sáu sai bảng kết quả**. Không coi toàn bộ là lỗi hiểu câu hỏi.
- Clarification v4: đầy đủ F **6/6**, C0 **1/6**; chỉ hai tình huống lặp ba lần. Memory v3 chưa đủ contract để kết luận ablation.
- Backend **261 passed, 12 skipped**; Playwright **15/15** với provider mô phỏng. Model thật: tám request đồng thời đúng trong một lượt sanity; p50/p95 end-to-end **21,2/36,5 giây**. Chưa xác lập sức chứa lớp học.
- Artifacts nguyên gốc: `data/benchmark/results/remediation-20261105/scorecard.json` và các thư mục được tham chiếu ở đó.

### P0: phân biệt lỗi compiler/semantic contract với lỗi LLM

Đã đối chiếu hai trace của `single-test-F-r1.jsonl`:

- `rv2_test_olist_purchase_revenue_trend`: QuerySpec đã chọn revenue theo ngày; compiler dùng `SUM(...) FILTER (purchase role)` nhưng `GROUP BY` vẫn nhìn toàn bộ event. Ngày chỉ có payment có thể xuất hiện thêm với revenue 0, trong khi gold chỉ nhóm purchase rows.
- `rv2_test_olist_category_buyers`: cùng cơ chế tạo category chỉ có event khác, buyers 0, trong khi gold chỉ có category có purchase.

Hai ca này lặp lỗi ba lần, chiếm sáu lượt sai bảng. **Đây là bất đồng về miền dòng tạo nhóm, không thể chữa bằng thêm prompt hoặc voting.** Cần review định nghĩa nghiệp vụ/gold trước khi quyết định hành vi; việc gold hiện có một đáp án chưa tự chứng minh gold đúng.

Việc tiên quyết:

1. Định nghĩa trong semantic contract: metric lấy những event nào; tập dòng nào tạo nhóm; có chủ động điền kỳ/category không phát sinh hay không; khác biệt giữa `0`, không có nhóm và unavailable.
2. Sau khi adjudicate, đưa quy tắc miền nhóm vào catalog/compiler, không yêu cầu LLM tự thêm filter để bù lỗi compiler. Một metric purchase có thể nhóm trên eligible purchase rows nếu contract quy định như vậy. Ratio phải giữ support của cả tử/mẫu; không đẩy predicate tử số xuống WHERE làm sai mẫu số. Không mở multi-metric trong scope này.
3. Không dùng `HAVING value != 0` hay xóa các hàng 0 sau truy vấn. Purchase có giá trị 0, doanh thu bù trừ về 0 và nhóm có buyer thật vẫn phải được giữ khi contract yêu cầu.
4. Test độc lập: payment-only day/category, purchase giá 0, NULL category, kỳ rỗng, event không có coverage, conversion denominator. Gold SQL được viết/review độc lập; công bố mọi thay đổi annotation bằng version mới.
5. Trace refusal phải lưu reason code và candidate đủ để phân biệt: ngoài scope thật, model đọc sai, hoặc guard/capability từ chối. Bảy refusal hiện chỉ là phân loại kết quả quan sát được, chưa đủ để khẳng định cùng một root cause.

Mốc này phải đo riêng. Các cấu hình ablation sau đó đều dùng **cùng compiler/contract đã sửa**, tránh gán công của sửa compiler cho hai kỹ thuật mới.

## 3. Kiến trúc dự kiến

```text
Câu hỏi + UI source + registry/snapshot
 → catalog/capability và policy bắt buộc
 → truy hồi 0–3 ví dụ đã kiểm chứng, đúng version/phạm vi
 → interpret structured candidate lần đầu
 → kiểm tra candidate bằng binder/reducer ở chế độ không ghi trạng thái
 → đủ điều kiện bình thường: dùng phương án đầu
 → có tín hiệu bất định kỹ thuật và đủ ngân sách:
      thêm hai mẫu interpret song song → chuẩn hóa → consistency selection
 → policy hỏi lại / từ chối / QuerySpec đã validate
 → compiler → PostgreSQL read-only → facts → trả kết quả
```

LLM hiện trả **candidate** có thể chứa thiếu thông tin/mơ hồ; `QuerySpec` là contract nghiêm ngặt ở bước sau. Không ép candidate chưa rõ thành QuerySpec hợp lệ chỉ để vote. Chỉ ghi candidate thắng vào turn; chỉ cập nhật memory sau luồng chính như hiện tại. Khi user trả lời form, dùng candidate/answers đã lưu, không gọi voting lại và làm thay đổi câu đang được hỏi.

## 4. Thành phần A — Kho ví dụ đã kiểm chứng và retrieval

### 4.1. Không bắt đầu từ số không

`interpret.render_catalog()` đã đưa `catalog.verified_questions` dạng `question → reading` vào prompt. Vì vậy thay đổi là **nâng cấp governance, độ đầy đủ và lựa chọn ví dụ**, không gọi là lần đầu Texa có few-shot. Control giữ nguyên các ví dụ legacy đã đóng băng; cờ mới chỉ bật/tắt kho truy hồi bổ sung. Dedupe và kế hoạch bỏ legacy nếu cần phải là một thử nghiệm riêng.

### 4.2. Contract của ví dụ

Kho khoảng **32–48 ví dụ để khởi đầu**, chọn theo coverage, không xem số lượng này là tối ưu đã được chứng minh. Đặt ở `catalog/verified_examples.yaml`; loader/validator riêng, liên kết với catalog hiện có.

Mỗi ví dụ có:

- ID, version, template/paraphrase family, ngôn ngữ, source applicability, catalog/contract version và capability requirements.
- Câu hỏi mẫu; context đầu vào nếu là follow-up; candidate output đúng schema; QuerySpec mong đợi nếu đã đủ thông tin, hoặc action/form fields mong đợi nếu phải hỏi lại/từ chối.
- Ghi chú nghiệp vụ ngắn dùng semantic IDs; độc lập với raw event literal của từng source.
- SQL tham chiếu và fixture kiểm chứng **dành cho review/CI**, không nhét toàn bộ SQL vào interpret prompt và không dùng lại SQL đó làm truy vấn sản phẩm.
- Người review, thời điểm, trạng thái draft/approved, provenance và hash. Agent review không được ghi thành human review.

Coverage: tám metric theo nguồn có hỗ trợ; aggregate/trend/breakdown/top-k; nested scalar đã khai báo; item vs order/payment; đủ/thiếu kỳ; xung đột nguồn; kết quả rỗng hợp lệ; unsupported thật; follow-up đổi kỳ/filter, giữ/xóa slot và tham chiếu kết quả cũ. Không viết một ví dụ khớp từng câu test. Ví dụ follow-up dùng local placeholder result ID được remap trong block, không mang ID thật từ chat khác.

### 4.3. Retrieval rẻ trước, chỉ thêm embedding khi có bằng chứng

1. Chỉ đọc bank approved, đúng catalog version và quyền/phạm vi hiện tại. Source đã được user xác nhận có thể hard-filter; source đang xung đột chưa được coi là đã xác nhận.
2. Xếp hạng lexical/BM25 trên câu hỏi, nhãn/synonym trong catalog và tags; chuẩn hóa Việt/Anh, mask giá trị cụ thể ở nơi có cấu trúc chắc chắn. Không thêm lượt LLM để tạo SQL sơ bộ chỉ nhằm retrieval.
3. Chọn tối đa ba ví dụ, ưu tiên đa dạng template và xử lý khác nhau; nếu không có ví dụ phù hợp thì dùng zero additional examples. Ngưỡng relevancy được chọn trên dev, không mặc định top-1 luôn đúng.
4. Mục tiêu trung bình **≤600 input tokens** bổ sung; hard cap dự kiến **1.200 tokens** theo tokenizer được kiểm chứng. Hiện `len(text)//4` chỉ là ước lượng; phải ghi cả actual usage, dùng packing bảo thủ và không cắt dở block JSON.
5. Giữ chỗ cho catalog, câu hỏi và registry trước; thiếu context budget thì bỏ bớt ví dụ, không cắt bằng chứng tham chiếu để giữ few-shot. Thứ tự: static catalog → examples → dynamic user/registry theo context packer đã đo.
6. Trace IDs/scores/version/token estimate. Cache bank/index theo content hash + catalog version; cache retrieval chỉ theo các đầu vào công khai tương ứng, không cache output hay memory xuyên phiên.

So sánh dev với vài ví dụ cố định cùng số lượng/token budget để biết ích lợi do **retrieval** hay chỉ do thêm ví dụ. Chỉ thử local multilingual embeddings nếu lexical retrieval thiếu recall trên tập relevance do người review; không thêm vector DB/service ở bản đầu. Đây là retrieval-ICL nhẹ, không tuyên bố triển khai đầy đủ thuật toán DAIL-SQL.

Ví dụ chỉ là bằng chứng hướng dẫn; catalog, capability, user context và binder vẫn có thẩm quyền. Không cho retrieved text đổi policy, source, thời gian hay tự tạo metric ngoài scope. Không tự đưa truy vấn user chạy thành công vào bank approved.

## 5. Thành phần B — Consistency selection có điều kiện

### 5.1. Giới hạn và điều kiện gọi thêm

- Giữ `gpt-6-luna` qua gateway hiện tại, chưa mua thêm model. Lấy mẫu cùng model là thử nghiệm đầu tiên; không mặc định model đa dạng hơn thì chắc chắn tốt hơn.
- Mặc định một interpret. Nếu trigger, thêm **hai mẫu độc lập song song**, tổng tối đa ba candidate cho một quyết định. Không cho các mẫu đọc đáp án của nhau.
- Trước tiên kiểm tra gateway/model hỗ trợ sampling parameters nào và có tạo đa dạng thực tế hay không. Khóa cấu hình được chấp nhận vào protocol; không mặc định temperature 1.0 của DAIL dùng được cho model này. Nếu không có diversity hữu ích, không rollout voting và không âm thầm đổi model.
- Trigger dự kiến: candidate không hợp lệ sau normalization; model từ chối nhưng catalog capability cho thấy có khả năng hỗ trợ; hoặc binding/reference có nhiều phương án mà cần xác minh cách đọc. Từng trigger cần có detector generic và test; không dựa vào case ID/câu hỏi benchmark, hoặc confidence do model tự chấm.
- **Không vote để đoán thông tin user chưa cung cấp.** Thiếu kỳ, mơ hồ nghiệp vụ thật, xung đột UI source hoặc registry bị cắt phải tuân policy hỏi lại. Nhiều mẫu cùng đoán một kỳ không biến kỳ đó thành ý định của user.
- Mục tiêu trigger rate dev khoảng ≤15%; đây là mục tiêu đo, không bỏ ngẫu nhiên các ca khó để đạt tỷ lệ. Có ngân sách/deadline cứng và policy fallback, cấu hình đóng băng trước test.

### 5.2. Chuẩn hóa và chọn phương án

Tách phần binder/reducer/validation cần dùng thành hàm có thể chạy dry-run trên cùng snapshot. Mỗi candidate được kiểm tra riêng, không query kết quả/ghi DB để “học” đáp án. Value binding có thể cần đọc vocabulary/source metadata từ DB; các lần đọc phải cùng snapshot, không ghi state và không làm mất trạng thái unresolved/ambiguous.

Khóa so sánh gồm outcome và trạng thái làm rõ, source, metric, shape, selection, filters đã bind, time range, top-k/limit; với follow-up thêm target result ID và thao tác keep/set/clear, lineage/snapshot. Query đủ rõ có thể so canonical QuerySpec; query chưa đủ rõ phải so normalized resolution bundle và các ambiguity còn lại.

- Chỉ chuẩn hóa tương đương đã định nghĩa: thứ tự các filter AND độc lập, số/date theo type, semantic ID → raw value theo catalog.
- Giữ khác biệt về toán tử, kiểu, NULL, thiếu vs clear, mục tiêu tham chiếu, source, kỳ và grain. Không sắp xếp dimensions khi thứ tự có ý nghĩa với output contract.
- Không vote bằng chuỗi SQL, câu diễn giải hay bảng kết quả trên một fixture. Hai query sai có thể cùng trả rỗng hoặc cùng một con số.
- Với ba mẫu đã lên lịch, cần ít nhất **hai mẫu hợp lệ đồng ý đầy đủ**; không lấy một mẫu hợp lệ còn lại làm “đa số” sau khi loại hai mẫu lỗi. Không ghép metric từ mẫu A với kỳ từ mẫu B để tạo candidate chưa ai đề xuất.
- Đồng thuận vẫn phải qua toàn bộ policy/binder/QuerySpec validation. Nếu hòa/bất đồng trọng yếu thì tạo form theo các field có lựa chọn hợp lệ. Không đủ dữ kiện tạo form thì báo giới hạn/retry phù hợp, không bịa lựa chọn.
- Candidate consensus không phải xác suất đúng đã hiệu chỉnh. Đo cả trường hợp đồng thuận sai.

### 5.3. Runtime, memory và chi phí

Giữ guard chi phí theo từng attempt: provider SDK retry tắt, application retry hiện tối đa hai provider attempts cho lỗi được phép retry, cùng deadline hiện tại. Hai samples bổ sung là hai logical calls, mọi attempt đều phải reserve/settle đúng. Giữ reservation khi usage chưa rõ như hiện tại.

Run admission và LLM admission hiện là hai semaphore riêng. Mỗi provider request chỉ lấy LLM admission một lần; không bọc cả quyết định bằng một LLM slot rồi chờ các sample con lấy lại chính semaphore đó. Dùng giới hạn riêng cho sampling với tổng provider in-flight nằm trong mức hiện có; giữ chỗ công bằng cho người dùng khác. Khi tám người cùng dùng, ưu tiên đường một mẫu; không mở concurrency vô hạn để giữ thời gian của một request.

Trace: trigger reason, số mẫu lên lịch/hoàn thành/lỗi, semantic fingerprints, vote counts, disagreement fields, selected candidate, retrieval IDs, stage timings, actual tokens/cost, timeout/fallback. Trace không chứa API key, hidden gold hay memory của phiên khác. Hủy yêu cầu không cho sample muộn ghi đè turn đã cancel; ngân sách vẫn phải được settlement khi có usage.

## 6. Ước tính thời gian và chi phí

Các con số dưới là **ước tính kế hoạch**, chưa phải kết quả của tính năng mới.

Gateway ledger tại thời điểm nghiên cứu ghi input **0,10 USD/triệu tokens**, output **0,50 USD/triệu tokens**; đây là giá gateway đang cấu hình, không khẳng định là bảng giá OpenAI. Tổng chi ước tính **0,556704 USD**, reserved **0,189662 USD**, cap dùng chung **10 USD**; còn khả dụng khoảng **9,253634 USD**, không reset ledger hay tự giải phóng khoản chưa rõ.

V3 Texa trung bình khoảng 4.346 input + 326 output tokens/câu, tương đương **0,000597 USD/câu** ở giá ghi nhận. Tổng này gồm các stage, không phải chỉ interpret.

Ví dụ dự toán:

- Retrieval bổ sung trung bình 600 input tokens: khoảng **0,000060 USD/câu**.
- Giả sử mỗi mẫu bổ sung 3.000 input + 300 output: **0,000450 USD/mẫu**. Hai mẫu ở 15% câu: trung bình **0,000135 USD/câu**.
- Tổng khoảng **0,000792 USD/câu**, tăng khoảng **33%**. Chưa gồm retry, context dài hơn hoặc thay đổi số stage; phải thay bằng actual usage sau pilot. Nếu không đạt gate chi phí thì giảm/bỏ consistency, không che giấu token.

Latency đường trigger gần `T_primary + max(T_sample2, T_sample3) + T_select`, còn phụ thuộc queue; không phải ba mẫu song song ngay từ đầu nên không hứa latency bằng một lần gọi. Theo dõi riêng nhóm trigger, toàn bộ traffic và tải tám phiên. Khi tỷ lệ trigger thấp, p95 vẫn có thể tăng mạnh.

## 7. Thiết kế benchmark để biết thành phần nào có ích

### 7.0. Khó vì đúng vấn đề, không khó để ép baseline thua

Điểm baseline lịch sử khoảng 68,8% không tự chứng minh bộ test quá dễ; baseline mới còn đạt 85,4% trên bộ regression nhỏ. Model có schema/định nghĩa rõ hoàn toàn có thể làm tốt truy vấn aggregate trên event table. Chưa có dữ liệu user đủ để kết luận câu dễ hiếm trong thực tế hoặc LLM trực tiếp luôn kém. Giá trị Texa phải được kiểm chứng, kể cả khi kết quả cuối là một số workflow không đem lại lợi ích.

Bộ mới là **challenge suite có chủ đích**, đo các khả năng sản phẩm muốn bảo đảm; không được gọi điểm của nó là accuracy đại diện mọi PM/PO. Một tập câu hỏi thu từ user độc lập về sau sẽ đo phân bố sử dụng thật. Khóa tiêu chí độ khó bằng số ràng buộc/khác biệt nghiệp vụ **trước khi gọi model**, không đặt mục tiêu kiểu “baseline phải dưới 40%” và không loại câu vì baseline giải đúng.

Giữ câu dễ làm negative control: nếu workflow khiến câu vốn đúng trở thành sai, hỏi thừa hoặc chậm hơn thì phải thấy được. Tăng độ khó bằng phân biệt semantics và dữ liệu có counterexample, không bằng viết câu dài, tiếng Bồ Đào Nha ngoài scope, giấu schema của baseline, hoặc yêu cầu tính năng Texa chưa hỗ trợ.

Contract máy đọc được: `data/benchmark/challenge_v1/design.yaml`. Các scenario blueprints chỉ là bản thảo chưa có gold/execution contract hoàn chỉnh, chưa phải test holdout. Validator phải báo rõ khoảng trống và chặn chạy confirmatory khi chưa đủ điều kiện. Bộ mới sẽ thay bộ cũ làm benchmark chính **sau khi hoàn tất review/freeze**; giữ nguyên bộ cũ để tái hiện lịch sử và regression, không xóa hoặc sửa ngược điểm.

### 7.1. Các cấu hình

| Nhãn kế hoạch | Cấu hình | Mục đích |
|---|---|---|
| B0 | Cùng LLM sinh SQL trực tiếp, schema + định nghĩa nghiệp vụ, không thêm bank mới | Baseline hiện có |
| B0+R | B0 thêm Q→SQL demonstrations từ cùng bank approved | Control công bằng về lợi ích thông tin ví dụ |
| B1 | Cùng LLM sinh SQL, có raw history/kết quả trước, hỏi lại qua schema chung và tối đa một vòng sửa SQL từ lỗi thực thi | Baseline mạnh hơn để đo đóng góp ngoài các công cụ hội thoại/thực thi cơ bản |
| T00 | Texa sau sửa P0, không retrieval mới, không consistency | Control hệ thống; giữ legacy examples như hiện tại |
| T10 | T00 + retrieval | Tách đóng góp A |
| T01 | T00 + consistency | Tách đóng góp B |
| T11 | T00 + cả hai | Lợi ích kết hợp và tương tác |

Các nhãn này là thiết kế mới, chưa là CLI variants đã implement. Ánh xạ rõ tới config, không đổi ý nghĩa các F/B0/M6/M0/C0 lịch sử. Giai đoạn dev có thêm static-few-shot và always-three-samples diagnostic để đo selection/trigger; không mở rộng matrix cuối khi chưa khóa protocol.

B0/B0+R giữ đúng ý nghĩa single-shot và chỉ chấm câu đơn đã đủ dữ kiện. **B1 là cấu hình riêng**, không âm thầm đổi B0: nhận cùng raw user history và các bảng trước trong budget ngang nhau; trả SQL hoặc yêu cầu làm rõ qua schema chung, nhận cùng requested-fields oracle; có PostgreSQL read-only và lỗi thực thi đã sanitize, không thấy gold. Tối đa một vòng sửa SQL từ lỗi cú pháp/thực thi, không được nhận nhãn “sai đáp án” hay sửa đến khi khớp gold. Không cấp QuerySpec/memory reducer của Texa cho B1. Phải implement/khóa adapter này trước khi công bố so sánh hội thoại; runner B0 hiện tại chưa tự hỗ trợ sẵn. B0+R là external baseline với dạng ví dụ Q→SQL khác Texa; hiệu ứng retrieval bên trong Texa được tách bằng **T10 so với T00**, không bằng B0+R so với T10. Trên hội thoại, đối chiếu Texa với B1 thay vì ép B0 không có history nhận điểm 0.

Giữ cùng model, source snapshot, catalog definitions, thông tin user, SQL read-only và oracle clarification. B0 không được thấy đáp án test; B0+R thấy SQL của **ví dụ training/bank**, không phải gold test. Giới hạn output theo schema mỗi hệ thống có thể khác; ghi rõ chứ không gọi mọi yếu tố inference là giống hệt.

### 7.2. Dataset và tránh leakage

- Các bộ đã dùng giữ làm regression/dev, không đổi tên thành holdout.
- Dự kiến bộ mới: **180 câu đơn (60 dev/120 test)**, **24 hội thoại (8 dev/16 test)**, **24 tình huống clarification (8/16)**; thêm tối thiểu **12 diagnostic ngoài scope/đối kháng** chấm action riêng. Hội thoại khoảng mười user turns trung bình chỉ là sizing; từng chat có thể dài hơn, đặc biệt để có >10 kết quả thành công. Final counts khóa sau review, trước test.
- Hai source hiện tại; chủ yếu Việt/Anh theo scope, báo riêng PT stress nếu giữ. Mỗi nguồn, metric được hỗ trợ và nhóm query phải có coverage, công bố bảng số lượng thay vì chỉ tổng số câu.
- Chia theo template/paraphrase families trước khi sinh biến thể; bank/dev/test không trùng câu hoặc họ paraphrase. Shared primitive như revenue/day được phép dùng, nhưng không copy gold mẫu rồi thay ngày/tên và gọi là test độc lập. Có holdout composed intents và wording do thành viên chưa xem prompt soạn.
- Có các ca phân biệt được: purchase/payment, item/order, category chỉ có non-purchase, event zero revenue, empty vs unavailable, NULL/duplicate, boundary dates, source negation/conflict, nested scalar có/không coverage, out-of-scope và prompt injection trong user text. Unsupported có action contract riêng, không trộn vào mẫu số SQL answerable.
- Gold SQL viết độc lập với compiler. Hai thành viên review scope, metric/grain, bảng, kỳ và oracle; lưu reviewer thật. Chưa có review người thứ hai thì chỉ được gọi là pilot/regression.
- Oracle lưu đầy đủ ý định ẩn nhưng chỉ trả field hệ thống hỏi, tối đa số vòng đã khóa. Tách `expected ask_fields` với toàn bộ ý định user như protocol4, không lặp lỗi thiếu period.
- Thiết kế thêm counterexample fixture để SQL sai không vô tình bằng gold trên một DB. Có thể kiểm lại cùng predicted SQL trên các fixture đồng schema; báo robustness riêng. Nếu thời gian/nguồn thay đổi làm câu hỏi đổi nghĩa thì phải instantiate gold/context tương ứng, không dùng lại SQL một cách mù quáng.
- Memory: mỗi turn có action, target result, QuerySpec/slot ops hoặc tập facts tham chiếu mong đợi. Discussion phải có contract facts/provenance và human-adjudication cho đáp án không tự chấm được; không regex một con số rồi xem là đúng. Chưa có scorer thì báo không chấm được, không công bố efficacy memory.

### 7.2a. Ma trận độ khó và tình huống cần có

| Nhóm câu đơn | Dev / test | Độ khó được xác định trước |
|---|---:|---|
| Core control | 12 / 24 | Metric, nguồn, kỳ rõ; aggregate hoặc một điều kiện đơn giản. Kiểm workflow không gây regression. |
| Semantic + data shape | 24 / 48 | Ít nhất một khác biệt có thể làm đổi kết quả: distinct user/event, item/order, purchase/payment, denominator, NULL/zero/missing, nested scalar, boundary date. Có fixture chứng minh query sai trả kết quả khác. |
| Composed in scope | 24 / 48 | Ít nhất hai khác biệt tương tác, vẫn một metric/một source: top-k buyers theo category sau lọc nested và kỳ; conversion có filter đúng cả quần thể; revenue theo tuần với literal/category và thời gian sát ranh giới. |

Tỷ trọng challenge cố định **20% / 40% / 40%**; công bố từng nhóm, từng nguồn và ngôn ngữ. Ít nhất 48/120 câu test cho mỗi source; ít nhất 72 tiếng Việt và 36 tiếng Anh, phần còn lại phân bổ theo coverage. Đây là trọng số của stress test, không suy ra tỷ trọng câu khó thực tế. Thứ tự top-k/ties phải có contract trước, không dùng các ca tie chưa quy định hành vi làm lỗi bất ngờ.

Ví dụ định hướng (ngày/giá trị cụ thể phải tồn tại trong fixture và không mang đáp án vào câu hỏi):

- “Trong kỳ này, mỗi danh mục có bao nhiêu người đã mua? Một người mua nhiều món chỉ tính một lần.” Đối chiếu gần nhau với “bao nhiêu lượt mua” để buộc phân biệt buyers/purchases; Olist có nhiều item lines cùng order để COUNT(DISTINCT order_id) trả kết quả sai.
- “Doanh thu tiền hàng Olist theo ngày, không cộng khoản thanh toán.” Fixture có payment-only day/category, purchase giá 0 và ngày cùng có cả hai loại; query sai miền nhóm hoặc cộng kép phải bị lộ.
- “Tỷ lệ người mua trong số người dùng được ghi nhận trên mobile trong kỳ.” Phải lọc đúng quần thể; numerator/denominator không được cùng biến thành chỉ người mua. Olist thiếu visitor/device thì chuyển sang action unavailable theo snapshot, không ép ra SQL cho nhóm answerable.
- “Ba danh mục có nhiều người mua nhất, chỉ tính mobile và tháng đã chọn.” Cùng primitive đơn giản nhưng kết hợp distinct users, ranking, nested scalar, filter và period. Chỉ answerable khi source snapshot có đường dẫn đã khai báo; không bịa device/campaign của Olist thật.
- Counterfactual pair: thay “giữ bộ lọc danh mục” thành “bỏ bộ lọc danh mục” phải đổi đúng slot, còn metric/source/kỳ được giữ. Không coi hai câu của một pair là hai family độc lập khi tính CI/split.

**Clarification 16 test scenarios:** gồm thiếu kỳ, thuật ngữ kinh doanh mơ hồ và xung đột nguồn; có matched explicit controls trong nhóm core/composed để chấm hỏi thừa. Ẩn một thông tin cần user xác nhận phải được chấm khả năng hỏi lại; không gán tùy tiện một gold SQL rồi phạt model vì không đoán trúng. Cả Texa/B1 có cùng intent oracle và giới hạn số vòng. Không đặt “hỏi lại” là đáp án mặc định cho mọi câu khó.

**Memory 16 test dialogues:** bốn chat cho mỗi khoảng **0–2, 3–6, 7–10, ≥11 kết quả thành công xen giữa** target và follow-up. Ghi thêm số message/noise, không đồng nhất 11 tin nhắn với 11 kết quả. Phải có quay lại target cũ, chuyển topic/source, giữ/đổi/xóa filter, đổi metric nhưng giữ kỳ và câu xã giao; target/source/filter của từng turn được review. Sample alternatives hoặc câu ví dụ retrieved không được thành memory. Task suy luận causal/tổng hợp ngoài scope không được đưa vào SQL accuracy để làm bộ “khó hơn”.

| Thành phần cần kiểm chứng | Nhóm tình huống | Dấu hiệu có giá trị |
|---|---|---|
| Semantic layer/binder | Buyers vs purchases; role purchase khác raw name; literal/filter theo source | Đọc đúng nghiệp vụ và bảng, ít sai grain/filter hơn baseline có cùng định nghĩa |
| Compiler | Payment-only groups, NULL, zero hợp lệ, ratio denominator | Kết quả đúng trên các counterexample worlds, không chỉ SQL hợp lệ |
| Clarification | Thiếu kỳ, sales mơ hồ, nguồn mâu thuẫn + explicit controls | Hỏi đúng chỗ, ít đoán sai và ít hỏi thừa |
| Memory | Target cũ qua >10 kết quả/noise; keep/set/clear | Đúng target và đủ các turn, vượt raw-history baseline nếu đo được |
| Retrieval mới | Cách diễn đạt/combination chưa nằm trong bank nhưng có primitive liên quan | T10 hơn T00; không chỉ trả đúng câu mẫu đã thấy |
| Consistency mới | Những ca trigger generic được đăng ký trước | Có nhiều override sửa đúng hơn làm hỏng; T01/T11 tăng chất lượng tương xứng cost/latency |

**Fixture:** tối thiểu ba data worlds đồng schema, khác số lượng, giá trị và sparsity; có realistic sanitized slice từ hai nguồn khi dữ liệu/quyền hiện có cho phép, cùng counterexample synthetic có provenance. Coverage không chỉ là số rows lớn: cần truy vấn sai phổ biến như đếm order thay item, đếm event thay user, sum payment + purchase, lọc tử số xuống mẫu số, drop mọi zero, nhầm NULL/missing JSON và dùng clock hiện tại đều bị phân biệt ở fixture tương ứng. Không tải domain mới hoặc tự gán thuộc tính không có cho dữ liệu thật. Gold và business rule phải thống nhất trước khi model chạy.

Mỗi scenario cần metadata: family/pair, stratum, phenomena, source/language/capabilities, lý do độ khó, expected action, input context, gold độc lập, oracle đầy đủ nếu cần, result contract, fixture worlds, reviewer và review status. Code kiểm tra schema/coverage không thay human review. `scenario_blueprints.yaml` hiện chỉ cung cấp câu/behavior để nhóm duyệt; thiếu gold hoặc human review thì không mang nhãn sealed/ready.

### 7.3. Metric và protocol

**Chính:** business-result accuracy trên toàn bộ câu answerable; đúng khi bảng sau truy vấn đáp ứng đủ measure, dimension, grain, rows, NULL/duplicate, tolerance và ordering đã khai báo trước. SQL không phải giống gold. Refusal sai, lỗi, timeout vẫn là sai; không chỉ tính trên câu chạy SQL được. Báo thêm challenge summary theo trọng số stratum khóa trước, không gộp clarification/memory/unsupported thành một điểm SQL duy nhất. Ba fixture worlds đo robustness riêng, không nhân ba số câu độc lập.

**Phụ:** output-contract compliance; false refusal; unsupported/action correctness; clarification precision/recall và số vòng; conversation all-required-turn success khi mọi turn chấm được; memory reference/slot accuracy dùng để chẩn đoán; tokens/USD, calls/attempts, queue/interpret/SQL-ready/end-to-end p50/p95.

Riêng thành phần mới: retrieval relevance/coverage theo nhãn; trigger rate; có ích khi override phương án đầu bao nhiêu; override làm đúng thành sai bao nhiêu; sai dù đồng thuận; tỷ lệ không đạt đồng thuận/fallback. Không dùng đồng thuận hoặc exact QuerySpec làm metric cuối thay cho đáp án truy vấn.

- Khóa code, bank/index, sampling config, trigger thresholds, seed nếu provider hỗ trợ, catalog, fixture, scorer và hashes **trước test**.
- Chạy ba repeats, thứ tự variant được xoay; cùng case dùng các cấu hình để so paired. Không tune sau khi xem test. Nếu phát hiện lỗi protocol, giữ raw và đánh dấu invalid trước khi chạy version mới.
- Báo điểm từng repeat và trung bình; paired confidence interval resample theo independent question/template hoặc dialogue cluster, không coi ba repeats hay tám turns trong một chat là các mẫu độc lập.
- Báo chênh lệch điểm phần trăm và error reduction khi phù hợp, không hứa “accuracy tăng nhiều lần”. Khoảng tin cậy chứa 0 thì chưa có bằng chứng thắng. 120 câu test có thể chưa đủ phát hiện chênh lệch nhỏ; dùng discordance trên dev để dự toán precision/power trước khi khóa cỡ mẫu, không mở rộng tùy kết quả test.

### 7.4. Ngân sách chạy

Với B0/B0+R chỉ chạy 120 câu đơn; B1 và bốn cấu hình Texa chạy 120 câu đơn + 16 hội thoại × khoảng mười turns + 16 clarification × khoảng hai turns: ba repeats tương đương **[2 × 120 + 5 × (120 + 160 + 32)] × 3 = 5.400 user-turn executions**. Dùng giá trung bình v3 khoảng 0,000597 USD/turn là **3,22 USD**; nhân 1,5 dự phòng cấu hình mới/context thành **4,84 USD**, cộng pilot khoảng **0,75 USD** thành **5,59 USD**. Chưa gồm diagnostic action suite, extra correction calls của B1 và các chat dài hơn; phải size lại sau pilot. Counterexample re-execution có thể tái dùng predicted SQL hợp lệ, không mặc định thêm LLM calls.

Đặt sub-budget dự kiến **6 USD cho phần nghiên cứu thực nghiệm mới**, luôn nhỏ hơn ngân sách khả dụng của ledger gốc. Sau pilot thay dự toán bằng actual per-suite cost, tính cả retry/reservations; chỉ chạy matrix nếu phần còn lại đủ cho một paired block hoàn chỉnh. Thiếu tiền thì dừng có báo coverage, không chọn bỏ các lượt thất bại. Không gọi thêm model trong giai đoạn plan này.

## 8. Thứ tự implement và commit

Mỗi bước lớn commit trên `main`, không tạo branch mới. Trạng thái triển khai thực tế ở mục 10; các gate chưa đạt vẫn giữ mở.

| Bước | Việc và điểm sửa dự kiến | Điều kiện xong |
|---|---|---|
| B−1 | Chốt design/strata/baselines, viết scenario blueprints và validator; sau đó author fixture/gold độc lập, review và lập split | Blueprint draft không bị coi là executable holdout; không chọn/bỏ câu theo hệ thống nào thắng; review/coverage đủ trước freeze |
| 0 | Adjudicate miền nhóm/empty/coverage; `catalog/product_events.yaml`, `catalog.py`, `compile.py`; trace refusal trong `answer.py`/eval | Regression độc lập cho compiler; lý do refusal truy được; artifact pre/post riêng |
| 1 | Contract bank approved + validator, ví dụ đa dạng có review; `catalog/verified_examples.yaml`, module loader mới, liên kết `catalog.py` | Sai ID/version/source/QuerySpec bị reject; CI kiểm độc lập reference SQL; bank không đọc thư mục eval test |
| 2 | Module retrieval/packing mới, tích hợp `interpret.py`/`prompts.py`; cờ R mặc định tắt | Dev relevance + no-example fallback; token budget; catalog/registry ưu tiên; trace IDs, không thêm LLM call |
| 3 | Tách normalization/binder/reducer dry-run thành contract không ghi state; module decision mới nếu cần | Candidate query/clarify/refuse/follow-up giữ nghĩa; bộ test equivalence/không-equivalence, source/time/NULL/ops và version guards |
| 4 | Sampling config và selective consistency; `llm.py`, `interpret.py`, `answer.py`, `runtime_guard.py`, `gateway_budget.py` | Sampling capability được xác minh; tối đa ba candidate; budget/timeout/cancel/no late write; hai samples cùng context, không chia sẻ state mutable |
| 5 | Cờ đánh giá độc lập R/C, mở rộng `ablation.py`, `eval/run_ablation.py`, `report_ablation.py`, `validate_dataset.py` và provenance | Matrix 2×2 + B0/B0+R; bỏ thành phần thật sự bỏ prompt/calls đó; coverage và invalid protocol được phát hiện |
| 6 | Pilot/dev, chọn bank/retrieval/trigger bằng dữ liệu dev, khóa protocol | Chứng minh có diversity và lợi ích đủ bù chi phí; nếu voting không ích lợi thì không bật |
| 7 | Chạy holdout có review, ba repeats + raw reports; kiểm load và E2E | Paired blocks đầy đủ, không thay test/gold để tăng điểm; báo cả regressions/CI và actual cost |
| 8 | Chọn cấu hình rollout theo gate; cập nhật `PRODUCT_SCOPE.md`, `FINAL_PRESENTATION_SCRIPT.md`, tracker này và issue plan | Script chỉ dùng số đã đo đúng phiên bản; toggle rollback hoạt động; commit/push; chỉ bật `run.sh` khi cần smoke/E2E rồi tắt khi xong |

File/module mới có thể đổi tên khi implement theo convention hiện có; các điểm tích hợp được xác nhận là `interpret.py:23/145`, `prompts.py`, `answer.py` (interpret rồi memory/clarify), `compile.py:150–196`, `spec.py:44`, `llm.py` và eval runners. Không chuyển LLM sang sinh SQL trực tiếp để dễ dùng ví dụ SQL.

## 9. Kiểm thử và gate quyết định bật

Các ngưỡng sau là **đề xuất acceptance criteria cần khóa trên dev**, không phải kết quả đã đạt:

1. T11 so với T00: mục tiêu tăng ít nhất **5 điểm phần trăm** trên primary answerable holdout; báo paired CI. Nếu CI chưa xác lập lợi ích thì chưa tuyên bố hơn. Vẫn phải báo B0 và B0+R dù baseline thắng.
2. Retrieval hoặc consistency không đạt lợi ích riêng thì cân nhắc chỉ bật thành phần còn lại; có thể chọn T10 thay T11. Không bắt buộc triển khai cả hai để hợp với ý tưởng ban đầu.
3. Không có regression đã xác nhận về source/currency/grain/khả năng ghi DB, session isolation, memory lineage hay hỏi lại bắt buộc; mọi lỗi nghiêm trọng là rollout blocker, không được bù bằng điểm trung bình cao.
4. Chi phí trung bình mục tiêu ≤**1,5× T00**; single-user p95 end-to-end ≤**1,25× T00** trên workload giống nhau. Đo riêng trigger p95 để không che đuôi chậm. Nếu trượt thì ưu tiên retrieval-only hoặc giữ cờ off.
5. Tải tám phiên thật: không thêm provider attempt lỗi/cross-session reads, đo throughput và queue p95, không chỉ một batch; so với T00 cùng tải và không gọi đó là classroom capacity nếu chưa thử tải đại diện. Retry/timeout vẫn nằm trong mẫu số.
6. Backend tests phù hợp thay đổi; Playwright mock kiểm retrieval trace, conflict form, pending/cancel, sửa câu, stale bank/catalog và nhiều session. Sau đó `run.sh` và browser dùng model thật: hai source, tám metric hỗ trợ đúng, ca khó/không hỗ trợ, >10 kết quả + noise, follow-up sửa/xóa filter, export/history. Ghi cả lỗi và chi phí.

Nếu không đạt gate, kết quả hợp lệ vẫn được giữ và báo cáo. Thành công của công việc là biết thành phần nào giúp sản phẩm với chi phí chấp nhận được; không phải làm benchmark xanh bằng mọi giá.

## 10. Trạng thái triển khai ngày 06/11/2026

- Đã sửa miền nhóm trong catalog/compiler bằng `metric_support`; ratio giữ support của cả tử và mẫu. Có kiểm thử PostgreSQL độc lập cho payment-only groups, zero và NULL.
- Đã tích hợp retrieval có version/fingerprint, source gating, whole-example packing và trace; bank 45 bản ghi, 42 được agent review, ba draft bị loại. Chỉ bảy ví dụ SQL đã được thực thi kiểm chứng độc lập; nghiên cứu B0R/T10/T11 dùng cùng tập bảy ví dụ này. Không gọi đó là human review.
- Đã tích hợp selective self-consistency: primary + hai samples tối đa, cùng model/prompt/provider defaults, chuẩn hóa qua reducer/binder/validator không ghi trạng thái. Bounded executor, admission, cancellation, timeout và ledger áp dụng cho mọi call. Clarification hợp lệ không bị hai phương án đoán đủ slot bỏ phiếu lấn át. Không có majority thì từ chối bảo thủ.
- Hai cờ `TEXA_EXAMPLE_RETRIEVAL` và `TEXA_CONSISTENCY` **mặc định tắt**. Không suy diễn rằng các sample cùng model chắc chắn đa dạng hay voting chắc chắn tốt hơn.
- Candidate hiện có 60 câu đơn (30 dev/30 test), 24 clarification records (12 cặp), chín hội thoại và 12 diagnostic cases. Ba worlds có 120/121/118 dòng; 180 bảng đáp án câu đơn được SQL độc lập tính trên ba worlds. Olist không có viewer/session; nested Olist là synthetic challenge extension. Bộ này chưa đạt cỡ mẫu mục 7, chưa được người thẩm định và chưa phải holdout sealed.
- Dev matrix dùng `gpt-6-luna`, một repeat tại `81b3d3c`: câu đơn B0/B0R 29/30, B1 25/30, T00 27/30, T10 26/30, T01 28/30, T11 27/30 sau sửa lỗi annotation c19. Raw giữ nguyên; `single-summary-corrected.json` ghi hash và mọi thay đổi điểm. Câu hỏi/gold SQL/đáp án không đổi; prose c19 được chuyển sang `business_note` ở candidate hiện hành.
- Cross-world replay không gọi model: mọi cấu hình giữ cùng số đúng trên cả ba worlds. Replay áp dụng đúng public-output projection của Texa, không chấm auxiliary sample columns như dữ liệu người dùng. Kiểm tra phụ bỏ qua alias: B0/T00/T01 cùng 29/30; T10/T11 28/30. Đây là phân tích phụ sau quan sát, không thay primary protocol hay chứng minh superiority.
- Clarification dev: B1 9/12, T00 10/12, T10 12/12, T01 11/12, T11 10/12. Một lượt, nhỏ và đã nhìn thấy; không suy rộng. Raw memory comparison đầu bị lỗi JSON Decimal/date và mẫu số khi baseline runner thất bại; đánh dấu không hợp lệ, sửa adapter và chạy lại đủ năm cấu hình riêng.
- Evidence: `data/benchmark/results/accuracy-dev-20261106-v2/INTERPRETATION.json`, `single-summary-corrected.json`, `world-robustness-*-v2.json`; có snapshot bộ dữ liệu gốc để tái lập erratum. Pilot sai protocol và world reports trước sửa projection vẫn được giữ, có chú thích không dùng làm kết luận.
- Chưa đạt gate tăng accuracy: không bật tính năng mới mặc định, không tuyên bố Texa hơn LLM trực tiếp. Hội thoại repaired: B1 7/8, T00/T10/T01 8/8, T11 7/8. Diagnostic action: B1 2/10, T00/T01/T11 7/10, T10 6/10; hai rubric cần review riêng. Browser model thật: 19/21 bảng đúng, hai false refusals; memory ordinal đúng sau 13 kết quả + noise. Backend 323 passed/36 skipped; Playwright 15/15. Không gộp các nhóm hoặc biến scripted checks thành holdout.

Việc còn bắt buộc trước nghiên cứu xác nhận: review nghiệp vụ độc lập (đặc biệt câu dễ nhầm source với category), bổ sung case thực tế theo strata đã chốt, review gold và seal test, ba repeats có xoay thứ tự, paired CI và tải đại diện. Không làm khó bộ câu hỏi chỉ để baseline giảm điểm. Điểm baseline cao trong scope hẹp không tự chứng minh benchmark sai.

### Gate sau đo

Không rollout retrieval/consistency: T11 không tăng điểm so với T00 (paired delta 0, CI95% khoảng −9,7…+10,0 điểm % trên dev), p95 câu đơn 22,4 giây so với 15,2 giây (1,48×, vượt gate 1,25×). Chi phí 30 câu đơn T11 khoảng 0,02064 USD, T00 0,01922 USD (1,07×). Retrieval-only có một diagnostic AOV bị đổi thành metric khác. Các số này là dev một lượt; không thay thế gate holdout.

Tái lập correction trên artifact gốc: dùng `report_accuracy_study.py --compare --annotation-erratum c19-prose-contract-v1 --dataset-dir data/benchmark/results/accuracy-dev-20261106-v2/frozen_dataset` với các `single-*.jsonl`. Replay worlds dùng cùng snapshot, `check_world_robustness.py`, reader không superuser và database cô lập 15433; cần explicit fixture flag, có restore trong finally. Không gọi thêm model khi replay. Hai feature flags cũng được ghi trong `.env.example`.
