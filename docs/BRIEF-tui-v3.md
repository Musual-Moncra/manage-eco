# Brief: TUI v3 — đơn giản, gọn, dùng được bằng chuột (owner claude-2)

User feedback: "vẫn hơi khó dùng, làm đơn giản thôi, giao diện gọn gàng, thao tác được bằng chuột vì lâu tôi quên phím".
Goal: a user who forgot every shortcut can do everything by clicking visible buttons.

## Layout (top → bottom, nothing else)
1. Header 1 line: `Manage Eco` left, `Số dư 23.715.000 ₫` right (green/red).
2. Tabs 1 line, clickable: `[ Tổng quan ] [ Giao dịch ] [ Dự định ] [ Ngân sách ]` — 4 tabs only. Forecast moves into Tổng quan (a short "Sắp tới" list + the low-balance warning line). Active tab highlighted.
3. Body: plain aligned rows, no nested boxes/panels, max one thin rule between sections. Tổng quan = 3 numbers (Thu / Chi / Còn lại tháng này), ≤5 budget bars, ≤5 upcoming plans, warning. Lists (Giao dịch, Dự định): one row per item, click a row to select it (highlight), mouse wheel / ↑↓ scroll.
4. Action bar 1 line, clickable buttons that change per tab and always show their key: `[+ Chi  a] [+ Thu  i] [+ Dự định  p]` and when a row is selected `[✓ Xong  d]` (plans) / `[✕ Xoá  x]` (transactions, asks "Xoá? [Có] [Không]"), always `[Thoát  q]`.
5. Status line: last success/error message.

## Forms (replace footer prompts)
Opens in the body area, fields one under another: Số tiền, Danh mục, Ghi chú, Ngày (default hôm nay); plan form adds Tên, Ngày đến hạn, Lặp [1 lần][Hàng tuần][Hàng tháng] as clickable chips. Danh mục shows clickable chips from `api.execute("categories", {})` (top 8, for the right kind) — clicking fills the field. Quick-amount chips `[50k][100k][200k][500k][1tr]`. Buttons `[Lưu  Enter] [Huỷ  Esc]`. Tab/click moves between fields. Inline error under the field on bad input.

## Mouse
On start write `\x1b[?1000h\x1b[?1006h` (SGR click + wheel), restore `\x1b[?1000l\x1b[?1006l` in `finally` (also on exception / Ctrl-C). Parse `\x1b[<b;x;yM` (press; ignore `m` release), b=0 left, 64/65 wheel. Hit-testing: while building the screen, record a list of `(row, x0, x1, action)` for every clickable thing. Keep the layout deterministic (fixed header/tab/action rows, body rows rendered as plain lines) so screen row → item is exact. Put hit-map building in pure functions and test them.

## Constraints
- Files: you may edit ONLY `manage_eco/tui.py`, `tests/test_tui.py`. Use api.execute only (cmds: dash, list, plan list, budget status, categories, income, expense, plan add, plan done, rm).
- rich only, no new deps, no busy loop (redraw on input/resize), RSS < 45 MB.
- Keyboard keeps working (keys shown on buttons). Works at 80×24 and wide terminals.

## Verify
`python3 -m unittest discover -s tests` all OK (incl. tests: hit-map for tabs/buttons/rows at 80 and 140 cols, form submit via simulated clicks, SGR mouse parsing), plus a real pty run: click a tab, click `+ Chi`, click a category chip, type amount, Enter, then `q` → exit 0. Report max RSS.

Report: `RESULT status=… files=… tests=…` to claude-1.
