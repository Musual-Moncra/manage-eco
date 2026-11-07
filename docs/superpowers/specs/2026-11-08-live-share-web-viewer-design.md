# Thiết Kế Chi Tiết: Tính Năng Chia Sẻ Trực Tiếp Qua Web (Live Share Web Viewer)

**Ngày lập**: 08-11-2026  
**Trạng thái**: Chờ duyệt (Pending Review)  
**Tác giả**: Antigravity & User  

---

## 1. Bối Cảnh & Mục Tiêu

### 1.1. Bối cảnh
Người dùng sử dụng ứng dụng terminal **Manage Eco** để ghi chép chi tiêu, quản lý các hũ tiết kiệm, theo dõi ngân sách và dòng tiền cá nhân. Người dùng muốn bạn gái có thể cùng quan sát và nắm bắt thông tin tài chính theo thời gian thực từ thiết bị di động của cô ấy (thường qua mạng 4G/Internet từ xa).

### 1.2. Mục tiêu cốt lõi
1. **Chia sẻ thông tin, không phải màn hình thao tác**: Bạn gái cần một giao diện web di động (Mobile Web Dashboard) trực quan, đẹp mắt và dễ đọc thông tin tài chính (thay vì nhìn màn hình dòng lệnh hay con trỏ terminal).
2. **Kiểm soát hiển thị theo từng Tab (Selective Tab Sharing)**: Người dùng có thể chọn chính xác tab nào được phép chia sẻ (ví dụ: chia sẻ *Hũ tiết kiệm*, *Ngân sách*, *Tổng quan*, nhưng ẩn *Tài khoản* ngân hàng hoặc *Giao dịch* riêng tư).
3. **Đồng bộ thời gian thực (Real-time Sync)**: Khi người dùng ghi chép chi tiêu hoặc cập nhật số liệu trên máy tính, trang web của bạn gái tự động nhảy số tức thì qua Server-Sent Events (SSE) mà không cần tải lại trang.
4. **Chế độ chỉ xem (View-only) & Bảo mật**: An toàn tuyệt đối, không có khả năng sửa/xoá dữ liệu từ web; bảo vệ bằng mã PIN ngẫu nhiên; link tự huỷ ngay khi thoát app.
5. **Truy cập dễ dàng qua 4G**: Hỗ trợ kết nối từ xa qua Cloudflare Quick Tunnel (`trycloudflare.com`) miễn phí, có HTTPS, kèm mã QR hiển thị ngay trong terminal để quét mở trên điện thoại.

---

## 2. Trải Nghiệm Người Dùng (User Experience & Workflows)

### 2.1. Tab 8 trên Terminal TUI: `Chia sẻ` (Phím tắt `8`)
Hệ thống tab của Manage Eco được mở rộng thêm tab thứ 8:
```
[1 Tổng quan] [2 Tài khoản] [3 Giao dịch] [4 Dòng tiền] [5 Ngân sách] [6 Hũ tiết kiệm] [7 Biểu đồ] [8 Chia sẻ]
```

Giao diện tab **Chia sẻ** bao gồm:
1. **Thanh trạng thái & Công tắc kết nối**:
   * Nút bấm toggle: `[● Đang chia sẻ]` (màu xanh mint) hoặc `[○ Đã tắt]` (màu xám).
   * Phím tắt `s` để bật/tắt nhanh.
   * Số thiết bị đang kết nối: `● 1 thiết bị đang xem (Safari iOS)`.
2. **Thông tin kết nối & Mã QR**:
   * Khi bật chia sẻ:
     * Hiển thị URL công khai: `https://<random>.trycloudflare.com?pin=2468` (kèm URL nội bộ `http://192.168.x.x:8080?pin=2468`).
     * Phím tắt `c` hoặc click nút `[Sao chép link]` để copy link vào clipboard.
     * Vẽ **Mã QR trực quan** bằng khối Unicode 2 ô ngay trên màn hình terminal: Người dùng chỉ cần giơ điện thoại bạn gái lên quét là vào xem được ngay.
