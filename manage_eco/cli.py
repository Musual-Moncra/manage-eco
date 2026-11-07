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
        s.add_argument("category", nargs="?", default="", help="(không bắt buộc)")
        s.add_argument("-n", "--note", default="")
        s.add_argument("-d", "--date")
        s.add_argument("-a", "--account", help="tên hoặc ID tài khoản")

    s = sub.add_parser("list", help="liệt kê giao dịch")
    s.add_argument("--month", help="YYYY-MM (mặc định tháng này)")
    s.add_argument("--all", action="store_true", help="tất cả giao dịch")

    s = sub.add_parser("rm", help="xoá giao dịch")
    s.add_argument("id", type=int)

    s = sub.add_parser("edit", help="sửa giao dịch (chỉ đổi các trường được nêu)")
    s.add_argument("id", type=int)
    s.add_argument("--amount")
    s.add_argument("--category")
    s.add_argument("-n", "--note")
    s.add_argument("-d", "--date")
    s.add_argument("-a", "--account")
    s.add_argument("--kind", choices=["income", "expense"])

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
    s.add_argument("-a", "--account")
    s = psub.add_parser("cancel")
    s.add_argument("id", type=int)
    s = psub.add_parser("edit", help="sửa dòng tiền (chỉ đổi các trường được nêu)")
    s.add_argument("id", type=int)
    s.add_argument("--name")
    s.add_argument("--amount")
    s.add_argument("--category")
    s.add_argument("--due")
    s.add_argument("--every", choices=["once", "daily", "weekly", "monthly"])
    s.add_argument("--day", type=int)
    s.add_argument("--kind", choices=["income", "expense"])

    budget = sub.add_parser("budget", help="ngân sách theo danh mục")
    bsub = budget.add_subparsers(dest="sub", required=True)
    s = bsub.add_parser("set")
    s.add_argument("category")
    s.add_argument("amount")
    s = bsub.add_parser("delete", help="xoá ngân sách của danh mục")
    s.add_argument("category")
    s = bsub.add_parser("status")
    s.add_argument("--month")

    s = sub.add_parser("forecast", help="dự báo số dư theo dòng tiền")
    s.add_argument("--days", type=int, default=90)

    s = sub.add_parser("history", help="số dư theo ngày (cho biểu đồ)")
    s.add_argument("--days", type=int, default=90, help="số ngày lùi lại (0 = từ đầu)")
    s.add_argument("--ahead", type=int, default=90, help="số ngày dự báo")

    goal = sub.add_parser("goal", help="mục tiêu tiết kiệm / hũ tiết kiệm")
    gsub = goal.add_subparsers(dest="sub")
    s = gsub.add_parser("add", help="thêm mục tiêu tiết kiệm")
    s.add_argument("name")
    s.add_argument("target")
    s.add_argument("--by", required=True)
    s.add_argument("--saved", default=None)
    gsub.add_parser("list", help="liệt kê mục tiêu")
    s = gsub.add_parser("save", help="góp tiền vào mục tiêu")
    s.add_argument("id", type=int)
    s.add_argument("amount")
    s = gsub.add_parser("take", help="rút tiền từ mục tiêu")
    s.add_argument("id", type=int)
    s.add_argument("amount")
    s = gsub.add_parser("edit", help="sửa mục tiêu")
    s.add_argument("id", type=int)
    s.add_argument("--name")
    s.add_argument("--target")
    s.add_argument("--by")
    s.add_argument("--saved")
    s = gsub.add_parser("rm", help="xoá mục tiêu")
    s.add_argument("id", type=int)
    s = gsub.add_parser("_calc", help="tính tiền cần để dành mỗi tháng")
    s.add_argument("target")
    s.add_argument("--by", required=True)

    account = sub.add_parser("account", help="quản lý tài khoản / ví tiền")
    asub = account.add_subparsers(dest="sub")
    s = asub.add_parser("add", help="thêm tài khoản mới")
    s.add_argument("name", help="tên tài khoản")
    s.add_argument("balance", nargs="?", default="0", help="số dư tài khoản (mặc định: 0)")
    s.add_argument("--default", action="store_true", help="đặt làm tài khoản mặc định")

    s = asub.add_parser("list", help="liệt kê tài khoản")

    s = asub.add_parser("edit", help="sửa tài khoản")
    s.add_argument("id")
    s.add_argument("--name")
    s.add_argument("--balance", help="điều chỉnh số dư hiện tại về mức này")
    s.add_argument("--initial-balance")
    s.add_argument("--default", action="store_true", default=None)

    s = asub.add_parser("set-balance", help="điều chỉnh số dư hiện tại của tài khoản")
    s.add_argument("id")
    s.add_argument("balance", help="số dư mới (vd: 2tr, 500k, 0)")

    s = asub.add_parser("rm", help="xoá tài khoản")
    s.add_argument("id", type=int)

    s = asub.add_parser("set-default", help="đặt tài khoản làm mặc định")
    s.add_argument("id", type=int)

    s = asub.add_parser("transfer", help="chuyển tiền giữa hai tài khoản")
    s.add_argument("from", help="tài khoản nguồn (tên hoặc ID)")
    s.add_argument("to", help="tài khoản đích (tên hoặc ID)")
    s.add_argument("amount", help="số tiền chuyển")
    s.add_argument("-d", "--date")
    s.add_argument("-n", "--note", default="")

    s = asub.add_parser("transfers", help="lịch sử chuyển tiền")
    s.add_argument("--account", help="lọc theo tài khoản (tên hoặc ID)")
    s.add_argument("--start")
    s.add_argument("--end")

    sub.add_parser("dash", help="bảng tổng quan")
    sub.add_parser("categories", help="danh mục đã dùng (nhiều nhất trước)")
    sub.add_parser("ui", help="giao diện toàn màn hình (TUI)")
    s = sub.add_parser("icons", help="kiểu icon trong TUI: symbol (mặc định) | emoji | off")
    s.add_argument("mode", nargs="?", choices=["symbol", "emoji", "off"])
    s = sub.add_parser("sound", help="bật/tắt âm thanh hiệu ứng trong TUI")
    s.add_argument("state", nargs="?", choices=["on", "off"])
    return p


