# Brief v7 — chỉ thao tác giao diện, biểu đồ kiểu chứng khoán, VFX "ping"

User: "Tôi không muốn dùng lệnh, chỉ thao tác giao diện" · "biểu đồ line kiểu lên xuống như biểu đồ chứng khoán" · "VFX kiểu ping ping lúc tương tác UI".
Limits unchanged: rich only, no deps, idle = zero redraws, RSS < 45 MB, mouse + keyboard, symbol icon mode safe glyphs (braille U+2800–28FF and box/blocks are OK in symbol mode; emoji only in emoji mode), every test passes.

## A. `manage_eco/chart.py` — antigravity-1 (pure, deterministic, returns list[rich.text.Text] + hit info)
- `line_chart(series, forecast, width, height, *, cursor=None, glyphs="symbol") -> Chart` where series/forecast are api `history` rows.
  - Braille plot (2×4 dots per cell) of balance; history solid, forecast dimmer; segment color green when rising, red when falling (stock style); a dotted zero line if range crosses 0 (negative area tinted red).
  - Right price axis (3–5 ticks, short money "23,7tr"), bottom date axis (dd/mm, ≤6 labels), a "Hôm nay" divider between history and forecast.
  - `cursor` (index into series+forecast) draws a vertical crosshair + a tooltip box "Thứ 6, 06/11 · 23.715.000 ₫ · +25tr / -1,3tr".
  - Header line: last balance, change vs first point "▲ +23,7tr (+∞%)"/"▼ …" colored.
- `candle_chart(series, width, height, *, bucket="week"|"day"|"month", cursor=None)` OHLC per bucket from daily balances (open = previous close), body `█`/hollow `▯`... use `┃` wick + `█` body, green up / red down, same axes.
- `Chart` object: `.lines: List[Text]`, `.index_at(col) -> Optional[int]` (screen col inside plot → data index, for click/hover), `.plot_box` (x0,y0,x1,y1).
- Bucket helper `ohlc(series, bucket) -> List[dict(date, open, high, low, close)]`.
- Tests `tests/test_chart.py`: sizes (no line wider than width, height exact) at 40/80/160, up/down colors, ohlc math, index_at mapping, cursor tooltip, empty series.

## B. `manage_eco/anim.py` additions — antigravity-1
- `Ripple(row, col, *, glyphs="symbol", duration=0.35)` → `cells(t)` expanding ring `· ∘ ○ ◌` (radius 0→3 cells, aspect-corrected: 2 cols per row) fading; ascii `. o O`.
- `Press(duration=0.12)` → `active(t) -> bool` (caller inverts the pressed button span).
- `slide(x_from, x_to, t, duration=0.18) -> int` eased underline position.
- `Glow(width, duration=0.4)` → `style_at(col, t)` sweeping highlight across a selected row.

## C. `manage_eco/tui.py` — claude-2
1. **New tab "Biểu đồ"** (⌁/📈 icon): range chips `[1T][3T][6T][1N][Tất cả]` (days 30/90/180/365/0) + forecast chips `[+0][+30][+90]` + mode chips `[Line][Nến]` + bucket chips for Nến `[Ngày][Tuần][Tháng]`; click on plot / ←→ moves cursor (tooltip); data from api `history`. Fill all available rows. Tổng quan's sparkline links to it (click → Biểu đồ tab).
2. **Everything without commands** (audit each CLI command; each must be reachable by clicks):
   - Ngân sách tab: `[+ Ngân sách]` form (category chips + amount chips + arithmetic), select row → `[✎ Sửa]` (change limit) / `[✕ Xoá]` (confirm) via api budget set / budget delete; month nav `‹ Tháng 11/2026 ›` (budget status month).
   - Giao dịch tab: month nav `‹ ›` + `[Tất cả]` chip; category filter chips optional.
   - Dòng tiền: `[⊘ Huỷ]` button for selected (plan cancel, confirm), filter chips `[Đang chờ][Tất cả]`.
   - Tổng quan: month summary by category (top 5 bars) — api summary.
   - **Mục tiêu** (savings goal) small card on Tổng quan with `[✎]` → form target + date chips → api goal; store last target/by in api setting? keep in-session OK.
   - Settings popover `[⚙ Cài đặt]` on the tab row: Âm thanh on/off, Icon symbol/emoji/off — clickable chips.
3. **VFX on every interaction**: Ripple at the click point; Press flash on the clicked button/chip; tab underline slides (anim.slide); Glow sweep on newly selected row; sfx `click` (soft ping) on button/chip clicks (not on every key), existing sfx stay. All overlays, never shift layout; the loop only ticks while any VFX is alive.
4. Tests: chart tab hit-map (range chips, cursor click), budget add/edit/delete by clicks, plan cancel by click, month nav, settings chips, VFX lifecycle with fake clock (ripple ends → blocking read again), no emoji in symbol mode.

## D. opencode-1
- `tests/test_json.py`: `history` (days/ahead/0, balances match transactions, forecast step values), `budget delete` (ok, not found exit 1).
- README: rewrite usage around the UI ("Hướng dẫn dùng giao diện": every task as click steps), keep CLI as a short appendix for agents; AGENTS.md: history + budget delete.

Verify (claude-1): unittest discover, memcheck, idlecheck, pty runs 50/100/170, chart rendered by eye.
Report: `RESULT status=… files=… tests=…` to claude-1.
