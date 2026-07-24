# -*- coding: utf-8 -*-
"""
LOF Fund Valuation GUI - Beeware/Toga

Cross-platform native desktop app for displaying real-time fund valuations
and premium/discount rates for LOF arbitrage.

Only uses toga/beeware + stdlib (sqlite3, threading). Reuses existing
fund_estimator_index_agent and fund_realtime modules.
"""

import sys
import os
import sqlite3
import threading
from datetime import datetime
from pathlib import Path

# ---------------------------------------------------------------------------
# Toga imports (v0.5.x)
# ---------------------------------------------------------------------------
try:
    import toga
    from toga.style import Pack
    from toga.style.pack import COLUMN, ROW
    from toga.dialogs import InfoDialog, QuestionDialog, ErrorDialog
    from toga.command import Command, Group
except ImportError:
    print("toga not installed. Run: pip install toga")
    sys.exit(1)

# ---------------------------------------------------------------------------
# Project path setup
# app.py is at: GUI_beeware/lof_valuator/app.py
# code/fund_estimator is at: ../code/fund_estimator (relative to GUI_beeware root)
# We need to go up 2 levels from app.py to reach fund_estimator root
# ---------------------------------------------------------------------------
_THIS_DIR = Path(__file__).resolve().parent  # GUI_beeware/lof_valuator/
_PROJECT_ROOT = _THIS_DIR.parent.parent  # E:/api/fund_estimator/
_PROJECT_CODE = _PROJECT_ROOT / "code" / "fund_estimator"
if str(_PROJECT_CODE) not in sys.path:
    sys.path.insert(0, str(_PROJECT_CODE))

# data_sources dir (for fund_realtime relative import fallback)
_DATA_SOURCES = _PROJECT_CODE / "data_sources"
if str(_DATA_SOURCES) not in sys.path:
    sys.path.insert(0, str(_DATA_SOURCES))

# ---------------------------------------------------------------------------
# Import existing modules
# ---------------------------------------------------------------------------
try:
    from fund_estimator_index_agent import estimate_realtime
except ImportError:
    estimate_realtime = None

try:
    from fund_realtime import fetch_fund_snapshot, fetch_all_fund_snapshots
except ImportError:
    fetch_fund_snapshot = None
    fetch_all_fund_snapshots = None

# ---------------------------------------------------------------------------
# Database path
# app.py is at GUI_beeware/lof_valuator/app.py
# DB is at E:/api/fund_estimator/lof_database/lof_master.db
# So we need to go up TWO levels from _THIS_DIR
# ---------------------------------------------------------------------------
_DB_PATH = str(_PROJECT_ROOT / "lof_database" / "lof_info.db")


# ===================================================================
# Main Window
# ===================================================================