_GLOBAL = ("json", "db", "today", "cmd", "sub")


def _preprocess_argv(argv: Optional[List[str]]) -> Optional[List[str]]:
    if argv is None:
        argv = sys.argv[1:]
    out = []
    i = 0
    while i < len(argv):
        out.append(argv[i])
        if argv[i] == "goal":
            if i + 1 == len(argv):
                out.append("list")
            elif argv[i + 1] not in ("add", "list", "save", "take", "edit", "rm", "-h", "--help"):
                out.append("_calc")
        elif argv[i] == "account":
            if i + 1 == len(argv) or (argv[i + 1].startswith("-") and argv[i + 1] not in ("-h", "--help")):
                out.append("list")
        i += 1
    return out


def main(argv: Optional[List[str]] = None, store: Optional[Store] = None,
         console=None, today: Optional[date] = None) -> int:
    argv = _preprocess_argv(argv)
    args = build_parser().parse_args(argv)
    as_json = args.json or os.environ.get("ECO_JSON") == "1"
    if args.cmd is None:  # bare `eco`: open the TUI, or the dashboard when scripted
        args.cmd = "dash" if as_json or not sys.stdout.isatty() else "ui"
    if args.cmd == "goal":
        sub_name = getattr(args, "sub", None)
        if sub_name == "_calc":
            cmd = "goal"
        elif sub_name:
            cmd = "goal " + sub_name
        else:
            cmd = "goal list"
    elif args.cmd == "account":
        sub_name = getattr(args, "sub", None)
        cmd = "account " + (sub_name or "list")
    else:
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
