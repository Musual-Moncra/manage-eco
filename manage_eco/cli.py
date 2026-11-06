"""`eco` command line: expenses, cash flow and future spending plans.

Human mode renders with rich; `--json` (or ECO_JSON=1) prints one JSON object and never imports rich.
"""
import argparse
import json
import os
import sys
from datetime import date
from typing import List, Optional

from manage_eco import api
from manage_eco.db import Store


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="eco", description="Quản lý chi tiêu & dòng tiền trên terminal")
    p.add_argument("--json", action="store_true", help="xuất JSON cho script/AI agent")
    p.add_argument("--db", help="đường dẫn file dữ liệu (mặc định $ECO_DB hoặc ~/.manage_eco.db)")
    p.add_argument("--today", help="ghi đè ngày hôm nay (YYYY-MM-DD)")
    sub = p.add_subparsers(dest="cmd")

    for name, help_ in (("income", "ghi khoản thu"), ("expense", "ghi khoản chi")):
        s = sub.add_parser(name, help=help_)
        s.add_argument("amount", help="vd: 200k, 1.5tr, 1.250.000, 50k+20k, 3x150k, 1tr:4")
        s.add_argument("category")
        s.add_argument("-n", "--note", default="")
        s.add_argument("-d", "--date")

    s = sub.add_parser("list", help="liệt kê giao dịch")
    s.add_argument("--month", help="YYYY-MM (mặc định tháng này)")
    s.add_argument("--all", action="store_true", help="tất cả giao dịch")

    s = sub.add_parser("rm", help="xoá giao dịch")
    s.add_argument("id", type=int)

    s = sub.add_parser("summary", help="tổng kết thu/chi theo tháng")
    s.add_argument("--month")

    plan = sub.add_parser("plan", help="dòng tiền: khoản thu/chi tương lai, 1 lần hoặc định kỳ")
    psub = plan.add_subparsers(dest="sub", required=True)
    s = psub.add_parser("add")
    s.add_argument("name")
    s.add_argument("amount")
    s.add_argument("category")
    s.add_argument("--due", help="ngày đến hạn đầu tiên: 2026-12-01, 01/12/2026, +30")
    s.add_argument("--every", choices=["once", "daily", "weekly", "monthly"], default="once",
                   help="1 lần | hàng ngày | hàng tuần | hàng tháng")
    s.add_argument("--day", type=int, help="hàng tháng: trả cố định vào ngày N (1-31); không cần --due")
    s.add_argument("--income", action="store_true", help="đây là khoản thu dự kiến")
    s = psub.add_parser("list")
    s.add_argument("--all", action="store_true")
    s = psub.add_parser("done", help="đánh dấu đã thực hiện (ghi giao dịch)")
    s.add_argument("id", type=int)
    s.add_argument("-d", "--date")
    s = psub.add_parser("cancel")
    s.add_argument("id", type=int)

    budget = sub.add_parser("budget", help="ngân sách theo danh mục")
    bsub = budget.add_subparsers(dest="sub", required=True)
    s = bsub.add_parser("set")
    s.add_argument("category")
    s.add_argument("amount")
    s = bsub.add_parser("status")
    s.add_argument("--month")

    s = sub.add_parser("forecast", help="dự báo số dư theo dòng tiền")
    s.add_argument("--days", type=int, default=90)

    s = sub.add_parser("goal", help="tính tiền cần để dành mỗi tháng")
    s.add_argument("target")
    s.add_argument("--by", required=True)

    sub.add_parser("dash", help="bảng tổng quan")
    sub.add_parser("categories", help="danh mục đã dùng (nhiều nhất trước)")
    sub.add_parser("ui", help="giao diện toàn màn hình (TUI)")
    s = sub.add_parser("sound", help="bật/tắt âm thanh hiệu ứng trong TUI")
    s.add_argument("state", nargs="?", choices=["on", "off"])
    return p


_GLOBAL = ("json", "db", "today", "cmd", "sub")


def main(argv: Optional[List[str]] = None, store: Optional[Store] = None,
         console=None, today: Optional[date] = None) -> int:
    args = build_parser().parse_args(argv)
    as_json = args.json or os.environ.get("ECO_JSON") == "1"
    if args.cmd is None:  # bare `eco`: open the TUI, or the dashboard when scripted
        args.cmd = "dash" if as_json or not sys.stdout.isatty() else "ui"
    cmd = args.cmd + (" " + args.sub if getattr(args, "sub", None) else "")
    params = {k: v for k, v in vars(args).items() if k not in _GLOBAL}

    try:
        if today is None:
            today = date.fromisoformat(args.today) if args.today else date.today()
        store = store or Store(args.db)
        if cmd == "ui":
            from manage_eco.tui import run_tui
            run_tui(store, today)
            return 0
        data = api.execute(cmd, params, store, today)
    except (LookupError, ValueError) as e:
        code = 1 if isinstance(e, LookupError) else 2
        msg = e.args[0] if e.args else str(e)
        if as_json:
            print(json.dumps({"ok": False, "error": msg, "code": "not_found" if code == 1 else "invalid"},
                             ensure_ascii=False))
        else:
            _console(console).print("[bold red]Lỗi:[/] %s" % msg)
        return code

    if as_json:
        print(json.dumps({"ok": True, "command": cmd, "data": data}, ensure_ascii=False))
    else:
        from manage_eco.views import render
        _console(console).print(render(cmd, data))
    return 0


def _console(console):
    if console is None:
        from rich.console import Console
        console = Console()
    return console


if __name__ == "__main__":
    sys.exit(main())