class MainWindow(toga.Window):
    """Main application window with toolbar and data table."""

    def __init__(self, app):
        super().__init__(
            title="基金实时估值系统 - LOF套利辅助",
            size=(1400, 800),
        )

        self.app = app

        # Column definitions
        self._col_keys = [
            "fund_code", "fund_name",
            "intraday_price", "intraday_change",
            "est_nav", "est_change",
            "premium_pct", "signal",
            "status",
        ]
        self._col_labels = [
            "基金代码", "基金名称",
            "场内价格", "场内涨幅%",
            "估算净值", "估算涨幅%",
            "溢价率%", "套利信号", "状态",
        ]

        # ---- Toolbar widgets ----
        self._input_box = toga.TextInput(
            placeholder="输入基金代码或名称",
            style=Pack(width=180),
        )
        self._btn_calc = toga.Button(
            "计算",
            on_press=lambda _: self._on_calculate_single(),
            style=Pack(margin_left=5),
        )
        self._btn_calc_all = toga.Button(
            "计算全部",
            on_press=lambda _: self._on_calculate_all(),
            style=Pack(margin_left=5),
        )
        self._btn_realtime = toga.Button(
            "实时行情",
            on_press=lambda _: self._on_realtime_only(),
            style=Pack(margin_left=5),
        )

        toolbar_box = toga.Box(
            children=[
                toga.Label("基金:", style=Pack(padding_right=5)),
                self._input_box,
                self._btn_calc,
                self._btn_calc_all,
                self._btn_realtime,
            ],
            style=Pack(direction=ROW, padding=5),
        )

        # ---- Table ----
        self._table = toga.Table(
            columns=self._col_labels,
            data=[],
            style=Pack(flex=1),
        )

        # ---- Status bar ----
        self._status_label = toga.Label(
            "就绪",
            style=Pack(padding=3),
        )

        # ---- Layout ----
        main_box = toga.Box(
            children=[
                toolbar_box,
                self._table,
                self._status_label,
            ],
            style=Pack(direction=COLUMN, flex=1),
        )

        self.content = main_box
        self.show()

    # -------------------------------------------------------------------
    # Database helpers
    # -------------------------------------------------------------------

    def _fetch_all_funds(self):
        """Return [(fund_code, fund_name), ...] from active_lofs (trading-active subset)."""
        try:
            conn = sqlite3.connect(_DB_PATH)
            c = conn.cursor()
            c.execute("SELECT fund_code, fund_name FROM active_lofs ORDER BY fund_code")
            rows = c.fetchall()
            conn.close()
            return rows
        except Exception:
            return []

    def _find_fund_code(self, query):
        """Find fund code by name or code. Returns (code, name) or None."""
        query = query.strip()
        if not query:
            return None
        try:
            conn = sqlite3.connect(_DB_PATH)
            c = conn.cursor()
            if len(query) == 6 and query.isdigit():
                c.execute(
                    "SELECT fund_code, fund_name FROM active_lofs WHERE fund_code = ?",
                    (query,),
                )
                row = c.fetchone()
                conn.close()
                return row
            c.execute(
                "SELECT fund_code, fund_name FROM active_lofs "
                "WHERE fund_name LIKE ? OR full_name LIKE ? OR pinyin LIKE ? "
                "LIMIT 10",
                (f"%{query}%", f"%{query}%", f"%{query}%"),
            )
            rows = c.fetchall()
            conn.close()
            if not rows:
                return None
            return rows[0]
        except Exception:
            return None

    # -------------------------------------------------------------------
    # UI helpers
    # -------------------------------------------------------------------

    def _set_status(self, msg):
        self._status_label.text = msg

    def _show_info(self, title, message):
        self.app.main_window.loop.call_later(
            0, lambda: self.app.dialog(InfoDialog(title, message))
        )

    def _show_question(self, title, message):
        def _show():
            dlg = QuestionDialog(title, message)
            self.app.main_window.loop.call_later(0, lambda: self.app.dialog(dlg))
        self.app.main_window.loop.call_later(0, _show)

    def _show_error(self, title, message):
        self.app.main_window.loop.call_later(
            0, lambda: self.app.dialog(ErrorDialog(title, message))
        )

    # -------------------------------------------------------------------
    # Row builder
    # -------------------------------------------------------------------

    def _build_row(self, fund_code, fund_name, snapshot=None, t1_nav="", est_method="", status=""):
        """Build a dict for toga.Table row."""
        if not snapshot:
            snapshot = {}
        return {
            "fund_code": fund_code,
            "fund_name": fund_name,
            "intraday_price": f'{snapshot.get("intraday_price", 0):.4f}',
            "intraday_change": f'{snapshot.get("intraday_change_pct", 0):.2f}',
            "est_nav": f'{snapshot.get("estimated_nav", 0):.4f}',
            "est_change": f'{snapshot.get("estimate_change_pct", 0):.2f}',
            "premium_pct": f'{snapshot.get("premium_pct", 0):.2f}',
            "signal": snapshot.get("signal", ""),
            "status": status,
        }

    # -------------------------------------------------------------------
    # Single fund calculation
    # -------------------------------------------------------------------

    def _on_calculate_single(self):
        query = self._input_box.value or ""
        result = self._find_fund_code(query)
        if not result:
            self._show_error("错误", f"未找到匹配的基金: {query}")
            return
        fund_code, fund_name = result
        self._set_status(f"正在计算 {fund_code} {fund_name} ...")
        threading.Thread(
            target=self._calc_single_thread,
            args=(fund_code, fund_name),
            daemon=True,
        ).start()

    def _calc_single_thread(self, fund_code, fund_name):
        today = datetime.now().strftime("%Y-%m-%d")

        snapshot = None
        if fetch_fund_snapshot:
            try:
                snapshot = fetch_fund_snapshot(fund_code)
            except Exception:
                pass

        t1_nav = ""
        est_method = ""
        if estimate_realtime:
            try:
                est_result = estimate_realtime(fund_code, today)
                if est_result.get("success"):
                    t1_nav = f"{est_result.get('t1_nav', 0):.4f}"
                    est_method = est_result.get("method_used") or est_result.get("method", "")
            except Exception:
                pass

        row_data = self._build_row(
            fund_code, fund_name, snapshot,
            t1_nav=t1_nav, est_method=est_method, status="估值",
        )

        def _update():
            self._table.data.clear()
            self._table.data.append(row_data)
            prem = row_data.get("premium_pct", "N/A")
            sig = row_data.get("signal", "")
            self._set_status(f"{fund_code} | 溢价: {prem}% | {sig}")

        self.app.main_window.loop.call_later(0, _update)

    # -------------------------------------------------------------------
    # Realtime only (fast, no fund_estimator)
    # -------------------------------------------------------------------

    def _on_realtime_only(self):
        query = self._input_box.value or ""
        if not query:
            self._batch_realtime_all()
        else:
            result = self._find_fund_code(query)
            if not result:
                self._show_error("错误", f"未找到: {query}")
                return
            fund_code, fund_name = result
            self._set_status(f"获取 {fund_code} {fund_name} 实时行情...")
            threading.Thread(
                target=self._realtime_single_thread,
                args=(fund_code, fund_name),
                daemon=True,
            ).start()

    def _realtime_single_thread(self, fund_code, fund_name):
        snapshot = None
        if fetch_fund_snapshot:
            try:
                snapshot = fetch_fund_snapshot(fund_code)
            except Exception:
                pass

        row_data = self._build_row(
            fund_code, fund_name, snapshot, status="实时",
        )

        def _update():
            self._table.data.clear()
            self._table.data.append(row_data)
            self._set_status(
                f"{fund_code} | 溢价: {row_data.get('premium_pct', 'N/A')}% | {row_data.get('signal', '')}"
            )

        self.app.main_window.loop.call_later(0, _update)

    def _batch_realtime_all(self):
        funds = self._fetch_all_funds()
        if not funds:
            self._show_error("错误", "数据库中无基金数据")
            return
        total = len(funds)
        self._set_status(f"共 {total} 只基金，开始获取实时行情...")
        threading.Thread(
            target=self._batch_realtime_thread,
            args=(funds, total),
            daemon=True,
        ).start()

    def _batch_realtime_thread(self, funds, total):
        fund_codes = [f[0] for f in funds]
        fund_names = {f[0]: f[1] for f in funds}

        snapshots = []
        if fetch_all_fund_snapshots:
            try:
                snapshots = fetch_all_fund_snapshots(fund_codes)
            except Exception:
                snapshots = []

        rows = []
        for i, snap in enumerate(snapshots):
            code = snap.get("fund_code", fund_codes[i] if i < len(fund_codes) else "")
            name = snap.get("fund_name", fund_names.get(code, ""))
            row_data = self._build_row(
                code, name, snap,
                status="OK" if "error" not in snap else "数据不足",
            )
            rows.append(row_data)

        def _update():
            self._table.data.clear()
            for r in rows:
                self._table.data.append(r)
            ok = sum(1 for r in rows if r.get("status", "") == "OK")
            self._set_status(f"完成! 成功: {ok}, 总计: {total}")

        self.app.main_window.loop.call_later(0, _update)

    # -------------------------------------------------------------------
    # Calculate All (full: fund_estimator + realtime)
    # -------------------------------------------------------------------

    def _on_calculate_all(self):
        funds = self._fetch_all_funds()
        if not funds:
            self._show_error("错误", "数据库中无基金数据")
            return
        total = len(funds)
        self._set_status(f"共 {total} 只基金，开始批量计算...")
        threading.Thread(
            target=self._calc_all_thread,
            args=(funds, total),
            daemon=True,
        ).start()

    def _calc_all_thread(self, funds, total):
        today = datetime.now().strftime("%Y-%m-%d")
        rows = []

        for i, (fund_code, fund_name) in enumerate(funds):
            snapshot = None
            if fetch_fund_snapshot:
                try:
                    snapshot = fetch_fund_snapshot(fund_code)
                except Exception:
                    pass

            t1_nav = ""
            est_method = ""
            if estimate_realtime:
                try:
                    est_result = estimate_realtime(fund_code, today)
                    if est_result.get("success"):
                        t1_nav = f"{est_result.get('t1_nav', 0):.4f}"
                        est_method = est_result.get("method_used") or est_result.get("method", "")
                except Exception:
                    pass

            row_data = self._build_row(
                fund_code, fund_name, snapshot,
                t1_nav=t1_nav, est_method=est_method,
                status=f"T-1:{t1_nav}" + (f" {est_method}" if est_method else "失败"),
            )
            rows.append(row_data)

            if i % 20 == 0:
                self._set_status(f"进度: {i + 1}/{total}")

        def _update():
            self._table.data.clear()
            for r in rows:
                self._table.data.append(r)
            ok = sum(1 for r in rows if "失败" not in r.get("status", ""))
            self._set_status(f"计算完成! 成功: {ok}, 总计: {total}")

        self.app.main_window.loop.call_later(0, _update)


