# Manage Eco (`eco`) — Quản lý Chi tiêu, Dòng tiền & Kế hoạch Tài chính trên Terminal

> **Nhanh · Nhẹ · Chuẩn VND · Có TUI tương tác · Thân thiện với AI Agent (`--json`)**

**Manage Eco** là ứng dụng dòng lệnh (CLI & TUI) bằng Python giúp bạn ghi chép thu chi hàng ngày, kiểm soát ngân sách theo danh mục, lên lịch các khoản thu/chi định kỳ trong tương lai và cảnh báo sớm nguy cơ âm tiền.

### Tính năng nổi bật

- **Nhập liệu tự nhiên chuẩn Việt Nam**: `200k`, `1.5tr`, `1.250.000`, biểu thức `50k+20k`; ngày `hom nay`, `mai`, `15/11`, `thứ 6`, `cuối tháng`, `+7`.
- **Quản lý Dòng tiền & định kỳ**: theo dõi các khoản thu/chi một lần (`once`), hàng ngày (`daily`), hàng tuần (`weekly`), hàng tháng (`monthly`) và tự động chuyển kỳ khi hoàn tất.
- **Dự báo dòng tiền & cảnh báo âm quỹ**: mô phỏng số dư 30–90 ngày tới, chỉ rõ ngày chạm đáy hoặc âm tiền.
- **Giao diện TUI tương tác (`eco ui`)**: bấm chuột hoặc phím tắt, chuyển tab tức thì, chọn ngày bằng chip/lịch tháng và xem trước ngay khi nhập.
- **Chế độ AI Agent (`--json` / `ECO_JSON=1`)**: đầu ra JSON một dòng chuẩn hóa, không nạp `rich`, tích hợp trực tiếp cho LLM/automation.
- **Siêu nhẹ & tiết kiệm RAM**: chỉ dùng thư viện chuẩn Python + `rich` (lazy import), tiêu thụ `< 25 MB` ở chế độ JSON và `< 45 MB` ở chế độ TUI.

---

## Cài đặt

Yêu cầu **Python 3.9+**.

```bash
./scripts/install.sh   # tạo lệnh `eco` trong /usr/local/bin → dùng được ở mọi terminal/shell
eco                    # mở ngay giao diện TUI
```

Hoặc dùng pip (pip ≥ 21.3): `pip install -e .`

Gõ `eco` không kèm lệnh con sẽ mở TUI; khi output không phải terminal (pipe, script) hoặc có `--json`, `eco` trả về `dash`.

---

## Cờ toàn cục (Global Flags) & Biến môi trường

Các cờ toàn cục có thể đặt trước bất kỳ lệnh con nào của `eco`:

| Cờ / Biến môi trường | Mô tả |
| :--- | :--- |
| `--json` | Xuất kết quả dạng một JSON object duy nhất ra `stdout` (không nạp `rich`). |
| `ECO_JSON=1` | Biến môi trường tương đương với `--json`. |
| `--db PATH` | Chỉ định đường dẫn file SQLite (mặc định lấy `$ECO_DB` hoặc `~/.manage_eco.db`). |
| `--today YYYY-MM-DD` | Giả lập ngày hiện tại (phục vụ kiểm thử và AI agent). |

---

## Giao diện TUI (`eco`)

Gõ `eco` (hoặc `eco ui`) để mở. **Mọi thao tác đều bấm chuột được** — không cần nhớ phím:

- **4 tab** ở dòng trên cùng: Tổng quan · Giao dịch · Dòng tiền · Ngân sách — nhấp để chuyển.
- **Nút hành động** ở dòng dưới cùng: `+ Chi` `+ Thu` `+ Dòng tiền`; khi chọn một dòng có thêm `✎ Sửa` / `✓ Xong` / `✕ Xoá`, và `Thoát`.
- **Form thêm**: nhấp số tiền gợi ý (`50k` … `1tr`) và danh mục hay dùng; ô ngày có chip nhanh `[Hôm qua][Hôm nay][Mai][Cuối tháng][Đầu tháng sau]`, lịch tháng bấm được (‹ › đổi tháng) và dòng xem trước `→ Thứ 6, 13/11/2026`; số tiền cũng hiện xem trước (`= 70.000 ₫`). Nhấp `Lưu`.
- Nhấp vào một dòng để chọn, lăn chuột để cuộn.