3. **Danh sách phân quyền chia sẻ từng Tab**:
   * Hiển thị danh sách các chip/checkbox tương ứng với 7 tab nội dung:
     * `[✓] 1. Tổng quan`
     * `[ ] 2. Tài khoản` *(tắt nếu không muốn hiện chi tiết từng ví/ngân hàng)*
     * `[ ] 3. Giao dịch` *(tắt nếu không muốn lộ lịch sử giao dịch lẻ)*
     * `[✓] 4. Dòng tiền` *(chia sẻ lịch các khoản định kỳ sắp tới)*
     * `[✓] 5. Ngân sách` *(chia sẻ hạn mức ăn uống, mua sắm)*
     * `[✓] 6. Hũ tiết kiệm` *(chia sẻ tiến độ mục tiêu chung)*
     * `[✓] 7. Biểu đồ` *(chia sẻ xu hướng số dư)*
   * Thao tác: Bấm phím số hoặc click chuột vào chip để bật/tắt quyền xem cho tab tương ứng.
4. **Chế độ hiển thị (Sync Mode)**:
   * `[Tự do duyệt]` (Mặc định): Bạn gái tự bấm chuyển giữa các tab đã được cấp quyền trên điện thoại.
   * `[Đi cùng tôi (Follow Me)]`: Web của bạn gái tự động nhảy tab theo đúng tab người dùng đang chọn trên terminal. Nếu người dùng chuyển sang tab chưa cấp quyền, web hiện thông báo nhẹ nhàng: *"Người yêu bạn đang ở khu vực riêng tư ♡"*.

---

### 2.2. Giao diện Web trên điện thoại của bạn gái (Mobile Web Viewer)

#### Giao diện & Phong cách
* **Chủ đề màu sắc**: Pastel chuẩn Manage Eco (Nền tối `#1e1b2e`, viền `#3b3363`, thẻ mềm mại `#262338`, điểm nhấn Lavender `#c4b5fd`, Hồng `#f9a8d4`, Mint `#86efac`, Coral `#fca5a5`).
* **Header**:
  * Tên: `🌿 Manage Eco • Cùng quan sát`
  * Trạng thái kết nối: Huy hiệu `● Trực tiếp` nhấp nháy xanh lá.
  * Thanh tab trượt ngang (Horizontal scroll tabs): **Chỉ chứa các tab đã được người dùng tick `[✓]` trên terminal**.
* **Nội dung từng tab khi được xem**:
  1. **Tab Tổng quan**:
     * Thẻ Tài sản tổng: Tổng số dư & Tiền tự do khả dụng.
     * Thẻ Tháng này: Thu (xanh), Chi (đỏ), Tiết kiệm ròng.
     * Top danh mục chi tiêu lớn nhất kèm thanh tỷ lệ.
  2. **Tab Ngân sách**:
     * Thẻ từng danh mục: Đã tiêu / Hạn mức, % đã dùng.
     * Tự đổi màu thông minh: Vàng khi ≥80%, Đỏ khi ≥100%.
  3. **Tab Hũ tiết kiệm**:
     * Các hũ mục tiêu (Du lịch, Mua sắm, Quỹ chung...).
     * Thanh tiến độ %, số tiền đã gom, số tiền cần tích luỹ mỗi tháng, đếm ngược ngày.
  4. **Tab Dòng tiền**:
     * Lịch các khoản sắp tới hạn thanh toán trong 30 ngày (tiền nhà, tiền mạng...).
  5. **Tab Giao dịch** *(nếu được bật)*:
     * Lịch sử giao dịch theo ngày, đánh dấu màu Thu/Chi.
  6. **Tab Tài khoản** *(nếu được bật)*:
     * Danh sách ví / tài khoản và số dư tương ứng.
  7. **Tab Biểu đồ** *(nếu được bật)*:
     * Biểu đồ đường cong số dư SVG mượt mà, chạm ngón tay để xem chi tiết từng ngày.
