"""Data serialization and tab-level whitelist filtering for shared web view.

Never imports rich. Pure dict/JSON friendly outputs.
"""
from datetime import date
from typing import Any, Dict, List, Optional, Set

from manage_eco import api

ALL_SHAREABLE_TABS: Dict[str, str] = {
    "overview": "Tổng quan",
    "accounts": "Tài khoản",
    "transactions": "Giao dịch",
    "cashflow": "Dòng tiền",
    "budgets": "Ngân sách",
    "goals": "Hũ tiết kiệm",
    "chart": "Biểu đồ",
}

TAB_KEY_BY_INDEX: List[str] = [
    "overview",
    "accounts",
    "transactions",
    "cashflow",
    "budgets",
    "goals",
    "chart",
]

INDEX_BY_TAB_KEY: Dict[str, int] = {k: i for i, k in enumerate(TAB_KEY_BY_INDEX)}


def get_shared_snapshot(
    store: Any,
    today: date,
    allowed_tabs: Set[str],
    active_tab: str = "overview",
    sync_mode: str = "free",
) -> Dict[str, Any]:
    """Serialize and return data snapshot only for tabs in allowed_tabs whitelist.

    Strictly excludes any records or data belonging to unpermitted tabs.
    """
    month_str = today.strftime("%Y-%m")
    tabs_data: Dict[str, Any] = {}

    if "overview" in allowed_tabs:
        tabs_data["overview"] = api.execute("dash", {}, store, today)

    if "accounts" in allowed_tabs:
        tabs_data["accounts"] = api.execute("account list", {}, store, today)

    if "transactions" in allowed_tabs:
        tabs_data["transactions"] = api.execute("list", {"month": month_str}, store, today)

    if "cashflow" in allowed_tabs:
        tabs_data["cashflow"] = api.execute("plan list", {"all": False}, store, today)

    if "budgets" in allowed_tabs:
        tabs_data["budgets"] = api.execute("budget status", {"month": month_str}, store, today)

    if "goals" in allowed_tabs:
        tabs_data["goals"] = api.execute("goal list", {}, store, today)

    if "chart" in allowed_tabs:
        tabs_data["chart"] = api.execute("history", {"days": 30, "ahead": 30}, store, today)

    return {
        "today": today.isoformat(),
        "month": month_str,
        "active_tab": active_tab,
        "sync_mode": sync_mode,
        "allowed_tab_keys": sorted(list(allowed_tabs)),
        "tab_labels": {k: ALL_SHAREABLE_TABS[k] for k in allowed_tabs if k in ALL_SHAREABLE_TABS},
        "tabs": tabs_data,
    }
