# ai-ops-custom-message

Web form (Vercel) để soạn và gửi tin Slack tùy chỉnh qua bot **AI Ops**: gửi tới nhiều channel, user group, danh sách người nhận (DM), gửi ngay hoặc đặt lịch (một lần hoặc lặp lại). Làm theo kiểu AI-Engineering-Daily: form có đăng nhập, API serverless, không có database, **Slack là nguồn dữ liệu duy nhất** cho tin đã đặt lịch.

Chỉ hai tài khoản được dùng (anh Trí và chị Quyên), cấu hình bằng `AUTH_USERS`.

## Chức năng
- Đăng nhập (mật khẩu băm PBKDF2-SHA256, phiên 8 giờ trong cookie HttpOnly, Secure, SameSite=Strict, kèm header chống CSRF).
- Soạn tin, chọn đích, **Xem trước**, rồi **Xác nhận**. Không có đường gửi bỏ qua xem trước ở giao diện.
- Đích: tối đa 10 channel; mention user group trong channel đã chọn; DM theo danh sách người nhận (tối đa 50 người, tự bỏ trùng). `@channel` / `@here` tắt mặc định.
- Thời điểm: gửi ngay (`chat.postMessage`) hoặc đặt lịch giờ Việt Nam (`chat.scheduleMessage`).
- Lịch lặp (hằng ngày, thứ 2 đến thứ 6, hằng tuần theo thứ): Slack không có lịch lặp, nên form tạo ra **từng tin đặt lịch riêng** cho mỗi lần chạy (tối đa 60 lần, trong 119 ngày). Hết hạn thì tạo lại.
- Danh sách tin đã đặt lịch lấy từ Slack, huỷ từng tin. Chưa có sửa tin: huỷ rồi tạo lại.
- Giới hạn: nội dung 3500 ký tự, tối đa 120 tin mỗi lần bấm (số đích × số lần chạy).

## Biến môi trường (Vercel)
| Biến | Bắt buộc | Ý nghĩa |
|---|---|---|
| `SLACK_BOT_TOKEN` | có | Bot token của app AI Ops (`xoxb-...`) |
| `AUTH_USERS` | có | JSON `{"tri":"<hash>","quyen":"<hash>"}`, hash tạo bằng `tools/hash_password.py` |
| `AUTH_SECRET` | có | Chuỗi ngẫu nhiên để ký cookie phiên (`tools/hash_password.py` in sẵn một chuỗi) |
| `RECIPIENT_LISTS` | không | JSON `{"leader":["U...","U..."]}`, danh sách người nhận để DM |
| `SLACK_ALLOWED_CHANNELS` | không | Danh sách channel ID được phép, cách nhau dấu phẩy. Bỏ trống: mọi channel bot nhìn thấy |

Thiếu `AUTH_USERS` hoặc `AUTH_SECRET` thì mọi endpoint trả 503 (không mở công khai).

## Cấu hình Slack (app AI Ops)
Scope hiện có đã đủ để gửi và DM (`chat:write`, `chat:write.public`, `im:write`). Cần thêm:
- `channels:read`, `groups:read`: để hiện danh sách channel.
- `usergroups:read`: để chọn user group (thiếu thì ô này tự ẩn).
Sau khi thêm scope, bấm **Reinstall to DSS** (trang OAuth đang cảnh báo đã đổi scope mà chưa reinstall). Không cần Shortcut hay Socket Mode cho chức năng này. Channel riêng muốn gửi vào phải mời bot AI Ops trước.

## Triển khai
1. Tạo project Vercel từ repo này (không cần build, thư mục `public/` là giao diện, `api/` là Python serverless).
2. Tạo mật khẩu: `python tools/hash_password.py` (mỗi người một lần), dán hash vào `AUTH_USERS`.
3. Đặt các biến môi trường ở bảng trên, deploy.
4. Thêm rate-limit cho `/api/login` trong Vercel Firewall (Vercel không giữ bộ đếm dùng chung giữa các instance).

Test: `pip install -r requirements-dev.txt && pytest -q`

## Chưa kiểm chứng
- Test tự động phủ logic (kiểm tra dữ liệu, lịch, gửi nhiều đích với Slack giả, đăng nhập, phiên) và đã gọi thử các endpoint cục bộ. **Chưa deploy lên Vercel, chưa gọi Slack thật.**
- Cần xác nhận khi chạy thật: Vercel nhận lớp `handler` kế thừa `BaseHTTPRequestHandler`; `maxDuration: 60` được gói Vercel đang dùng cho phép; `chat.scheduledMessages.list` chạy với scope hiện có; scheduleMessage vào DM channel hoạt động.
- Thử trên channel test trước khi dùng cho channel thật.

## Chính sách
Chính sách AI của công ty cấm AI gửi tin Slack vào kênh khách hàng và kênh nội bộ. Ở đây người soạn xem trước và xác nhận từng tin; chị Quyên nên xác nhận phù hợp chính sách trước khi dùng rộng.