* **Đặc tính**:
  * Hoàn toàn chỉ xem (Read-only), không có bất kỳ nút thêm/sửa/xoá nào.
  * Dữ liệu tự động cập nhật mượt mà (SSE), không giật lắc, không cần refresh trang.

---

## 3. Kiến Trúc Kỹ Thuật (Architecture & Component Design)

```
┌────────────────────────────────────────────────────────────────────────┐
│                        MÁY TÍNH CỦA BẠN (LOCAL)                        │
│                                                                        │
│   ┌─────────────────────┐             ┌────────────────────────────┐   │
│   │   Manage Eco TUI    │             │   SQLite Database (Store)  │   │
│   │   (manage_eco/tui)  │             │   (manage_eco/db)          │   │
│   └──────────┬──────────┘             └─────────────┬──────────────┘   │
│              │ Thao tác dữ liệu                      │                 │
│              ▼                                       ▼                 │
│   ┌────────────────────────────────────────────────────────────┐       │
│   │                      Event Bus / Notify                    │       │
│   └──────────────────────────┬─────────────────────────────────┘       │
│                              │ Phát tín hiệu thay đổi                  │
│                              ▼                                         │
│   ┌────────────────────────────────────────────────────────────┐       │
│   │   Background Web Server (manage_eco/web.py)                │       │
│   │   - Python standard http.server in daemon thread           │       │
│   │   - GET /              -> Single-page HTML/CSS/JS (embed)  │       │
│   │   - GET /api/data      -> JSON snapshot of allowed tabs    │       │
│   │   - GET /api/stream    -> Server-Sent Events (SSE) stream  │       │
│   │   - PIN validation & Tab Whitelist Enforcement             │       │
│   └──────────┬─────────────────────────────────────────────────┘       │
│              │ Port 8080                                               │
│              ▼                                                         │
│   ┌────────────────────────────────────────────────────────────┐       │
│   │   Cloudflare Quick Tunnel (cloudflared sub-process)        │       │
│   │   Tạo URL HTTPS ngẫu nhiên: https://<hash>.trycloudflare...│       │
│   └──────────────────────────┬─────────────────────────────────┘       │
└──────────────────────────────┼─────────────────────────────────────────┘
                               │ HTTPS (Internet / 4G)
                               ▼
┌────────────────────────────────────────────────────────────────────────┐
│                       ĐIỆN THOẠI BẠN GÁI (REMOTE)                      │
│                                                                        │
│   Trình duyệt di động (Safari / Chrome Mobile)                         │
│   - Kết nối SSE /api/stream?pin=XXXX                                   │
│   - Nhận payload JSON chỉ chứa dữ liệu các tab được cấp quyền          │
│   - Cập nhật DOM tự động mượt mà, không giật màn hình                  │
└────────────────────────────────────────────────────────────────────────┘
```

### 3.1. Module Web Server (`manage_eco/web.py`)
* Sử dụng `http.server` và `threading` có sẵn trong thư viện chuẩn Python (zero external dependencies).
* Tài nguyên tiêu thụ: Thêm < 5MB RAM, chiếm 0% CPU khi không có request.
* **Cơ chế lọc quyền (Data Filtering Guard)**:
  * Server giữ danh sách các tab được phép chia sẻ (`allowed_tabs = {"overview", "budgets", "goals", ...}`).
  * Khi serialize dữ liệu gửi cho web, server **chỉ truy vấn và đóng gói đúng dữ liệu của các tab nằm trong danh sách trắng**. Dữ liệu của các tab không được tick tuyệt đối không bao giờ được gửi qua mạng.
* **Cơ chế xác thực (PIN Security)**:
  * Mỗi phiên bật chia sẻ sinh mã PIN ngẫu nhiên 4 chữ số.
  * Mọi request tới `/api/*` và trang chủ đều phải đi kèm đúng PIN qua query param hoặc cookie phiên.
  * Nhập sai PIN 5 lần sẽ bị khoá tạm thời.

