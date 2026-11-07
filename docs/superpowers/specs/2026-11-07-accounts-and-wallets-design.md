# Đặc tả Thiết kế: Phân hệ Quản lý Tài khoản & Nguồn tiền (Accounts & Wallets)

- **Ngày tạo**: 2026-11-07
- **Trạng thái**: Đã thống nhất thiết kế với người dùng (Approved in chat)
- **Tài liệu tham chiếu**: `SPEC.md`, `AGENTS.md`

---

## 1. Mục tiêu & Bối cảnh

### 1.1. Bối cảnh
Hiện tại, `Manage Eco` ghi nhận các giao dịch thu chi vào một dòng tiền duy nhất trên toàn hệ thống (`balance = sum(income) - sum(expense)`). Người dùng không thể phân tách hay biết được tiền đang nằm ở đâu (ví dụ: trong ví tiền mặt, ví điện tử ZaloPay/Momo, hay tài khoản các ngân hàng Techcombank, Vietcombank...).

### 1.2. Mục tiêu
- Cung cấp khả năng phân chia và theo dõi chính xác vị trí tiền (tiền mặt, ví điện tử, ngân hàng...).
- Thêm một tab chuyên biệt **"Tài khoản"** trên giao diện TUI để quản lý danh sách tài khoản, số dư thực tế, tỷ lệ phân bổ tài sản và thực hiện chuyển tiền nội bộ.
- Cho phép chuyển tiền giữa các tài khoản mà **không làm sai lệch báo cáo thu/chi tháng** (không tính chuyển tiền nội bộ thành chi tiêu hay thu nhập).
- Giữ vững trải nghiệm nhập nhanh (frictionless quick entry): Mặc định các giao dịch Thu/Chi tự động gán vào **Tài khoản chính (mặc định)** nếu người dùng không chọn tài khoản khác.
- Tuân thủ hợp đồng `--json` cho Agent và giới hạn tài nguyên bộ nhớ (RAM RSS < 25MB cho JSON mode, < 45MB cho TUI).

---

## 2. Mô hình Dữ liệu (Data Models)

### 2.1. Lớp thực thể (`manage_eco/models.py`)

```python
@dataclass
class Account:
    """Tài khoản hoặc ví lưu trữ tiền (Tiền mặt, Ngân hàng, Ví điện tử...)."""
    name: str
    initial_balance: int = 0
    is_default: bool = False
    id: Optional[int] = None

@dataclass
class Transfer:
    """Giao dịch chuyển tiền nội bộ giữa hai tài khoản."""
    date: date
    amount: int
    from_account_id: int
    to_account_id: int
    note: str = ""
    id: Optional[int] = None
```

### 2.2. Cập nhật `Transaction`
```python
@dataclass
class Transaction:
    date: date
    amount: int
    kind: str  # INCOME | EXPENSE
    category: str = ""
    note: str = ""
    account_id: Optional[int] = None  # None nghĩa là thuộc tài khoản mặc định
    id: Optional[int] = None
```

---

## 3. Lưu trữ Cơ sở Dữ liệu & Migration (`manage_eco/db.py`)

### 3.1. SQLite Schema mới

```sql
CREATE TABLE IF NOT EXISTS accounts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT UNIQUE NOT NULL,
    initial_balance INTEGER NOT NULL DEFAULT 0 CHECK (initial_balance >= 0),
    is_default INTEGER NOT NULL DEFAULT 0 CHECK (is_default IN (0, 1))
);

CREATE TABLE IF NOT EXISTS transfers (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    date TEXT NOT NULL,
    amount INTEGER NOT NULL CHECK (amount > 0),
    from_account_id INTEGER NOT NULL REFERENCES accounts(id),
    to_account_id INTEGER NOT NULL REFERENCES accounts(id),
    note TEXT NOT NULL DEFAULT '',
    CHECK (from_account_id != to_account_id)
);
```

### 3.2. Migration tự động trong `Store.__init__`
1. Kiểm tra bảng `transactions`: nếu cột `account_id` chưa tồn tại, thực thi:
   `ALTER TABLE transactions ADD COLUMN account_id INTEGER REFERENCES accounts(id);`
2. Tạo các bảng `accounts` và `transfers` nếu chưa có (`CREATE TABLE IF NOT EXISTS`).

