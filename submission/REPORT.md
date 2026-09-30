# Báo cáo cá nhân — K4-L3B Day 13 Monitoring & LLMOps

> Mỗi học viên hoàn thiện một file duy nhất này. Khi dẫn evidence, dùng đường dẫn tương đối, ví dụ `evidence/07-trace-waterfall.png`.

## 1. Thông tin học viên

- **Họ và tên:**Đặng Thế Vinh
- **MSSV:**2A202602587
- **Lớp:** K4-L3B
- **Repository URL:**https://github.com/HnivGnad/K4-L3-DAY13-DangTheVinh-2A202602587-Monitoring-LLMOps.git
- **Commit SHA cuối:**97f4848225bbdcdd1feee2568446d7a81d400fe9
- **Challenge ID:** `day13-k4-l3b-monitoring-llmops-v1`
- **Tên project Langfuse cá nhân:** `day13-k4-l3b-2A202602587`

## 2. Evidence index

Điền đúng đường dẫn tới evidence thực tế. Có thể đổi tên hoặc dùng nhiều ảnh nếu cần.

| Evidence | Đường dẫn |
|---|---|
| Pytest cuối | `evidence/01-pytest.png` |
| Log validator | `evidence/02-log-validator.png` |
| Dashboard validator | `evidence/03-dashboard-validator.png` |
| Structured log | `evidence/04-structured-log.png` |
| PII redaction | `evidence/05-pii-redaction.png` |
| Trace list | `evidence/06-trace-list.png` |
| Trace waterfall | `evidence/07-trace-waterfall.png` |
| Trace metadata | `evidence/08-trace-metadata.png` |
| Prompt versions | `evidence/09-prompt-versions.png` |
| Prompt rollback | `evidence/10-prompt-rollback.png` |
| Dashboard runtime | `evidence/11-dashboard-overview.png` |
| Incident metric | `evidence/12-incident-metric.png` |
| Incident log | `evidence/13-incident-log.png` |
| Incident trace | `evidence/14-incident-trace.png` |

## 3. Kết quả kỹ thuật

| Nội dung | Baseline | Kết quả cuối | Nhận xét |
|---|---|---|---|
| `validate_logs.py` | Không lưu artifact baseline | 100/100 | 23 correlation ID, đủ enrichment, 0 PII leak |
| `validate_dashboard.py` | Không lưu artifact baseline | 6/6 panel | Contract hợp lệ |
| `pytest` | Không lưu artifact baseline | 29 passed | Chạy lại thành công trên workspace cuối |
| Số traces hợp lệ | 0 | 20 generation spans | 11 dùng prompt v1, 9 dùng prompt v2 |
| Số PII leak | Chưa ghi nhận | 0 | Kiểm tra trên workload mẫu |
| Latency P95 / TTFT P95 | Chưa ghi nhận | khoảng 154ms / 50ms | Workload fake LLM bình thường |
| Retrieval success rate | Chưa ghi nhận | 100% | Workload không bật incident |

## 4. Logging và PII

- **Cách tạo/nhận và truyền correlation ID:** middleware xóa context cũ ở đầu request, ưu tiên header `x-request-id` hợp lệ; nếu không có thì sinh `req-<8 ký tự hex>`. ID được bind vào `structlog.contextvars`, truyền vào agent/Langfuse metadata, trả lại qua header `x-request-id` và xuất hiện trên mọi log của request.
- **Các metadata được ghi vào structured log:** `ts`, `level`, `service`, `event`, `correlation_id`, `user_id_hash`, `session_id`, `feature`, `model`, `env`; log kết quả bổ sung latency, TTFT, token input/output, cost, quality score và trạng thái retrieval. Evidence: [`evidence/04-structured-log.png`](evidence/04-structured-log.png).
- **Cách bảo đảm PII được scrub trước khi ghi:** `user_id` được băm SHA-256 rút gọn; email, số điện thoại Việt Nam, CCCD, thẻ và hộ chiếu được thay bằng marker `[REDACTED_*]`. Processor `scrub_event` xử lý đệ quy context và payload sau khi format exception nhưng trước cả file JSONL lẫn console JSON renderer.
- **Cách kiểm chứng kết quả:** workload chứa PII giả cho thấy ba loại dữ liệu đã bị thay thế trong [`evidence/05-pii-redaction.png`](evidence/05-pii-redaction.png); validator độc lập quét toàn bộ 257 record và báo `0` potential PII leak, `100/100` tại [`evidence/02-log-validator.png`](evidence/02-log-validator.png).

