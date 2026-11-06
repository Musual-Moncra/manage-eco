# Brief: TUI v5 — dễ thương, co giãn theo terminal, có animation (user request)

User: "làm giao diện dễ thương, scalable hơn và cute hơn, thêm animation popup lúc lưu dòng tiền… nhìn hay hay".
Hard limits (unchanged): rich only, no new deps, RSS < 45 MB, **idle = zero redraws/zero CPU** (block on input; only while an animation is active use a select timeout ≈ 33 ms), keyboard + mouse keep working, all existing tests pass.

## A. `manage_eco/anim.py` — owner antigravity-1 (pure, deterministic, no I/O, no time calls inside)
- `ease_out_cubic(x)`, `ease_out_back(x)` (x clamped 0..1).
- `count_up(start:int, end:int, t:float, duration=0.6) -> int` eased number (balance ticking to new value).
- `Toast(message:str, kind="success"|"error"|"info", icon:str|None=None)` with `duration` (≈2.2 s: 0.25 s pop-in with ease_out_back scale/slide from bottom, 1.6 s hold, 0.35 s fade via dimmer colors) and `frame(t, width) -> Optional[rich Text/Panel]` (None when finished), `done(t) -> bool`. Rounded pastel box, kaomoji per kind: success `(ﾉ◕ヮ◕)ﾉ*:･ﾟ✧`, error `(╥﹏╥)`, info `(•‿•)`.
- `Sparkle(width, height, seed:int, count=14, duration=0.9)` → `cells(t) -> List[(row, col, char, style)]` confetti `✦ ✧ ⋆ ˚ ♡ ✿` drifting up/out from a center point and fading; deterministic for a seed.
- `bar_fill(pct, t, duration=0.5) -> float` animated progress-bar percentage.
- `ascii_mode()` → True if `ECO_ASCII=1` or `TERM in ("linux","dumb")` or stdout encoding is not UTF-8; every glyph above has an ASCII fallback (`*`, `+`, `:)`, `:(`).
- Tests `tests/test_anim.py`: easing endpoints, toast lifecycle (None after duration), sparkle determinism and bounds, ascii fallbacks.

## B. `manage_eco/tui.py` — owner claude-2
1. **Responsive** (recompute every frame from `console.size`, SIGWINCH already wakes loop):
   - `< 60` cols: compact — tabs as icons + short labels, one column, buttons show key only when no room.
   - `60–119`: current single-column layout.
   - `≥ 120`: Tổng quan two columns (Ngân sách | Sắp tới), lists get extra columns (Ghi chú, Lặp).
   - `≥ 160`: add a 30-day balance sparkline/mini chart (▁▂▃▄▅▆▇█) on Tổng quan.
   - Height: lists use all spare rows; form scrolls (already). Never crash down to 40×12.
2. **Cute theme**: pastel palette (mint income, coral expense, lavender accent, peach warn), rounded pill buttons with padding, tab icons `🏠 Tổng quan 💸 Giao dịch 🔁 Dòng tiền 🎯 Ngân sách` (ASCII fallback via `anim.ascii_mode()`), header mascot kaomoji by mood: balance growing/ok `(◕‿◕)`, budget ≥80% `(・_・;)`, forecast negative `(｡•́︿•̀｡)`. Small category icons by keyword (ăn/uống 🍜, nhà 🏠, xăng/xe 🛵, lương 💰, mua 🛍, học 📚, điện/nước 💡, claude/app/gói 💻; else •). Keep emoji cell-width safe (rich cell_len) and hit-map exact.
3. **Animations** (via anim.py): after saving any item → Toast "Đã lưu dòng tiền ✓ Tiền nhà −5.000.000 ₫" + Sparkle around it + header balance `count_up`; after ✓ Xong → toast "Đã thanh toán…"; errors → error toast (no sparkle); switching tab → budget bars `bar_fill` 0.5 s. Overlay toast bottom-right above the action bar, not shifting layout, not clickable-through (clicks still go to hit-map underneath after it fades). Any key/click during an animation works immediately.
4. Tests in `tests/test_tui.py`: layouts at 50/80/120/170 cols (hit-map still exact, no line exceeds width), toast overlay present after a save with fake clock, loop uses blocking read when no animation is active (inject clock + reader).

## C. `scripts/idlecheck.sh` + README — owner opencode-1
- Script: run `eco` in a pty (python pty helper inside the script) at 100×30, wait 1 s, send `a`, type `50k`, Tab, `test`, Enter, wait 3 s (animation over), then sample CPU of the process for 3 s via `ps -o %cpu=` (must be ≈0, fail if > 2%), send `q`, require exit 0 and max RSS < 45 MB. Exit non-zero on failure.
- README TUI section: short "Giao diện" subsection describing responsive breakpoints, animations, `ECO_ASCII=1`.

## Verify (claude-1 runs at the end)
`python3 -m unittest discover -s tests`, `bash scripts/memcheck.sh`, `bash scripts/idlecheck.sh`, real pty run at 50, 100 and 170 cols.
Report: `RESULT status=… files=… tests=…` to claude-1.

## D. v6 PixelPopup — centered pixel-art popup (user: "popup có icon tick giữa màn hình với animation pixel terminal")
### anim.py (antigravity-1)
- `PixelPopup(icon, title, subtitle="", color=None, *, glyphs="symbol", seed=0)`; icons `check | coin | pencil | trash | cross`, each a 16×16 bitmap (list of strings, plus per-icon **stroke order**: list of pixel coords in draw order, e.g. check = short stroke down-right then long stroke up-right) rendered with half blocks `▀ ▄ █` (2 px per cell → 16 cols × 8 rows). Pastel color per icon (check mint, coin gold, pencil lavender, trash coral, cross red).
- `duration` ≈ 1.6 s. Timeline: 0–0.18 s rounded box grows from center (ease_out_back); 0.18–0.65 s icon pixels appear in stroke order (bright "pen head" pixel at the leading edge); 0.65–1.2 s hold, title/subtitle under the icon, a dotted ring pulses once around the icon (`· ∘ ○` symbol mode); 1.2–1.6 s dissolve: pixels turn `▓ → ▒ → ░ → space` in seeded random order. `cross` shakes horizontally ±1 col during 0.18–0.5 s.
- `frame(t, width, height) -> Optional[Tuple[int, int, List[rich.text.Text]]]` = (top row, left col, lines) centered on screen; None when done. `size(width, height)` → (w, h). Compact mode when width < 44 or height < 16: 8×8 bitmap (cols 8 × rows 4); if even that does not fit, return None (caller falls back to Toast).
- Pure/deterministic; tests: every icon bitmap 16×16 and its stroke covers all lit pixels, frames at t=0/0.4/1.0/1.5/1.7 (last None), centered position, compact mode, symbol mode has no codepoint ≥ U+1F000.
### tui.py (claude-2)
- Use PixelPopup centered over the body for: save (check, "Đã lưu!", item + amount), ✓ Xong (coin, "Đã thanh toán!"), sửa (pencil, "Đã sửa!"), xoá (trash, "Đã xoá"), errors (cross, message). Fall back to the bottom-right Toast if `frame()` returns None. Sparkle still bursts around the popup on success. Any key/click dismisses the popup immediately and is NOT swallowed for keys (clicks only dismiss). Idle rules unchanged.