### 3.3. Các hàm Store trong `manage_eco/db.py`
- `add_account(account: Account) -> int`: Thêm tài khoản mới. Nếu là tài khoản duy nhất, tự động set `is_default = True`. Nếu `is_default = True`, bỏ cờ `is_default` ở các tài khoản khác.
- `list_accounts() -> List[Account]`: Lấy danh sách tất cả tài khoản.
- `get_account(account_id: int) -> Optional[Account]`: Lấy tài khoản theo ID.
- `get_account_by_name(name: str) -> Optional[Account]`: Tìm tài khoản theo tên (không phân biệt hoa thường).
- `get_default_account() -> Optional[Account]`: Lấy tài khoản mặc định.
- `update_account(account: Account) -> None`: Cập nhật thông tin tài khoản.
- `delete_account(account_id: int) -> bool`: Xóa tài khoản nếu không có giao dịch hoặc lệnh chuyển tiền nào gắn với nó.
- `set_default_account(account_id: int) -> None`: Đặt một tài khoản làm mặc định.
- `add_transfer(transfer: Transfer) -> int`: Ghi nhận chuyển tiền giữa 2 tài khoản.
- `list_transfers(account_id: Optional[int] = None, start: Optional[date] = None, end: Optional[date] = None) -> List[Transfer]`: Lấy danh sách chuyển tiền.
- `delete_transfer(transfer_id: int) -> bool`: Xóa một giao dịch chuyển tiền.
- `account_balance(account_id: int, as_of: Optional[date] = None) -> int`:
  $$\text{balance} = \text{initial\_balance} + \sum \text{income} - \sum \text{expense} + \sum \text{transfers\_in} - \sum \text{transfers\_out}$$
  (Các giao dịch không có `account_id` được gán vào tài khoản mặc định).
- `total_balance(as_of: Optional[date] = None) -> int`:
  $$\text{total} = \sum_{a \in \text{accounts}} \text{account\_balance}(a.id, as\_of)$$
  (Nếu chưa có tài khoản nào được tạo, trả về tổng thu chi như logic cũ).

---

## 4. Giao diện Dòng lệnh (CLI) & Python API

### 4.1. Lệnh Quản lý Tài khoản (`account`)
- `account add NAME [INITIAL_BALANCE] [--default]`:
  - Thêm tài khoản. Ví dụ: `eco account add "Tiền mặt" 1.5tr --default`.
- `account list`:
  - Trả về danh sách tài khoản: id, name, initial_balance, balance, pct, is_default.
- `account edit ID [--name NAME] [--initial-balance AMOUNT] [--default]`:
  - Sửa thông tin tài khoản.
- `account rm ID`:
  - Xóa tài khoản. Báo lỗi nếu tài khoản còn chứa giao dịch/chuyển khoản hoặc là tài khoản mặc định duy nhất.
- `account transfer FROM TO AMOUNT [-d DATE] [-n NOTE]`:
  - Chuyển tiền từ `FROM` (tên hoặc ID) sang `TO` (tên hoặc ID).
- `account transfers [--account ID_OR_NAME]`:
  - Liệt kê lịch sử chuyển tiền.

### 4.2. Cập nhật các lệnh hiện có
- `income` / `expense AMOUNT [CATEGORY] [-n NOTE] [-d DATE] [--account NAME_OR_ID]`:
  - Thêm cờ `--account` / `-a`. Không truyền thì lấy tài khoản mặc định.
- `edit ID [--amount ...] [--account NAME_OR_ID]`:
  - Cập nhật tài khoản của một giao dịch.
- `plan done ID [-d DATE] [--account NAME_OR_ID]`:
  - Chọn tài khoản thanh toán cho kế hoạch dòng tiền.
- `dash`:
  - Trong dữ liệu trả về của `dash`, bổ sung mảng `accounts: [...]` tóm tắt các tài khoản và số dư.

### 4.3. Định dạng JSON (`--json` mode)
- `account add` / `account edit`:
  `{"ok": true, "command": "account add", "data": {"account": {"id": 1, "name": "Tiền mặt", "initial_balance": 1500000, "balance": 1500000, "is_default": true}}}`
- `account list`:
  `{"ok": true, "command": "account list", "data": {"accounts": [...], "total_balance": 27000000}}`
- `account transfer`:
  `{"ok": true, "command": "account transfer", "data": {"transfer": {"id": 1, "date": "2026-11-07", "amount": 2000000, "from_account": "Techcombank", "to_account": "ZaloPay", "note": "Nap vi"}, "from_balance": 23000000, "to_balance": 2500000}}`

---

## 5. Thiết kế Giao diện Terminal (TUI)

### 5.1. Tab Bar
- Danh sách 7 tabs:
  `TABS = ["Tổng quan", "Tài khoản", "Giao dịch", "Dòng tiền", "Ngân sách", "Hũ tiết kiệm", "Biểu đồ"]`
  `TABS_SHORT = ["Tổng", "Khoản", "Giao", "Dòng", "Ngân", "Hũ", "Biểu"]`