### 3.2. Luồng đồng bộ thời gian thực qua Server-Sent Events (SSE)
* Endpoint `/api/stream?pin=...`:
  * Mở kết nối HTTP giữ liên tục với header `Content-Type: text/event-stream`.
  * Trình duyệt điện thoại sử dụng `new EventSource('/api/stream?pin=...')` có sẵn của JavaScript.
  * Khi có sự kiện (ví dụ: người dùng nhập khoản chi mới, đổi tab hoặc cập nhật danh sách chia sẻ), server gửi gói tin:
    ```
    event: update
    data: {"type": "data_changed", "tab": "overview", "payload": {...}}
    ```
  * Trình duyệt nhận sự kiện và cập nhật trực tiếp vào các thẻ DOM tương ứng.

### 3.3. Đường hầm từ xa (Cloudflare Quick Tunnel)
* Tích hợp điều khiển tiến trình ngầm `cloudflared tunnel --url http://127.0.0.1:8080`.
* Không cần tài khoản Cloudflare, không tốn phí, có sẵn chứng chỉ SSL HTTPS hợp lệ.
* Tự động bắt regex chuỗi `https://[a-zA-Z0-9-]+\.trycloudflare\.com` từ stdout của `cloudflared` để lấy đường link chia sẻ.
* Nếu máy tính chưa có `cloudflared`, app hiển thị hướng dẫn cài đặt 1 dòng `brew install cloudflared`, đồng thời vẫn cung cấp link IP mạng nội bộ (Wi-Fi) để dùng ngay.

### 3.4. Quản lý vòng đời (Lifecycle & Cleanup)
* Khi người dùng bấm tắt chia sẻ hoặc thoát app Manage Eco (`q` hoặc `Ctrl+C`):
  * Web server ngầm được đóng (`server.shutdown()`).
  * Tiến trình `cloudflared` được gửi tín hiệu `SIGTERM` và huỷ hoàn toàn.
  * Đường hầm và link web lập tức vô hiệu hoá, bảo vệ tính riêng tư tuyệt đối.

---

## 4. Kế Hoạch Kiểm Thử (Testing Strategy)

1. **Unit Tests (`tests/test_web.py`)**:
   * Kiểm thử khởi tạo và tắt server độc lập trong tiến trình test.
   * Kiểm thử bảo mật PIN: Từ chối request không có PIN hoặc sai PIN.
   * Kiểm thử bộ lọc tab: Đảm bảo khi chỉ cho phép tab `Ngân sách` thì response API không chứa dữ liệu `Tài khoản` hay `Giao dịch`.
   * Kiểm thử phát tín hiệu SSE khi có thay đổi dữ liệu trong `Store`.
2. **TUI Integration Tests (`tests/test_tui_share.py`)**:
   * Kiểm thử chuyển sang tab 8 (`Chia sẻ`), vẽ giao diện tab 8 và hiển thị mã QR.
   * Kiểm thử bấm toggle các chip tab chia sẻ (bật/tắt quyền từng tab).
3. **Memory & Performance Regression**:
   * Chạy lệnh kiểm tra bộ nhớ `scripts/memcheck.sh` để đảm bảo app khi chạy chế độ chia sẻ vẫn duy trì mức tiêu thụ RAM cực thấp (<25 MB RSS).

---

## 5. Tự Rà Soát (Self-Review Checklist)

* [x] **Không có nội dung TBD / Chưa rõ ràng**: Toàn bộ luồng TUI, Web, SSE và Tunnel đều có đặc tả chi tiết.
* [x] **Nhất quán nội bộ**: Quyền hạn từng tab đồng bộ giữa TUI và Web API.
* [x] **Phạm vi tập trung**: Giải quyết chính xác bài toán chia sẻ thông tin tài chính cho bạn gái theo tab tuỳ chọn, không thêm các tính năng dư thừa.
* [x] **Bảo mật & An toàn dữ liệu**: Chế độ 100% read-only, có PIN xác thực, tự huỷ khi tắt app.