# Manage Eco (`eco`) — Quản lý Chi tiêu, Dòng tiền & Kế hoạch Tài chính trên Terminal

> **Nhanh · Nhẹ · Chuẩn VND · Giao diện bấm chuột · Thân thiện với AI Agent (`--json`)**

**Manage Eco** là ứng dụng terminal (Python) để ghi chép thu chi, kiểm soát ngân sách theo danh mục, lên lịch các khoản thu/chi định kỳ và xem biểu đồ số dư — **mọi thao tác đều làm được bằng giao diện, không cần gõ lệnh**.

### Tính năng nổi bật

- **Chỉ thao tác giao diện**: thêm/sửa/xoá giao dịch, dòng tiền, ngân sách; đổi tháng; xem biểu đồ; đổi âm thanh/icon — tất cả bằng chuột hoặc phím tắt.
- **Nhập liệu tự nhiên**: `200k`, `1.5tr`, `1.250.000`, biểu thức `50k+20k`; ngày `mai`, `15/11`, `thứ 6`, `cuối tháng`, chip ngày và lịch tháng bấm được.
- **Dòng tiền định kỳ**: một lần, hàng ngày, hàng tuần, hàng tháng (ngày cố định, kẹp cuối tháng, không trôi).
- **Biểu đồ kiểu chứng khoán**: line/nến, xanh khi tăng đỏ khi giảm, dự báo tương lai, rê/click xem số dư từng ngày.
- **Dễ thương & nhẹ**: theme pastel, toast + sparkle, hiệu ứng "ping" khi bấm; chờ input hoàn toàn khi rảnh (0% CPU).
- **Chế độ AI Agent**: `--json` / `ECO_JSON=1` trả một JSON object, không nạp `rich`; dùng được qua CLI hoặc `manage_eco.api`.

---

## Cài đặt

Yêu cầu **Python 3.9+** (chỉ cần thư viện chuẩn + `rich`).

```bash
./scripts/install.sh   # tạo lệnh `eco` trong /usr/local/bin
# hoặc: pip install -e .
eco                    # mở giao diện (hoặc `eco ui`)
```

---

## Hướng dẫn dùng giao diện

Gõ `eco` để mở. Mọi thứ đều bấm được; phím tắt ghi sẵn trên từng nút.

**5 tab**: `Tổng quan` · `Giao dịch` · `Dòng tiền` · `Ngân sách` · `Biểu đồ` — bấm để chuyển (phím `1`–`5`).

### Tổng quan

- Thẻ số dư, thu/chi tháng này, top 5 danh mục chi (thanh bar), cảnh báo dòng tiền quá hạn / nguy cơ âm tiền.
- Thẻ **Mục tiêu**: bấm `✎` → nhập số tiền đích + chọn ngày bằng chip/lịch → xem mỗi tháng cần để dành bao nhiêu.
- Sparkline số dư 30 ngày: bấm vào để mở tab **Biểu đồ**.

### Giao dịch (tab 2)

- **Thêm**: bấm `+ Chi` (phím `a`) hoặc `+ Thu` (phím `i`). Nhập số tiền (bấm chip `50k`…`1tr` hoặc gõ biểu thức), chọn/gõ danh mục, ghi chú, rồi chọn ngày:
  - chip nhanh `[Hôm qua] [Hôm nay] [Mai] [Cuối tháng] [Đầu tháng sau]`;
  - hoặc bấm lịch tháng (‹ › đổi tháng, bấm ngày);
  - hoặc gõ `15/11`, `thứ 6`, `+7`…
  - Dòng xem trước hiện `= 70.000 ₫` và `→ Thứ 6, 13/11/2026`. Bấm `Lưu`.
- **Sửa**: chọn dòng → `✎ Sửa` (phím `e`) → đổi số tiền/danh mục/ghi chú/ngày/loại → `Lưu`. Chỉ trường bạn đổi mới thay đổi.
- **Xoá**: chọn dòng → `✕ Xoá` → xác nhận.
- **Lọc**: `‹ ›` đổi tháng, chip `[Tất cả]`, chip danh mục.

### Dòng tiền (tab 3)

- **Thêm**: bấm `+ Dòng tiền` (phím `p`): tên, số tiền, danh mục, chọn lặp `[Một lần] [Hàng ngày] [Hàng tuần] [Hàng tháng]`.
  - Chọn `Hàng tháng` sẽ hiện ô **Ngày trả hằng tháng** (chip 1…31, kẹp cuối tháng, không trôi: 31 → 28/30 → 31); có thể bỏ trống ngày bắt đầu để app tự tính.
  - Chọn ngày bắt đầu bằng chip/lịch như form giao dịch; chọn `Chi`/`Thu`; bấm `Lưu`.
- **Sửa**: chọn dòng → `✎ Sửa` (phím `e`).
- **Đánh dấu đã trả**: chọn dòng → `✓ Xong` (phím `d`) — ghi giao dịch và tự nhảy kỳ tiếp theo.
- **Huỷ**: chọn dòng → `⊘ Huỷ` → xác nhận.
- **Lọc**: `[Đang chờ] [Tất cả]`.

