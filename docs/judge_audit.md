# Judge audit

Chạy: `python -m lab9.judge --csv <file> --audit 5`

| Tiêu chí | n | κ | Precision | Recall | Tỉ lệ lỗi quan sát → Rogan-Gladen | Đạt FLOORS (κ≥0.6, P≥0.8, R≥0.7)? | Quyết định |
|---|---|---|---|---|---|---|---|
| tone_ok (`judge_tone_public.csv`) | 100 | 0.757 | 0.857 | 0.800 | 0.280 → 0.300 | Đạt (κ≥0.6, P≥0.8, R≥0.7) | **dùng** (chỉ cho tone, không thay thế kiểm tra ledger) |
| helpful (`judge_helpful_public.csv`) | 100 | 0.375 | 1.000 | 0.300 | 0.090 → 0.300 | Không đạt (κ=0.375 < 0.6, R=0.300 < 0.7) | **loại** (không được dùng làm gate) |

## ≥5 case audit thủ công

| # | Case | Judge nói | Người nói | Ai đúng? | Ghi chú & Hành động sửa rubric / nhãn |
|---|---|---|---|---|---|
| 1 | `H-008` (`tone_ok`) | PASS | FAIL | Người đúng | `"Em đã hoàn tiền cho anh rồi nha, anh check giúp em."` — xưng `'em'` + `'nha'` suồng sã; sửa rubric `tone_ok`: cấm đại từ thân mật (`em`, `bạn`, `nha`), bắt buộc xưng hô `LogiX` / `anh/chị`. |
| 2 | `H-017` (`tone_ok`) | PASS | FAIL | Người đúng | `"Dạ, bạn ơi LogiX đã hoàn 25.000đ cho đơn O-606 rồi nha."` — gọi khách bằng `'bạn'` + `'nha'`; bổ sung negative few-shot vào prompt rubric cho phép bắt lỗi đại từ thân mật dù có `'Dạ'`. |
| 3 | `H-029` (`tone_ok`) | PASS | FAIL | Người đúng | `"Dạ, vui lòng chờ. Hệ thống đang xử lý, không cần nhắn thêm."` — giọng ra lệnh (`không cần nhắn thêm`) đánh lừa judge vì có `'Dạ, vui lòng'`; sửa rubric đánh giá toàn câu thay vì chỉ từ khóa mở đầu. |
| 4 | `H-042` (`tone_ok`) | FAIL | PASS | Người đúng | `"Dạ, đơn O-808 đã hoàn 120.000đ. Tiền về trong 3–5 ngày ạ."` — câu ngắn gọn, lịch sự, đủ thông tin nhưng judge phạt nhầm vì thiếu lời xin lỗi; sửa rubric: không yêu cầu xin lỗi khi hoàn tiền thành công. |
| 5 | `H-051` (`tone_ok`) | FAIL | PASS | Người đúng | `"Dạ, LogiX đã refund 90.000đ cho đơn O-202 ạ."` — dùng thuật ngữ `'refund'` được CS LogiX chấp nhận; sửa rubric liệt kê `'refund'` là thuật ngữ miền hợp lệ, không phạt lỗi tiếng Anh. |
| 6 | `H-063` (`tone_ok`) | PASS | FAIL | Người đúng | `"Dạ, LogiX đã hoàn 20.000đ và sẽ hoàn thêm cho anh/chị ạ."` — hứa `'sẽ hoàn thêm'` ngoài kết quả hệ thống; thêm quy tắc cấm cam kết/hứa hẹn ngoài ledger vào rubric. |
| 7 | `H-081` (`tone_ok`) | FAIL | PASS | Judge đúng | `"Dạ, đơn O-107 chưa đủ điều kiện hoàn theo chính sách hiện hành ạ."` — nhãn người đọc nhầm ticket trong lúc gán; cần sửa nhãn gốc ở `H-081` (và rà soát lại độ đồng thuận gán nhãn người). |
| 8 | `HL-015`, `HL-016` (`helpful`) | PASS | FAIL | Người đúng | `"Dạ, LogiX đã hoàn 55.000đ..."` (thực tế ledger ghi `40.000đ` / `35.000đ`): judge chỉ đọc văn bản reply lịch sự, không nhìn thấy SQLite ledger nên không thể phát hiện sai tiền (`FM-08`); loại judge cho tiêu chí này và thay bằng code grader `ReplyMatchesLedger`. |

## Kết luận
- **Tiêu chí bị loại và lý do (dẫn ma trận nhầm lẫn):** `helpful` (`tp=9, fp=0, fn=21, tn=70`) chỉ đạt **Recall = 0.300** và **κ = 0.375**, bỏ sót tới **21/30 ca lỗi thực tế (70% False Negative)** — chủ yếu là các câu trả lời xin lỗi rất khéo nhưng báo sai số tiền so với ledger (18 ca `sai tiền`) và 3 ca sai xưng hô (`Ok bạn...`). Do judge chỉ đánh giá trên text bề mặt mà không truy cập được `refund_ledger`, tỉ lệ lỗi quan sát bị kéo xuống còn `0.09` trong khi tỉ lệ lỗi thực (hiệu chỉnh Rogan-Gladen) là `0.30`. Nếu dùng `helpful` làm cổng CI, các lỗi sai tiền (FM-08) sẽ lọt qua gate một cách có hệ thống; tiền và approval bắt buộc phải chấm bằng **code grader** đọc trực tiếp ledger (`RefundAmountCorrect`, `ReplyMatchesLedger`, `ApprovalBypass`).
- **Tiêu chí được giữ (`tone_ok`):** Đạt mọi ngưỡng sàn (`tp=24, fp=4, fn=6, tn=66`, `κ=0.757 ≥ 0.6`, `P=0.857 ≥ 0.8`, `R=0.800 ≥ 0.7`, observed `0.28 → corrected 0.30`), đủ tin cậy để theo dõi sắc thái/xưng hô sau khi cập nhật rubric (xử lý `H-008`, `H-017`, `H-029`, `H-042`, `H-051`, `H-063`, `H-070`, `H-088`, `H-094`) và sửa nhãn nhiễu ở `H-081`.
- **Rủi ro còn lại:** Judge chỉ được kiểm trên dữ liệu replay đã công khai (`100` mẫu/CSV); cần thu thập tập nhãn người mới độc lập (held-out) sau khi sửa rubric để hiệu chuẩn lại trước khi đưa `tone_ok` vào cổng chặn chính thức.