Phím tắt (luôn ghi sẵn trên từng nút): `1`–`4` tab · `a` thêm chi · `i` thêm thu · `p` thêm dòng tiền · `e` sửa · `d` xong · `x` xoá · `↑↓` chọn · `Enter` lưu · `Esc` huỷ · `q` thoát.

### Giao diện

- **Co giãn theo terminal**: dưới 60 cột dùng bố cục gọn (icon + nhãn ngắn, một cột); 60–119 cột một cột; từ 120 cột tab Tổng quan chia hai cột (Ngân sách | Sắp tới) và danh sách có thêm Ghi chú/Lặp; từ 160 cột thêm sparkline số dư 30 ngày. Không vỡ layout xuống 40×12.
- **Animation**: lưu khoản chi/thu/dòng tiền hiện toast pastel bo tròn + sparkle và số dư nhảy theo; `✓ Xong` hiện toast "Đã thanh toán…"; lỗi hiện toast lỗi. Khi rảnh TUI chờ input hoàn toàn (0% CPU, không redraw).
- **Âm thanh (SFX)**: nút `🔊/🔇` hoặc phím `m` bật/tắt và ghi nhớ lựa chọn. Tiếng phát khi lưu, `✓ Xong`, xoá, lỗi, chuyển tab, và cảnh báo (lưu xong làm dự báo âm tiền hoặc ngân sách ≥100%). Tắt tạm thời bằng `ECO_SOUND=0`.
- **Icon an toàn**: `eco icons symbol|emoji|off` — mặc định `symbol` (glyph đơn ô, hiển thị tốt trên mọi terminal monospace); `ECO_ICONS` ghi đè cho một lần chạy.
- **ASCII**: đặt `ECO_ASCII=1` (hoặc `TERM=linux`/`dumb`) để thay emoji/kaomoji bằng ký tự ASCII.

---

## Hướng dẫn sử dụng các lệnh CLI (`eco`)

### Định dạng tiền tệ & ngày tháng hỗ trợ

- **Số tiền**: `1250000`, `1.250.000`, `1,250,000`, `200k` (200.000 ₫), `1.5tr`/`1.5m` (1.500.000 ₫), hoặc biểu thức:

  | Nhập | Kết quả |
  | :--- | ---: |
  | `50k+20k` | 70.000 ₫ |
  | `3x150k` | 450.000 ₫ |
  | `1tr:4` | 250.000 ₫ |
  | `(2tr-500k)*2` | 3.000.000 ₫ |

  Toán tử `+ - x X × * : / ÷`, ngoặc, dấu cách và dấu trừ đơn; không dùng `eval`.

- **Ngày tháng** (không phân biệt hoa/thường, có/không dấu):

  | Nhập | Ý nghĩa |
  | :--- | :--- |
  | `2026-11-06` | ngày ISO |
  | `06/11/2026` | ngày/tháng/năm |
  | `today` / `hom nay` | hôm nay |
  | `hôm qua` / `qua` | hôm qua |
  | `mai` / `ngày mai` | ngày mai |
  | `mốt` / `ngày kia` | +2 ngày |
  | `-3` / `+7` | lùi/tiến N ngày |
  | `15` | ngày 15 tháng này (kẹp cuối tháng) |
  | `15/11` hoặc `15-11` | 15/11 năm nay |
  | `15/11/26` | 15/11/2026 |
  | `thứ 6` / `t6` | thứ 6 tới (không tính hôm nay) |
  | `chủ nhật` / `cn` | chủ nhật tới |
  | `tuần sau` | +7 ngày |
  | `tháng sau` | cùng ngày tháng sau (kẹp cuối tháng) |
  | `đầu tháng sau` | ngày 1 tháng sau |
  | `cuối tháng` | ngày cuối tháng này |

### 1. Ghi nhận khoản thu / khoản chi (`eco income` | `eco expense`)

