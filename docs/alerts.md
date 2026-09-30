# Alert và Runbook

Mỗi alert phải dựa trên triệu chứng người dùng hoặc SLO, không dựa trực tiếp vào tên implementation nội bộ.

## Alert 1

- Tên: `HighLatencyP95`
- Severity: `warning`
- Duration: `5m`
- Kênh thông báo: Slack `#k4-l3b-alerts`
- SLI/SLO liên quan: latency P95 của event `response_sent`; SLO request hoàn tất trong 3000ms.
- Điều kiện và thời gian duy trì: `p95(response_sent.latency_ms) > 3000` liên tục trong 5 phút.
- Ảnh hưởng tới người dùng: phần request chậm nhất phải chờ quá ba giây để nhận câu trả lời.
- Ba bước kiểm tra đầu tiên:
  1. Xác nhận P50/P95/P99 và TTFT trên panel Latency, ghi lại khoảng thời gian bắt đầu tăng.
  2. Lọc `response_sent` trong khoảng đó, chọn request có `latency_ms` cao và lấy `correlation_id`.
  3. Mở trace cùng `correlation_id`, so sánh duration của `retrieval` và `generation`.
- Mitigation tạm thời: tắt practice incident nếu đang bật; nếu generation tăng sau khi đổi prompt thì rollback label `production`; nếu retrieval chậm thì giảm tải và kiểm tra nguồn dữ liệu.
- Owner: `student-2A202602587`

## Alert 2

- Tên: `HighRequestErrorRate`
- Severity: `critical`
- Duration: `5m`
- Kênh thông báo: Slack `#k4-l3b-alerts`
- SLI/SLO liên quan: tỷ lệ `request_failed` trên tổng `request_received`; SLO availability 99.5%.
- Điều kiện và thời gian duy trì: error rate lớn hơn 2% liên tục trong 5 phút.
- Ảnh hưởng tới người dùng: request trả HTTP 500 và không nhận được câu trả lời.
- Ba bước kiểm tra đầu tiên:
  1. Xác nhận error rate và breakdown `error_type` trên panel Errors.
  2. Lấy `correlation_id` của một `request_failed` đại diện và kiểm tra `tool_name`, `tool_success`.
  3. Mở trace tương ứng để xác định observation lỗi và thông báo trạng thái an toàn, không chứa PII.
- Mitigation tạm thời: tắt incident gây lỗi, khôi phục dependency/config gần nhất và giảm concurrency nếu lỗi do quá tải.
- Owner: `student-2A202602587`

## Alert 3

- Tên: `LowRetrievalSuccessRate`
- Severity: `warning`
- Duration: `10m`
- Kênh thông báo: Slack `#k4-l3b-alerts`
- SLI/SLO liên quan: tỷ lệ `tool_success=true` của retrieval; guardrail tối thiểu 90%.
- Điều kiện và thời gian duy trì: retrieval success rate thấp hơn 90% liên tục trong 10 phút.
- Ảnh hưởng tới người dùng: câu trả lời thiếu context, giảm chất lượng hoặc request thất bại.
- Ba bước kiểm tra đầu tiên:
  1. Xác nhận retrieval success và quality score trong cùng khoảng thời gian.
  2. Lọc log có `tool_name=retrieval` và `tool_success=false`, lấy một `correlation_id`.
  3. Mở observation `retrieval` trong trace tương ứng để kiểm tra duration, trạng thái và số document.
- Mitigation tạm thời: kiểm tra vector store, tắt incident `tool_fail`, dùng fallback an toàn và giảm lưu lượng tới retrieval nếu dependency chưa phục hồi.
- Owner: `student-2A202602587`