## 5. Tracing và prompt versioning

- **Cách xác nhận traces do chính tôi tạo trong project cá nhân:** chạy `scripts/generate_traces.py` bằng key trong `.env`, sau đó truy vấn Observations API v2 trong đúng project và đối chiếu correlation ID.
- **Cấu trúc root/retrieval/generation observations:** `lab-agent-run` là root agent; `retrieval` là child loại retriever; `generation` là child loại generation có model, TTFT, usage và cost.
- **Cách nối trace với log:** dùng cùng metadata `correlation_id`; input/output trên trace chỉ lưu preview đã scrub.
- **Prompt name:** `day13-chat`.
- **Version/label baseline:** version 1, labels `baseline` và `production` sau rollback.
- **Version/label candidate:** version 2, label `candidate`.
- **Trace ID của mỗi version:** v1 `5b458b04c078a6f475230148900d48ba` (`req-726c3055`); v2 `d3801d02e6d1ca9998abd4c4a7bda062` (`req-7f2ccfb2`).
- **Cách promote và rollback `production`:** `python scripts/manage_prompts.py promote` chuyển `production` sang v2; `python scripts/manage_prompts.py rollback` đưa `production` về v1. Trạng thái cuối là `production -> day13-chat v1`.

## 6. Dashboard, SLO và alerts

- **Dashboard và sáu panel:** latency P50/P95/P99 + TTFT P95, traffic, errors + retrieval success, cost, tokens và quality; time range 60 phút, refresh 30 giây và mỗi panel có threshold.
- **SLO và lý do chọn:** 99.5% request phải có `response_sent` với latency không quá 3000ms trong 28 ngày. Baseline fake workload khoảng 154ms nên ngưỡng này có dư địa tải nhưng vẫn giới hạn thời gian chờ người dùng.
- **Cách tính error budget:** `100% - 99.5% = 0.5%`; với 10,000 request, tối đa 50 request được phép lỗi hoặc chậm hơn 3000ms.
- **Ba alert và runbook tương ứng:** `HighLatencyP95` (>3000ms/5m), `HighRequestErrorRate` (>2%/5m), `LowRetrievalSuccessRate` (<90%/10m); đều gửi Slack `#k4-l3b-alerts` và có runbook tại `docs/alerts.md`.

> Ví dụ cách viết error budget: "SLO 99.5% trong 28 ngày nghĩa là error budget 0.5%. Nếu workload có 10,000 request thì tối đa 50 request được phép lỗi hoặc chậm hơn ngưỡng SLO."

## 7. Điều tra challenge

- **Challenge ID:** `day13-k4-l3b-monitoring-llmops-v1`.
- **Khoảng thời gian điều tra:** `2026-09-30 04:14:38–04:14:54 UTC` (`11:14:38–11:14:54` giờ Asia/Bangkok). Evidence metric: [`evidence/12-incident-metric.png`](evidence/12-incident-metric.png).
- **Triệu chứng từ metrics:** 5 request challenge đều chậm; latency P50 `2654ms`, P95/P99 `3692ms`, vượt ngưỡng challenge `2000ms`. TTFT P95 vẫn `50ms`, error rate `0%` và retrieval success `100%`, nên đây là latency regression trước bước generation chứ không phải lỗi model/tool.
- **Log line và correlation ID liên quan:** dòng `response_sent` lúc `2026-09-30T04:14:45.447328Z` có `correlation_id=req-bff1e9b0`, `latency_ms=2654`, `ttft_ms=50`, `tool_name=retrieval`, `tool_success=true`. Evidence log: [`evidence/13-incident-log.png`](evidence/13-incident-log.png).
- **Trace ID và span gây ảnh hưởng:** trace `b3deafba39cb46dc68078b6e5fab2252` có cùng `correlation_id=req-bff1e9b0`; root `lab-agent-run` mất `2658ms`, child `retrieval` mất `2505ms`, còn `generation` chỉ `151ms` với TTFT `50ms`. Evidence trace: [`evidence/14-incident-trace.png`](evidence/14-incident-trace.png).
- **Root cause:** incident `rag_slow` đưa độ trễ chặn `2.5s` vào `app/mock_rag.py::retrieve`. Metric khoanh vùng latency, log chọn đúng request, và trace xác nhận retrieval chiếm khoảng 94% thời gian root; prompt `day13-chat v1` và generation không phải nguồn regression.
- **Fix action:** gọi `POST /incidents/rag_slow/disable` để bỏ delay được inject và xác nhận `/health` trả `rag_slow=false`. Trong môi trường thật, cần rollback thay đổi retrieval hoặc chuyển traffic sang backend khỏe trước khi điều tra sâu hơn.
- **Preventive measure:** duy trì alert `HighLatencyP95`, runbook Metrics → Logs → Traces, đồng thời thêm guardrail riêng cho retrieval latency (ví dụ P95 ≤ `1000ms`), timeout/circuit breaker và test regression để phát hiện dependency chậm trước khi phát hành.