```bash
# Ghi khoản thu
eco income 20tr luong -n "Lương tháng 11" -d today

# Ghi khoản chi
eco expense 150k "an uong" -n "Phở sáng" -d 06/11/2026
```

### 2. Liệt kê & xoá giao dịch (`eco list`, `eco rm`)

```bash
eco list                  # Giao dịch trong tháng hiện tại
eco list --month 2026-11  # Giao dịch theo tháng YYYY-MM
eco list --all            # Toàn bộ giao dịch
eco rm 1                  # Xoá giao dịch theo ID
```

### 3. Tổng kết thu/chi theo tháng (`eco summary`)

```bash
eco summary
eco summary --month 2026-11
```

### 4. Quản lý Dòng tiền (`eco plan`)

```bash
# Thêm dòng tiền chi định kỳ hàng tháng vào một ngày cố định (không cần --due)
eco plan add "Tiền nhà" 6tr nha --every monthly --day 5

# Hàng ngày, hoặc có ngày đến hạn cụ thể
eco plan add "Cà phê" 20k "an uong" --due +1 --every daily
eco plan add "Tiền nhà" 6tr nha --due 2026-12-01 --every monthly

# Thêm dòng tiền thu nhập (--income)
eco plan add "Thưởng dự án" 10tr thuong --due +30 --income

# Xem danh sách dòng tiền đang chờ (pending) hoặc tất cả (--all)
eco plan list
eco plan list --all

# Đánh dấu đã thực hiện (ghi giao dịch & tự động nhảy kỳ nếu lặp lại)
eco plan done 1 -d today

# Huỷ dòng tiền
eco plan cancel 2
```

`--day N` chỉ dùng với `--every monthly` (N = 1..31, kẹp cuối tháng, không trôi: 31 → 28/30 → 31); dùng với `daily`/`weekly` sẽ báo lỗi.

### 5. Ngân sách theo danh mục (`eco budget`)

```bash
eco budget set "an uong" 3tr
eco budget status
eco budget status --month 2026-11
```

### 6. Dự báo dòng tiền (`eco forecast`) & Mục tiêu tiết kiệm (`eco goal`)

```bash
# Dự báo số dư 90 ngày tới (mặc định) hoặc tuỳ chỉnh số ngày
eco forecast
eco forecast --days 60

# Tính số tiền cần tiết kiệm mỗi tháng để đạt mục tiêu trước hạn
eco goal 50tr --by 2027-06-01
```

### 7. Bảng tổng quan (`eco dash`)

```bash
eco dash
```

### 8. Bật/tắt âm thanh hiệu ứng (`eco sound`)

```bash
eco sound          # xem trạng thái
eco sound off      # tắt SFX
eco sound on       # bật lại
```

Với `--json`, kết quả là `{"ok": true, "command": "sound", "data": {"sound": true}}`.
Trong TUI, bấm nút `🔊/🔇` hoặc nhấn `m` để đổi và ghi nhớ; `ECO_SOUND=0` tắt tạm mà không đổi cài đặt.

### 9. Sửa giao dịch (`eco edit`)

```bash
eco edit 1 --amount 200k -n "Phở bò"
eco edit 1 -n ""              # xoá ghi chú
eco edit 1 --kind income      # đổi loại; số dư cập nhật
eco edit 1 --category "an uong" -d 06/11/2026
```

Chỉ các trường được nêu thay đổi. ID không tồn tại → exit 1; số tiền không hợp lệ → exit 2.
Trong TUI, chọn dòng rồi bấm `✎ Sửa` (phím `e`).

### 10. Sửa dòng tiền (`eco plan edit`)

```bash
eco plan edit 1 --amount 6tr --name "Tiền nhà mới"
eco plan edit 1 --every monthly --day 5   # cố định ngày 5, tự tính ngày đến hạn
eco plan edit 1 --every weekly            # đổi sang hàng tuần, xoá --day
```

Chỉ các trường được nêu thay đổi; `--day` chỉ dùng với `--every monthly` (lặp khác → exit 2).
Trong TUI, chọn dòng tiền rồi bấm `✎ Sửa` (phím `e`).