### Ngân sách (tab 4)

- **Thêm**: bấm `[+ Ngân sách]` → chọn/gõ danh mục + hạn mức (chip hoặc biểu thức) → `Lưu`.
- **Sửa**: chọn dòng → `✎ Sửa` → đổi hạn mức → `Lưu`.
- **Xoá**: chọn dòng → `✕ Xoá` → xác nhận.
- **Đổi tháng**: `‹ Tháng 11/2026 ›`. Thanh bar chuyển vàng khi ≥80%, đỏ khi ≥100%.

### Biểu đồ (tab 5)

- Chọn `[Line]` hoặc `[Nến]`; khoảng thời gian `[1T] [3T] [6T] [1N] [Tất cả]`; dự báo `[+0] [+30] [+90]`.
- Chế độ Nến có thêm `[Ngày] [Tuần] [Tháng]`.
- Di chuột/bấm vào đồ thị hoặc dùng `←` `→` để xem tooltip: `Thứ 6, 06/11 · 23.715.000 ₫ · +25tr / -1,3tr`.
- Đường số dư tô xanh khi tăng, đỏ khi giảm; vạch "Hôm nay" chia quá khứ và dự báo; trục giá và trục ngày tự co theo bề rộng.

### Cài đặt (nút `⚙`)

- **Âm thanh**: bật/tắt bằng chip trong popover, hoặc nút `🔊/🔇` / phím `m`. Tiếng phát khi lưu, `✓ Xong`, xoá, lỗi, chuyển tab và cảnh báo.
- **Icon**: `symbol` (mặc định, glyph đơn ô an toàn cho terminal monospace), `emoji`, hoặc `off`.
- Tắt tạm cho một lần chạy: `ECO_SOUND=0`, `ECO_ICONS=off`, `ECO_ASCII=1`.

### Phím tắt

| Phím | Việc | Phím | Việc |
| :--- | :--- | :--- | :--- |
| `1`–`5` | chuyển tab | `a` / `i` | thêm chi / thu |
| `p` | thêm dòng tiền | `e` | sửa mục đang chọn |
| `d` | đánh dấu xong | `x` | xoá (có xác nhận) |
| `m` | bật/tắt âm thanh | `←` `→` | di chuyển cursor biểu đồ |
| `↑` `↓` | chọn dòng | `Enter` | lưu form |
| `Esc` | huỷ / đóng | `q` | thoát |

---

## Giao diện & hiệu năng

- **Co giãn**: dưới 60 cột bố cục gọn; 60–119 cột một cột; từ 120 cột Tổng quan hai cột và danh sách thêm Ghi chú/Lặp; từ 160 cột thêm sparkline. Không vỡ layout xuống 40×12.
- **Animation & VFX**: toast pastel + sparkle khi lưu, "Đã thanh toán…" khi xong, ripple "ping" tại điểm bấm, gạch chân tab trượt, glow dòng mới chọn. Khi rảnh app chờ input hoàn toàn (0% CPU, không redraw).
- **RAM**: `< 45 MB` cho TUI, `< 25 MB` cho `--json dash`; chỉ phụ thuộc `rich`.

---

## Dành cho AI agent / script

Agent nên dùng `--json` (hoặc `ECO_JSON=1`) và đọc `AGENTS.md` để có đầy đủ schema. Mọi lệnh CLI vẫn giữ nguyên cho automation.

```bash
python3 -m manage_eco --json --db /tmp/eco.db --today 2026-11-06 dash
```

- Thành công: `{"ok": true, "command": "<cmd>", "data": {...}}`, exit `0`.
- Lỗi: `{"ok": false, "error": "<msg>", "code": "not_found"|"invalid"}`, exit `1` / `2`.
- Cờ: `--json`, `--db PATH`, `--today YYYY-MM-DD`; biến: `ECO_JSON`, `ECO_DB`, `ECO_SOUND`, `ECO_ICONS`, `ECO_ASCII`.

| Nhóm | Lệnh |
| :--- | :--- |
| Giao dịch | `income`, `expense`, `list`, `edit`, `rm`, `summary`, `categories` |
| Dòng tiền | `plan add / list / done / cancel / edit` |
| Ngân sách | `budget set / status / delete` |
| Phân tích | `forecast`, `history`, `goal`, `dash` |
| Cài đặt | `sound on/off`, `icons symbol/emoji/off` |

```bash
eco --json expense 150k "an uong" -n "Phở" -d today
eco --json edit 1 --amount 200k
eco --json plan add "Tiền nhà" 6tr nha --every monthly --day 5
eco --json history --days 30 --ahead 30
```

Python API: `manage_eco.api.execute(cmd, params, store, today)` trả đúng object `data` (raise `LookupError` / `ValueError`).

---

## Kiểm thử

```bash
python3 -m unittest discover -s tests -v
bash scripts/memcheck.sh    # RSS của `--json dash` < 25 MB
bash scripts/idlecheck.sh   # TUI rảnh: ~0% CPU, RSS < 45 MB
```
