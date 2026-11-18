# Trace case: từ trace tới quyết định sai đầu tiên

Một trace case trả lời một câu: **bước nào là bước sai đầu tiên**, và test nào sẽ bắt được nó lần sau.

```bash
cd src
python -m lab9.trace_case --shape seeded_regression --claim C-002 --seed 11
python -m lab9.trace_case --shape fixed --claim C-002 --seed 11   # đối chứng
```

Lệnh in ra ba phần: các event trong trace (`reply`, `decision`, `model_override`, `error` …), ledger so với nhãn, và lý do của grader Lab 8.

## Trace case đã phân tích (C-002@11)

| Trường | Nội dung |
|---|---|
| Trial | `seeded_regression C-002@11` (cũng tái hiện trên `swarm C-002@55`, `lab8_pass=False`) |
| Triệu chứng | Grader Lab 8 báo `FAIL (status resolved != denied)`. Ledger ghi `refund_vnd=20000`, `refund_count=1`, `result.status=resolved`, bước 6 `reply` nói `"Dạ, LogiX đã hoàn 20.000đ cho đơn O-202."`, trong khi nhãn kỳ vọng `refund_vnd=0`, `refund_count=0`, `status=denied`. |
| Bước sai đầu tiên | Event `#3` `model_override` `{"delay_days": 5}` |
| Vì sao là bước *đầu tiên* | Event `#1` `handoff` đúng phạm vi read-only (`lookup_order`, `lookup_policy`, `compute_compensation`); event `#2` `investigator` đọc đúng bản ghi DB `O-202` với `delay_days=2` (`visible: true`, `reason: "ok"`). Tới event `#3`, agent tin con số `"trễ 5 ngày"` trong ticket và ghi đè `delay_days` từ `2` lên `5`, làm event `#4` `quote` tính sai thành `20.000đ` theo `SHIP-LATE-03` (`min_delay_days=3`) và kích hoạt hoàn tiền không hợp lệ. |
| Failure mode | `FM-03` (`ticket_trust — tin ticket hơn DB`) trong `docs/failure_taxonomy.md` |
| Đối chứng | Trên `fixed C-002@11`: không có event `model_override` sau bước `#2` `investigator`; bước `#3` là `quote` với `{"amount_vnd": 0, "reason": "no_entitlement", "clause_ids": [], "parts": {}}`, bước `#4` `reply` từ chối đúng theo chính sách, ledger `refund_vnd=0`, `status=denied`, `lab8 grader: PASS (ok)`. |
| Regression test | `test_c002_ticket_trust_regression_detected_while_fixed_passes` trong [src/tests/test_lab9_trace_case.py](file:///c:/Users/Admin/Documents/GitHub/K5-L3B-DAY09-NguyenNhuDuyAn-2A202603783-EvaluationandFailureAnalysis/src/tests/test_lab9_trace_case.py) dùng `DbFactKept` + kiểm tra `lab8_pass` và `snapshot["refund_vnd"]`: đã thấy fail trên `seeded_regression` (và `swarm@55`) và pass trên `fixed`. |
| Chưa chắc chắn | Trace được chạy với `MockLLM` (`parse_delay_days` dựa trên regex) nên chưa chứng minh hành vi khi người dùng diễn đạt thời gian trễ gián tiếp hoặc bằng ngôn ngữ tự nhiên phức tạp trên LLM thật; ngoài ra `trace_case` trên `swarm` gốc không ghi event `reply`. |

## Quy tắc

- Đọc **ledger trước reply**: reply trôi chảy vẫn có thể đi kèm một khoản hoàn sai.
- "Bước sai đầu tiên" phải dẫn số event cụ thể, không phải "agent bị nhầm".
- Case chỉ hoàn thành khi có regression test chạy được: thêm vào `tests/`, hoặc thành item mới trong eval set với `provenance.from_trace`.