# ===================================================================
# App
# ===================================================================

class FundValuatorApp(toga.App):

    def startup(self):
        # Commands (menus in Toga 0.5.x are commands)
        self.commands.add(
            Command(
                "_refresh_all",
                Group("_File", 10),
                text="刷新全部 (F5)",
                tooltip="获取全部基金实时行情",
                shortcut="f5",
            ),
            Command(
                "_quit",
                Group("_File", 20),
                text="退出",
                shortcut="q",
            ),
            Command(
                "_about",
                Group("_Help", 10),
                text="关于",
            ),
        )

        # Assign command handlers
        def on_refresh_all(cmd):
            self.main_window._on_realtime_only()

        def on_quit(cmd):
            self.request_exit()

        def on_about(cmd):
            self.main_window._show_info(
                "关于",
                "基金实时估值系统 v2.0\n"
                "功能: 估算净值 + 场内价格 + 溢价率/折价率\n"
                "数据来源:\n"
                "  场内价格: 腾讯行情 (qt.gtimg.cn)\n"
                "  估算净值: 天天基金 (fundgz.1234567.com.cn)\n"
                "  估值算法: fund_estimator_index_agent\n"
                "套利逻辑:\n"
                "  溢价率 > +1% → 溢价卖出 (申购→转场内→卖出)\n"
                "  溢价率 < -1% → 折价买入 (买入→转场内→赎回)",
            )

        self.commands["_refresh_all"].on_action = on_refresh_all
        self.commands["_quit"].on_action = on_quit
        self.commands["_about"].on_action = on_about

        self.main_window = MainWindow(self)


def main():
    return FundValuatorApp(
        formal_name="LOF Fund Valuator",
        app_id="com.lof.valuator",
        version="0.1.0",
        description="LOF基金实时估值与套利辅助工具",
    )


if __name__ == "__main__":
    main().main_loop()
