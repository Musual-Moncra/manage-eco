# Manage Eco (`eco`) — Quản lý Chi tiêu, Dòng tiền & Kế hoạch Tài chính trên Terminal

> **Nhanh · Nhẹ · Chuẩn VND · Có TUI tương tác · Thân thiện với AI Agent (`--json`)**

**Manage Eco** là ứng dụng dòng lệnh (CLI & TUI) bằng Python giúp bạn ghi chép thu chi hàng ngày, kiểm soát ngân sách theo danh mục, lên lịch các khoản thu/chi định kỳ trong tương lai và cảnh báo sớm nguy cơ âm tiền.

### Tính năng nổi bật

- **Nhập liệu tự nhiên chuẩn Việt Nam**: hỗ trợ `200k`, `1.5tr`, `1.5m`, `1.250.000`, ngày `hom nay`, `06/11/2026`, `+7`.
- **Quản lý dự định & định kỳ**: theo dõi các khoản thu/chi một lần (`once`), hàng tuần (`weekly`), hàng tháng (`monthly`) và tự động chuyển kỳ khi hoàn tất.
- **Dự báo dòng tiền & cảnh báo âm quỹ**: mô phỏng số dư 30–90 ngày tới, chỉ rõ ngày chạm đáy hoặc âm tiền.
- **Giao diện TUI tương tác (`eco ui`)**: điều khiển hoàn toàn bằng phím tắt, chuyển tab tức thì.
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

## Giao diện TUI (`eco ui`)

Khởi chạy bảng điều khiển tương tác toàn màn hình trên terminal:

```bash
eco ui
```

### Phím tắt trong TUI

| Phím | Chức năng |
| :--- | :--- |
| `1` – `5` | Chuyển nhanh giữa 5 tab: **Tổng quan**, **Giao dịch**, **Dự định**, **Ngân sách**, **Dự báo** |
| `j` / `k` | Di chuyển lên / xuống trong danh sách |
| `a` | Thêm nhanh khoản chi tiêu (`expense`) |
| `i` | Thêm nhanh khoản thu nhập (`income`) |
| `p` | Thêm nhanh dự định thu/chi tương lai (`plan`) |
| `d` | Đánh dấu dự định đang chọn là hoàn thành (`plan done`) |
| `q` | Thoát giao diện TUI |

---

## Hướng dẫn sử dụng các lệnh CLI (`eco`)

### Định dạng tiền tệ & ngày tháng hỗ trợ

- **Số tiền**: `1250000`, `1.250.000`, `1,250,000`, `200k` (200.000 ₫), `1.5tr` hoặc `1.5m` (1.500.000 ₫).
- **Ngày tháng**: ISO `2026-11-06`, `06/11/2026`, `today` / `hom nay`, hoặc `+7` (7 ngày kể từ hôm nay).

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

### 4. Quản lý kế hoạch thu/chi tương lai (`eco plan`)

```bash
# Thêm dự định chi tiêu định kỳ hàng tháng
eco plan add "Tiền nhà" 6tr nha --due 2026-12-01 --every monthly

# Thêm dự định thu nhập (--income)
eco plan add "Thưởng dự án" 10tr thuong --due +30 --income

# Xem danh sách dự định đang chờ (pending) hoặc tất cả (--all)
eco plan list
eco plan list --all

# Đánh dấu dự định đã thực hiện (ghi giao dịch & tự động nhảy kỳ nếu lặp lại)
eco plan done 1 -d today

# Huỷ dự định
eco plan cancel 2
```

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
