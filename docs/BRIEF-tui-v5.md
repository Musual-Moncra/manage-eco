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