> Gợi ý cách viết ngắn, không thay cho evidence thực tế: "Metric cho thấy `[latency/error/cost/quality]` bất thường trong `[khoảng thời gian]`. Log line `[event]` có `correlation_id=[...]` đại diện cho request bị ảnh hưởng. Trace cùng `correlation_id` cho thấy span `[retrieval/generation/prompt/tool]` có dấu hiệu `[chậm/lỗi/token tăng]`. Root cause là `[nguyên nhân suy ra từ evidence]`. Fix action là `[hành động khôi phục]`; preventive measure là `[alert/runbook/test/guardrail để ngăn tái diễn]`."

## 8. Giải thích và tự đánh giá

- **Một quyết định kỹ thuật quan trọng và lý do:** đặt PII scrubbing tại processor chung của logging thay vì gọi thủ công ở từng endpoint. Nhờ vậy context, payload lồng nhau và exception đều đi qua cùng một điểm kiểm soát trước khi được ghi; child observations `retrieval` và `generation` đồng thời tách riêng thời gian từng bước để trace có giá trị điều tra.
- **Một lỗi/blocker đã gặp:** khi tạo cache dependency trong workspace đang được `uvicorn --reload` theo dõi, server tự reload giữa workload challenge, làm reset incident state và in-memory metrics. Các lần chạy đó bị loại vì không còn cùng một khoảng sự cố ổn định.
- **Cách tìm nguyên nhân và xử lý:** đối chiếu timestamp log với `/health`, nhận ra `rag_slow` đã chuyển về `false` giữa lượt chạy; sau đó bật incident lại, không tạo/chỉnh file trong lúc workload chạy, gửi đủ năm request rồi mới truy vấn metrics và Langfuse. Chỉ lượt ổn định `04:14:38–04:14:54 UTC` được dùng làm evidence.
- **Cách hiểu luồng Metrics → Logs → Traces:** metrics cho biết loại triệu chứng và cửa sổ thời gian; log trong cửa sổ đó cung cấp một `correlation_id`; trace có cùng ID cho biết child span nào chiếm thời gian hoặc phát lỗi. Với challenge này, P95 khoanh vùng latency, log chọn `req-bff1e9b0`, và trace xác nhận retrieval chiếm `2505/2658ms`.
- **Vai trò của prompt version, token/cost, SLO hoặc rollback trong vận hành LLM:** prompt version giúp so sánh thay đổi hành vi mà không sửa code và rollback label `production` nhanh; token/cost phát hiện output phình hoặc chi phí tăng; SLO/error budget biến chất lượng thành mục tiêu đo được; alert và runbook rút ngắn thời gian phát hiện–khôi phục. Evidence cuối xác nhận `production` đã rollback từ v2 về v1.
- **Điều quan trọng nhất đã học:** correlation ID nhất quán là khóa nối ba lớp quan sát; không nên kết luận root cause từ một metric hoặc một trace riêng lẻ khi chưa đối chiếu cùng request và thời gian.
- **Hạn chế hoặc phần chưa hoàn thành, nếu có:** ứng dụng dùng fake LLM, metrics nằm trong memory và evidence là snapshot nên chưa đại diện cho hệ thống phân tán dài hạn. Khi production cần metrics backend bền vững, alert delivery thật, retention phù hợp và load test dài hơn. Artifact baseline trước CP1 không được lưu nên báo cáo ghi rõ thay vì tái tạo dữ liệu giả.

## 9. Checklist trước khi nộp

- [x] Kết quả và evidence thuộc commit SHA cuối.
- [x] Tất cả ảnh/output mở được bằng đường dẫn tương đối.
- [x] Incident evidence nối đúng metric → log → trace.
- [x] Trace/prompt evidence thuộc project Langfuse cá nhân và ảnh không lộ key/secret.
- [x] Repository chạy lại được theo README.
- [x] Không có secret, API key, PII thô hoặc evidence của người khác/lớp khác.
- [ ] URL repo và commit SHA cuối đã được nộp trên LMS/Codelabs.