### 11. Kiểu icon (`eco icons`)

```bash
eco icons             # xem (mặc định symbol)
eco icons emoji       # bộ emoji đầy đủ
eco icons off         # ẩn icon
```

`symbol` dùng glyph đơn ô, an toàn khi emoji hiện thành ô vuông; `ECO_ICONS` ghi đè cho một lần chạy.
Với `--json`: `{"ok": true, "command": "icons", "data": {"icons": "symbol"}}`.

---

## Quy trình sử dụng hàng ngày (Sample Daily Workflow)

```bash
# 1. Đầu tháng: nhận lương, đặt ngân sách và lên lịch các khoản cố định
eco income 25tr luong -n "Lương tháng 11"
eco budget set "an uong" 4tr
eco budget set "di chuyen" 1tr
eco plan add "Tiền thuê nhà" 6tr nha --due +5 --every monthly

# 2. Hàng ngày: ghi nhanh các khoản chi phát sinh
eco expense 45k "an uong" -n "Cà phê & bánh mì"
eco expense 120k "di chuyen" -n "Đổ xăng"

# 3. Khi đến hạn thanh toán hoá đơn định kỳ: đánh dấu hoàn tất
eco plan done 1

# 4. Cuối ngày / cuối tuần: kiểm tra bảng tổng quan hoặc mở TUI
eco dash
eco ui
```

---

## Dùng cho AI Agent (`--json`)

Manage Eco được thiết kế sẵn cho AI Agent và công cụ tự động hóa thông qua cờ `--json` (hoặc biến môi trường `ECO_JSON=1`) cũng như API Python trực tiếp trong `manage_eco.api`. Xem tài liệu chi tiết về schema và quy ước tích hợp tại **[AGENTS.md](./AGENTS.md)**.

- Khi thành công (exit code `0`): `{"ok": true, "command": "<cmd>", "data": {...}}`
- Khi lỗi: `{"ok": false, "error": "<msg>", "code": "not_found"|"invalid"}` (exit code `1` nếu `not_found`, `2` nếu `invalid`)

### Ví dụ 1: Ghi khoản chi và lấy số dư mới qua `--json`

```bash
eco --db /tmp/demo.db --today 2026-11-06 --json expense 150k "an uong" -n "Ăn trưa"
```

Kết quả JSON:

```json
{"ok": true, "command": "expense", "data": {"transaction": {"id": 1, "date": "2026-11-06", "amount": 150000, "kind": "expense", "category": "an uong", "note": "Ăn trưa", "signed": -150000}, "balance": -150000}}
```

### Ví dụ 2: Truy vấn bảng tổng quan (`dash`) cho Agent bằng `ECO_JSON=1`

```bash
ECO_JSON=1 eco --db /tmp/demo.db --today 2026-11-06 dash
```

Kết quả JSON:

```json
{"ok": true, "command": "dash", "data": {"today": "2026-11-06", "balance": -150000, "month": {"month": "2026-11", "income": 0, "expense": 150000, "net": -150000, "by_category": [{"category": "an uong", "amount": 150000}]}, "overdue": [], "budgets": [], "upcoming": [], "lowest": null}}
```

---

## Hiệu năng & RAM

- **Phụ thuộc duy nhất**: chỉ sử dụng thư viện chuẩn Python (`sqlite3`, `argparse`, `datetime`, `json`, ...) và `rich`. Không cần cài đặt framework nặng.
- **Lazy Import**: khi chạy với `--json` hoặc `ECO_JSON=1`, `eco` chỉ nạp tầng dữ liệu (`db`, `api`, `fmt`) và **không import `rich`**, giúp khởi động tức thì và giảm tối đa bộ nhớ.
- **Ngân sách bộ nhớ (RAM Budgets)** (đo bằng `/usr/bin/time -l`):
  - `eco --json dash`: Max RSS **< 25 MB**
  - `eco ui` (TUI tương tác): Max RSS **< 45 MB**

---

## Chạy kiểm thử (Unit Tests)

```bash
python3 -m unittest discover -s tests -v
```