- Icon tab:
  - Emoji: `🏦`
  - Symbol: `⌸`
  - Off: `""`

### 5.2. Nội dung Tab "Tài khoản"
- **Thanh tóm tắt phía trên**:
  - `Tổng tài sản: <số tiền>`
  - `Số tài khoản: <N> ví/tài khoản`
- **Hàng nút hành động**:
  - `[+ Thêm a]`
  - `[⇄ Chuyển tiền t]`
  - `[✎ Sửa e]`
  - `[★ Mặc định s]`
  - `[✕ Xóa d]`
- **Bảng danh sách tài khoản**:
  - Hàng: `[Icon] Tên tài khoản | Số dư hiện tại | Số dư ban đầu | Tỷ lệ %`
  - Tag `[Mặc định]` bên cạnh tài khoản chính.
  - Phím mũi tên lên/xuống hoặc click chuột để chọn tài khoản.
- **Danh sách chuyển tiền gần đây (Recent Transfers)**:
  - Hiển thị ở nửa dưới màn hình: `[Ngày] [Ví gửi] → [Ví nhận] [Số tiền] [Ghi chú]`.
- **Form Popup (Dialog)**:
  - Form Thêm/Sửa tài khoản: Tên, Số dư ban đầu, Checkbox `Đặt làm mặc định`.
  - Form Chuyển tiền: Ví nguồn, Ví đích, Số tiền (kèm chips nhanh `50k`, `100k`, `200k`, `500k`, `1tr`, `2tr`, `5tr`), Ngày, Ghi chú.

### 5.3. Tích hợp trên Tab "Giao dịch"
- Form thêm/sửa giao dịch bổ sung trường: `Tài khoản: [Tiền mặt] [ZaloPay] [Techcombank]...` dạng chips chọn nhanh.
- Tự động highlight sẵn tài khoản mặc định. Nhấn Enter để lưu ngay lập tức mà không phát sinh thêm thao tác thừa.

### 5.4. Tích hợp trên Tab "Tổng quan"
- Thêm một mini widget hiển thị nhanh vị trí tiền:
  `Tiền mặt: 1.5tr  │  ZaloPay: 500k  │  Techcombank: 25tr`

---

## 6. Xử lý Lỗi & Trường hợp biên (Edge Cases)

1. **Chưa có tài khoản nào được tạo**:
   - Nếu database chưa tạo tài khoản nào, hệ thống vẫn hoạt động tương thích ngược: giao dịch thu chi tính tổng như cũ.
   - Khi vào tab "Tài khoản", hiển thị màn hình trống thân thiện với gợi ý nhấn `[+ Thêm tài khoản a]`.
2. **Xóa tài khoản đang chứa dữ liệu**:
   - Chặn xóa tài khoản nếu đang có giao dịch (`account_id = ...`) hoặc lệnh chuyển khoản (`from_account_id` hoặc `to_account_id`). Thông báo rõ ràng: *"Không thể xóa tài khoản đã có giao dịch hoặc lịch sử chuyển tiền"*.
3. **Xóa tài khoản mặc định**:
   - Không cho phép xóa nếu là tài khoản mặc định duy nhất. Nếu còn tài khoản khác, yêu cầu đặt tài khoản khác làm mặc định trước.
4. **Chuyển tiền vào chính nó (`from_account == to_account`)**:
   - Báo lỗi không hợp lệ (exit 2 trong CLI).
5. **Số tiền chuyển ≤ 0 hoặc cú pháp sai**:
   - Báo lỗi qua `fmt.parse_money`.

---

## 7. Kế hoạch Kiểm thử (Testing)

1. **Unit tests DB & Models (`tests/test_accounts_db.py`)**:
   - Thêm tài khoản, tự động chọn default cho tài khoản đầu tiên.
   - Tính toán số dư tài khoản theo Thu/Chi/Chuyển tiền.
   - Ràng buộc không xóa tài khoản có giao dịch/chuyển tiền.
2. **API & JSON CLI tests (`tests/test_accounts_cli.py`)**:
   - `account add`, `account list`, `account edit`, `account rm`, `account transfer`.
   - Cờ `--account` trên `income`, `expense`, `edit`.
   - Kiểm tra `dash` bao gồm dữ liệu accounts.
   - Đảm bảo JSON mode không import `rich`.
3. **TUI Tests (`tests/test_accounts_tui.py`)**:
   - Chuyển tab số 2 (Tài khoản) hiển thị đúng bảng và danh sách chuyển tiền.
   - Thao tác mở form thêm tài khoản, form chuyển tiền bằng phím tắt và click chuột.
   - Chọn tài khoản trong form Giao dịch.
   - Kiểm tra giao diện responsive ở các kích thước màn hình terminal khác nhau.
