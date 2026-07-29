# -*- coding: utf-8 -*-
"""
基金实时估值系统 - LOF 套利辅助工具

功能:
  1. 获取基金估算净值 (天天基金 fundgz)
  2. 获取基金场内实时价格 (腾讯 qt.gtimg.cn)
  3. 计算溢价率/折价率
  4. 提示套利机会 (折价买入 / 溢价卖出)
"""

import sys
import os
import csv
import sqlite3
import threading
import wx
import wx.grid
from datetime import datetime

# ====================================================================
# Path setup
# ====================================================================
_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
_PROJECT_CODE = os.path.join(_SCRIPT_DIR, '..', 'code', 'fund_estimator')
if _PROJECT_CODE not in sys.path:
    sys.path.insert(0, _PROJECT_CODE)

# data_sources 目录需要在路径中 (for relative imports in fund_realtime)
_DATA_SOURCES = os.path.join(_PROJECT_CODE, 'data_sources')
if _DATA_SOURCES not in sys.path:
    sys.path.insert(0, _DATA_SOURCES)

from fund_estimator_index_agent import estimate_realtime
from fund_realtime import (
    fetch_fund_snapshot,
    fetch_all_fund_snapshots,
)

# --- 商品 / 商品期货基金估值模块（v_futures 实时 / v_random 离线） ---
# 当点击"计算"或"计算全部"且基金是商品/商品期货 LOF 时，
# 自动路由到 fund_estimator_product 模块，使用 v_futures 进行盘中实时估值。
try:
    from fund_estimator.fund_estimator_product import (
        estimate_commodity_realtime as _estimate_commodity_realtime,
        get_commodity_for_fund as _get_commodity_for_fund,
        COMMODITY_MAP as _COMMODITY_MAP,
    )
    _HAS_COMMODITY_MODULE = True
except ImportError:
    _HAS_COMMODITY_MODULE = False
    _estimate_commodity_realtime = None
    _get_commodity_for_fund = None
    _COMMODITY_MAP = {}

# --- 债券型基金估值模块（v_bond_sse_gov 实时 / v_bond_blend 离线） ---
# 当点击"计算"或"计算全部"且基金是债券型 LOF（如 164703 汇添富纯债(LOF)A）时，
# 自动路由到 fund_estimator_bond 模块，使用 v_bond_sse_gov（上证国债指数代理）进行盘中实时估值。
try:
    from fund_estimator.fund_estimator_bond import (
        estimate_bond_realtime as _estimate_bond_realtime,
        get_bond_info_for_fund as _get_bond_info_for_fund,
        BOND_MAP as _BOND_MAP,
    )
    _HAS_BOND_MODULE = True
except ImportError:
    _HAS_BOND_MODULE = False
    _estimate_bond_realtime = None
    _get_bond_info_for_fund = None
    _BOND_MAP = {}

# --- Database path ---
_DB_PATH = os.path.join(_SCRIPT_DIR, '..', 'lof_database', 'lof_info.db')


# ====================================================================
# Commodity fund routing
# ====================================================================

def _is_commodity_fund(fund_code: str, fund_name: str = "") -> bool:
    """判断基金是否为商品 / 商品期货基金。

    判定规则（按优先级）：
      1) fund_code 已在 COMMODITY_MAP 中（强信号，准确）
      2) 基金名称含"期货"或"白银"/"黄金"/"原油"/"商品"/"有色"等关键词（弱信号）

    真正的 FTYPE（fundmobapi.eastmoney.com 返回的"商品"标识）也可作为信号，
    但本函数仅做最轻量判断（避免在单只基金计算时触发联网），准确判定
    由 estimate_realtime 内部 classify_fund_type() 完成。
    """
    if not _HAS_COMMODITY_MODULE:
        return False
    # 信号 1：COMMODITY_MAP 命中（最强）
    if _get_commodity_for_fund and _get_commodity_for_fund(fund_code) is not None:
        return True
    # 信号 2：名称含商品/期货关键词（弱）
    if fund_name:
        for kw in ("白银", "黄金", "原油", "商品", "有色", "期货"):
            if kw in fund_name:
                return True
    return False


def _route_commodity_estimate(
    fund_code: str,
    fund_name: str,
    today: str,
    method: str = "v_futures",
    force: bool = False,
) -> dict:
    """商品基金估值路由：把 estimate_realtime 风格的调用路由到商品模块。

    优先使用 ``v_futures``（盘中实时用 SHFE 期货价代理，理论 MAE ~0.1pp）；
    若 sina hq 不可用 / 非盘中时段，``estimate_commodity_realtime`` 内部会
    fallback 到 v_random。

    Returns
    -------
    dict
        字段命名与 ``estimate_realtime`` 兼容（success, t1_nav, estimated_nav,
        estimated_change_pct, method, detail, official_nav, error_pp, ...），
        GUI 可直接复用。
    """
    if not _HAS_COMMODITY_MODULE:
        return {
            "success": False,
            "fund_code": fund_code,
            "trade_date": today,
            "error": "fund_estimator_product 模块未加载（ImportError）",
            "method": method,
        }

    result = _estimate_commodity_realtime(
        fund_code=fund_code,
        trade_date=today,
        method=method,
        force=force,
    )
    # 补充 method_used 字段（与 estimate_realtime 输出一致）
    if "method_used" not in result:
        result["method_used"] = result.get("method", method)
    if "method_reason" not in result:
        result["method_reason"] = (
            f"商品/商品期货基金 ({fund_name})，"
            f"自动路由到 fund_estimator_product，使用 {result.get('method', method)}"
        )
    return result


# ====================================================================
# Bond fund routing
# ====================================================================

def _is_bond_fund(fund_code: str, fund_name: str = "") -> bool:
    """判断基金是否为债券型基金。

    判定规则（按优先级）：
      1) fund_code 已在 BOND_MAP 中（强信号，准确）
      2) 基金名称含"纯债"/"债券"/"债基"/"信用债"/"利率债"等关键词（弱信号）

    真正的 FTYPE（fundmobapi.eastmoney.com 返回的"债券"标识）也可作为信号，
    但本函数仅做最轻量判断（避免在单只基金计算时触发联网），准确判定
    由 estimate_bond_realtime 内部的 BOND_MAP 注册检查完成。
    """
    if not _HAS_BOND_MODULE:
        return False
    # 信号 1：BOND_MAP 命中（最强）
    if _get_bond_info_for_fund and _get_bond_info_for_fund(fund_code) is not None:
        return True
    # 信号 2：名称含债券关键词（弱）
    if fund_name:
        for kw in ("纯债", "债券", "债基", "信用债", "利率债", "金融债"):
            if kw in fund_name:
                return True
    return False


def _route_bond_estimate(
    fund_code: str,
    fund_name: str,
    today: str,
    method: str = "v_bond_sse_gov",
    force: bool = False,
) -> dict:
    """债券型基金估值路由：把 estimate_realtime 风格的调用路由到债基模块。

    优先使用 ``v_bond_sse_gov``（上证国债指数 sh000012 直接代理，实测 60d MAE 0.0219pp）；
    若 sina hq 不可用 / 非盘中时段，``estimate_bond_realtime`` 内部会
    fallback 到 T-1 涨跌% 代理。

    Returns
    -------
    dict
        字段命名与 ``estimate_realtime`` 兼容（success, t1_nav, t1_date,
        estimated_nav, estimated_change_pct, method, official_nav, error_pp, ...），
        GUI 可直接复用。
    """
    if not _HAS_BOND_MODULE:
        return {
            "success": False,
            "fund_code": fund_code,
            "trade_date": today,
            "error": "fund_estimator_bond 模块未加载（ImportError）",
            "method": method,
        }

    result = _estimate_bond_realtime(
        fund_code=fund_code,
        trade_date=today,
        method=method,
        force=force,
    )
    # 补充 method_used 字段（与 estimate_realtime 输出一致）
    if "method_used" not in result:
        result["method_used"] = result.get("method", method)
    if "method_reason" not in result:
        result["method_reason"] = (
            f"债券型基金 ({fund_name})，"
            f"自动路由到 fund_estimator_bond，使用 {result.get('method', method)}"
        )
    return result


def _format_official_nav(est_result: dict) -> tuple[str, str]:
    """从估值结果中提取官方 T 日净值 + 估值偏离。

    优先级：
      1) est_result["official_nav"] 存在（商品 / 指数 estimate_realtime 都有）
      2) 否则返回 ("未公布", "")

    估值偏离 = (估算净值 - T净值) / T净值 * 100，保留 2 位小数 + % 号。
    """
    official_nav = est_result.get("official_nav")
    if not official_nav or float(official_nav) <= 0:
        return ("未公布", "")

    est_nav = est_result.get("estimated_nav")
    if not est_nav or float(est_nav) <= 0:
        return (f"{float(official_nav):.4f}", "")

    err_pct = (float(est_nav) - float(official_nav)) / float(official_nav) * 100.0
    return (f"{float(official_nav):.4f}", f"{err_pct:+.2f}%")


# ====================================================================
# Grid 组件
# ====================================================================

class FundGrid(wx.grid.Grid):
    """基金估值表格，含场内价格与溢价率列。"""

    COLUMNS = [
        ("fund_code", "基金代码", 90),
        ("fund_name", "基金名称", 180),
        ("intraday_price", "场内价格", 90),
        ("intraday_change", "场内涨幅(%)", 90),
        ("est_nav", "估算净值", 90),
        ("est_change", "估算涨幅(%)", 90),
        ("t1_nav", "T-1净值", 80),
        ("t_nav", "T净值", 80),
        ("est_error_pct", "估值偏离(%)", 90),
        ("premium_pct", "溢价率(%)", 90),
        ("signal", "套利信号", 150),
        ("method", "算法", 130),
        ("status", "状态", 80),
    ]

    # 可点击列头排序的列：{列索引: 数据键名}
    SORTABLE_COLUMNS = {
        3: "intraday_change",  # 场内涨幅
        5: "est_change",       # 估算涨幅
        8: "est_error_pct",    # 估值偏离
        9: "premium_pct",      # 溢价率
    }

    def __init__(self, parent):
        super().__init__(parent)
        n_cols = len(self.COLUMNS)
        self.CreateGrid(0, n_cols)

        for idx, (_, label, width) in enumerate(self.COLUMNS):
            self.SetColLabelValue(idx, label)
            self.SetColMinimalWidth(idx, width)
            self.AutoSizeColumn(idx, False)

        self.EnableEditing(False)
        self.SetRowLabelSize(0)

        # 颜色：溢价率正数红色背景，负数绿色背景
        self.red_colour = wx.Colour(255, 240, 240)
        self.green_colour = wx.Colour(240, 255, 240)
        self.white_colour = wx.WHITE

        # ===== 排序状态 =====
        self._raw_data = []        # 原始行数据 (list[dict])
        self._sort_col = None      # 当前排序列索引, None 表示未排序
        self._sort_asc = True      # True=升序, False=降序
        self._base_labels = [label for _, label, _ in self.COLUMNS]

        # 列头左键点击 → 切换排序
        self.Bind(wx.grid.EVT_GRID_LABEL_LEFT_CLICK, self._on_label_left_click)

    def _color_cell(self, row, col, value_str):
        """对溢价率列着色。"""
        if col == 9:  # premium_pct
            try:
                v = float(value_str)
                if v > 0:
                    self.SetCellBackgroundColour(row, col, self.red_colour)
                elif v < 0:
                    self.SetCellBackgroundColour(row, col, self.green_colour)
                else:
                    self.SetCellBackgroundColour(row, col, self.white_colour)
            except (ValueError, TypeError):
                self.SetCellBackgroundColour(row, col, self.white_colour)

    @staticmethod
    def _parse_numeric(value_str):
        """从可能带 % 或逗号的字符串中解析浮点数; 无法解析返回 None。"""
        try:
            return float(str(value_str).replace("%", "").replace(",", "").strip())
        except (ValueError, TypeError):
            return None

    def _sort_key(self, row_data, key):
        """排序键: 无法解析的值始终排在末尾。"""
        v = self._parse_numeric(row_data.get(key, ""))
        if v is None:
            return (1, 0.0)
        return (0, v)

    def _update_header_indicators(self):
        """更新列头标签: 当前排序列追加 ▲/▼, 其它列恢复原始标签。"""
        for idx, base_label in enumerate(self._base_labels):
            if idx == self._sort_col:
                arrow = " ▲" if self._sort_asc else " ▼"
                self.SetColLabelValue(idx, base_label + arrow)
            else:
                self.SetColLabelValue(idx, base_label)

    def _on_label_left_click(self, event):
        """列头左键点击: 可排序列切换升/降序, 其它列放行默认行为。"""
        col = event.GetCol()
        if col in self.SORTABLE_COLUMNS:
            if self._sort_col == col:
                self._sort_asc = not self._sort_asc
            else:
                self._sort_col = col
                self._sort_asc = True
            self._apply_sort()
        else:
            event.Skip()

    def _apply_sort(self):
        """按当前排序列对 _raw_data 排序后刷新表格。"""
        self._update_header_indicators()
        if self._sort_col is None or not self._raw_data:
            return
        key = self.SORTABLE_COLUMNS[self._sort_col]
        sorted_data = sorted(
            self._raw_data,
            key=lambda r: self._sort_key(r, key),
            reverse=not self._sort_asc,
        )
        self._redraw(sorted_data)

    def _redraw(self, rows_data):
        """按 rows_data 重置表格行数与内容 (不维护 _raw_data)。"""
        if self.GetNumberRows() > 0:
            self.DeleteRows(0, self.GetNumberRows())
        if rows_data:
            self.AppendRows(len(rows_data))
            for i, row_data in enumerate(rows_data):
                self._write_row(i, row_data)

    def _write_row(self, row_idx, row_data):
        """仅写入单元格内容与颜色, 不维护 _raw_data。"""
        for idx, (key, _, _) in enumerate(self.COLUMNS):
            val = str(row_data.get(key, ""))
            self.SetCellValue(row_idx, idx, val)
            self._color_cell(row_idx, idx, val)

    def append_row(self, row_idx, row_data):
        """写入一行数据, 同时保存到 _raw_data 供后续排序使用。"""
        while len(self._raw_data) <= row_idx:
            self._raw_data.append({})
        self._raw_data[row_idx] = dict(row_data)
        self._write_row(row_idx, row_data)

    def clear_and_add(self, rows_data):
        """清空并重绘表格; 若已设置排序列, 新数据按相同规则排序。"""
        if self.GetNumberRows() > 0:
            self.DeleteRows(0, self.GetNumberRows())

        self._raw_data = list(rows_data) if rows_data else []

        if self._sort_col is not None and self._raw_data:
            key = self.SORTABLE_COLUMNS[self._sort_col]
            self._raw_data = sorted(
                self._raw_data,
                key=lambda r: self._sort_key(r, key),
                reverse=not self._sort_asc,
            )

        self._update_header_indicators()

        if self._raw_data:
            self.AppendRows(len(self._raw_data))
            for i, row_data in enumerate(self._raw_data):
                self._write_row(i, row_data)


# ====================================================================
# 主窗口
# ====================================================================

class MainFrame(wx.Frame):
    """主应用窗口。"""

    def __init__(self, parent=None):
        super().__init__(
            parent,
            title="基金实时估值系统 - LOF套利辅助",
            size=(1300, 750),
        )

        self.CreateStatusBar(2)
        self.SetStatusText("就绪", 1)

        panel = wx.Panel(self)
        main_sizer = wx.BoxSizer(wx.VERTICAL)

        # ===== TOOLBAR =====
        toolbar_panel = wx.Panel(panel)
        tb_sizer = wx.BoxSizer(wx.HORIZONTAL)

        lbl = wx.StaticText(toolbar_panel, label="基金代码/名称:")
        tb_sizer.Add(lbl, 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 5)

        self.input_ctrl = wx.TextCtrl(
            toolbar_panel, size=(180, -1), style=wx.TE_PROCESS_ENTER,
        )
        self.input_ctrl.Bind(wx.EVT_TEXT_ENTER, self.on_calculate)
        tb_sizer.Add(self.input_ctrl, 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 5)

        btn_calc = wx.Button(toolbar_panel, id=wx.ID_ANY, label="计 算")
        btn_calc.Bind(wx.EVT_BUTTON, self.on_calculate)
        tb_sizer.Add(btn_calc, 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 5)

        btn_calc_all = wx.Button(toolbar_panel, id=wx.ID_ANY, label="计算全部")
        btn_calc_all.Bind(wx.EVT_BUTTON, self.on_calculate_all)
        tb_sizer.Add(btn_calc_all, 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 10)

        btn_realtime = wx.Button(toolbar_panel, id=wx.ID_ANY, label="实时行情")
        btn_realtime.Bind(wx.EVT_BUTTON, self.on_realtime_only)
        tb_sizer.Add(btn_realtime, 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 5)

        btn_export = wx.Button(toolbar_panel, id=wx.ID_ANY, label="导出CSV")
        btn_export.Bind(wx.EVT_BUTTON, self.on_export_csv)
        tb_sizer.Add(btn_export, 0, wx.ALIGN_CENTER_VERTICAL)

        # ===== 保存按钮引用，用于忙闲切换 =====
        self._busy_buttons = [btn_calc, btn_calc_all, btn_realtime, btn_export]

        toolbar_panel.SetSizer(tb_sizer)
        main_sizer.Add(toolbar_panel, 0, wx.EXPAND | wx.ALL, 5)

        # ===== GRID =====
        self.grid = FundGrid(panel)
        main_sizer.Add(self.grid, 1, wx.EXPAND | wx.ALL, 5)

        # ===== BOTTOM PROGRESS =====
        bottom_panel = wx.Panel(panel)
        bottom_sizer = wx.BoxSizer(wx.HORIZONTAL)
        self.progress_label = wx.StaticText(
            bottom_panel, label="", style=wx.ST_ELLIPSIZE_MIDDLE,
        )
        bottom_sizer.Add(self.progress_label, 1, wx.ALIGN_CENTER_VERTICAL | wx.ALL, 3)
        bottom_panel.SetSizer(bottom_sizer)
        main_sizer.Add(bottom_panel, 0, wx.EXPAND)

        panel.SetSizer(main_sizer)

        # ===== MENU BAR =====
        menubar = wx.MenuBar()

        file_menu = wx.Menu()
        refresh_item = file_menu.Append(wx.ID_REFRESH, "刷新(&R)\tF5", "获取全部基金实时行情")
        exit_item = file_menu.Append(wx.ID_EXIT, "退出(&X)")
        menubar.Append(file_menu, "文件(&F)")
        self.Bind(wx.EVT_MENU, self.on_refresh, refresh_item)
        self.Bind(wx.EVT_MENU, self.on_exit, exit_item)

        help_menu = wx.Menu()
        about_item = help_menu.Append(wx.ID_ABOUT, "关于(&A)")
        menubar.Append(help_menu, "帮助(&H)")
        self.Bind(wx.EVT_MENU, self.on_about, about_item)

        self.SetMenuBar(menubar)
        self.Bind(wx.EVT_KEY_DOWN, self.on_key_down)

        # ===== 线程控制状态 =====
        self._busy = False

    def _set_busy(self, busy: bool):
        """忙闲切换：禁用/启用操作按钮，更新状态栏。"""
        self._busy = busy
        for btn in self._busy_buttons:
            btn.Enable(not busy)
        if busy:
            self.status_bar_set("正在计算，请稍候...")
        else:
            self.status_bar_set("就绪")
        wx.Yield()

    # ---- Events ----

    def on_key_down(self, event):
        if event.GetKeyCode() == wx.WXK_F5:
            self.on_refresh(event)
        else:
            event.Skip()

    def on_exit(self, event):
        self.Close(True)

    def on_about(self, event):
        wx.MessageBox(
            "基金实时估值系统 v2.0\n"
            "功能: 估算净值 + 场内价格 + 溢价率/折价率\n"
            "数据来源:\n"
            "  场内价格: 腾讯行情 (qt.gtimg.cn)\n"
            "  估算净值: 天天基金 (fundgz.1234567.com.cn)\n"
            "  估值算法: fund_estimator_index_agent\n"
            "套利逻辑:\n"
            "  溢价率 > +2.5% → 溢价卖出 (申购→转场内→卖出)\n"
            "  溢价率 < -2.5% → 折价买入 (买入→转场内→赎回)\n"
            "{}".format(datetime.now().strftime("%Y-%m-%d")),
            "关于",
            wx.OK | wx.ICON_INFORMATION,
            self,
        )

    def status_bar_set(self, msg):
        """主线程：直接更新状态栏。"""
        self.SetStatusText(msg, 0)
        self.SetStatusText(msg, 1)

    def progress_set(self, msg):
        """主线程：直接更新进度条。"""
        self.progress_label.SetLabel(msg)
        wx.Yield()

    # ---- Thread-Safe UI Dispatchers (from worker thread) ----

    def _post_status(self, msg):
        """后台线程 → 主线程：设置状态栏。"""
        def _run():
            self.status_bar_set(msg)
        if wx.IsMainThread():
            _run()
        else:
            wx.CallAfter(_run)

    def _post_progress(self, msg):
        """后台线程 → 主线程：设置进度标签。"""
        def _run():
            self.progress_set(msg)
        if wx.IsMainThread():
            _run()
        else:
            wx.CallAfter(_run)

    def _post_grid_clear_add(self, rows_data):
        """后台线程 → 主线程：清空并重绘表格。"""
        def _run():
            self.grid.clear_and_add(rows_data)
        if wx.IsMainThread():
            _run()
        else:
            wx.CallAfter(_run)

    def _post_grid_append_rows(self, count):
        """后台线程 → 主线程：为网格追加空行。"""
        def _run():
            self.grid.AppendRows(count)
        if wx.IsMainThread():
            _run()
        else:
            wx.CallAfter(_run)

    def _post_append_row(self, row_idx, row_data):
        """后台线程 → 主线程：向指定行写入数据并着色。"""
        def _run():
            self.grid.append_row(row_idx, row_data)
        if wx.IsMainThread():
            _run()
        else:
            wx.CallAfter(_run)

    def _post_set_busy(self, busy):
        """后台线程 → 主线程：切换忙闲状态。"""
        def _run():
            self._set_busy(busy)
        if wx.IsMainThread():
            _run()
        else:
            wx.CallAfter(_run)

    # ---- Fund Lookup ----

    def find_fund_code(self, query):
        """返回 (fund_code, fund_name) 或 None。"""
        query = query.strip()
        if not query:
            return None

        conn = sqlite3.connect(_DB_PATH)
        cursor = conn.cursor()

        if len(query) == 6 and query.isdigit():
            cursor.execute(
                "SELECT fund_code, fund_name FROM active_lofs WHERE fund_code = ?",
                (query,),
            )
            row = cursor.fetchone()
            conn.close()
            if row:
                return row
            return None

        cursor.execute(
            "SELECT fund_code, fund_name FROM active_lofs "
            "WHERE fund_name LIKE ? OR full_name LIKE ? OR pinyin LIKE ? "
            "LIMIT 10",
            (f"%{query}%", f"%{query}%", f"%{query}%"),
        )
        rows = cursor.fetchall()
        conn.close()

        if not rows:
            return None
        if len(rows) == 1:
            return rows[0]

        choices = [f"{code}  {name}" for code, name in rows]
        dlg = wx.SingleChoiceDialog(
            self,
            f"找到 {len(rows)} 只匹配基金，请选择：",
            "选择基金",
            choices,
        )
        if dlg.ShowModal() == wx.ID_OK:
            sel = dlg.GetStringSelection()
            parts = sel.split(" ", 1)
            return (parts[0], parts[1] if len(parts) > 1 else "")
        return None

    # ---- Worker Thread Helpers ----

    def _run_in_thread(self, target, *args, **kwargs):
        """在后台线程中运行目标函数，完成后自动恢复忙闲状态。"""
        if self._busy:
            wx.MessageBox("已有任务在运行中", "提示", wx.OK | wx.ICON_INFORMATION, self)
            return None
        self._set_busy(True)
        t = threading.Thread(target=target, args=args, kwargs=kwargs, daemon=True)
        t.start()
        return t

    # ---- Single Fund Calculation (non-blocking) ----

    def on_calculate(self, event):
        query = self.input_ctrl.GetValue().strip()
        if not query:
            wx.MessageBox("请输入基金代码或名称", "提示", wx.OK | wx.ICON_WARNING, self)
            return

        result = self.find_fund_code(query)
        if not result:
            wx.MessageBox(f"未找到匹配的基金: {query}", "错误", wx.OK | wx.ICON_ERROR, self)
            self.status_bar_set("未找到基金")
            return

        self._run_in_thread(self._do_single_calculate, result)

    def _do_single_calculate(self, result):
        """后台线程：单只基金估值计算。

        路由逻辑：
          - 商品 / 商品期货基金（如 161226）→ fund_estimator_product 的 v_futures
          - 被动指数 / 主动基金 → fund_estimator_index_agent 的 estimate_realtime
        """
        fund_code, fund_name = result
        self._post_status(f"正在计算 {fund_code} {fund_name} ...")

        try:
            # 1) 获取场内实时价格 + 估算净值 + 溢价率
            snapshot = fetch_fund_snapshot(fund_code)

            # 2) 根据基金类型选择估值入口
            today = datetime.now().strftime("%Y-%m-%d")
            t1_nav = ""
            est_method = ""
            is_commodity = _is_commodity_fund(fund_code, fund_name)
            is_bond = _is_bond_fund(fund_code, fund_name)
            est_result: dict = {}  # 用于提取官方 T 日净值

            if is_bond:
                # ===== 债券型基金 → v_bond_sse_gov 实时估值 =====
                try:
                    est_result = _route_bond_estimate(
                        fund_code, fund_name, today, method="v_bond_sse_gov",
                    )
                    if est_result.get("success"):
                        t1_nav = f"{est_result.get('t1_nav', 0):.4f}"
                        bond_subtype = est_result.get("fund_subtype", "纯债")
                        primary_idx = est_result.get("primary_index", {}) or {}
                        idx_name = primary_idx.get("name", "上证国债指数")
                        est_method = (
                            f"v_bond_sse_gov[{idx_name}]"
                        )
                        # 用债基估值结果覆盖 snapshot
                        snapshot["estimated_nav"] = est_result.get(
                            "estimated_nav", snapshot.get("estimated_nav", 0),
                        )
                        snapshot["estimate_change_pct"] = est_result.get(
                            "estimated_change_pct",
                            snapshot.get("estimate_change_pct", 0),
                        )
                except Exception as e:
                    est_method = f"v_bond失败:{type(e).__name__}"
            elif is_commodity:
                # ===== 商品 / 商品期货基金 → v_futures 实时估值 =====
                try:
                    est_result = _route_commodity_estimate(
                        fund_code, fund_name, today, method="v_futures",
                    )
                    if est_result.get("success"):
                        t1_nav = f"{est_result.get('t1_nav', 0):.4f}"
                        est_method = (
                            f"v_futures[{est_result.get('commodity', '商品')}]"
                        )
                        # 用 v_futures 的结果覆盖 snapshot 里的"估算净值/涨跌幅"
                        # —— 天天基金的官方估值对商品 LOF 误差大，v_futures 更准
                        snapshot["estimated_nav"] = est_result.get(
                            "estimated_nav", snapshot.get("estimated_nav", 0),
                        )
                        snapshot["estimate_change_pct"] = est_result.get(
                            "estimated_change_pct",
                            snapshot.get("estimate_change_pct", 0),
                        )
                except Exception as e:
                    est_method = f"v_futures失败:{type(e).__name__}"
            else:
                # ===== 指数 / 主动基金 → estimate_realtime =====
                try:
                    est_result = estimate_realtime(fund_code, today)
                    if est_result.get("success"):
                        t1_nav = f"{est_result.get('t1_nav', 0):.4f}"
                        est_method = est_result.get("method_used") or est_result.get("method", "")
                except Exception:
                    pass

            # 3) 提取 T 日官方净值 + 估值偏离
            t_nav, est_error_pct = _format_official_nav(est_result)

            # 4) 构建行数据
            row_data = {
                "fund_code": fund_code,
                "fund_name": fund_name,
                "intraday_price": f'{snapshot.get("intraday_price", 0):.4f}',
                "intraday_change": f'{snapshot.get("intraday_change_pct", 0):.2f}%',
                "est_nav": f'{snapshot.get("estimated_nav", 0):.4f}',
                "est_change": f'{snapshot.get("estimate_change_pct", 0):.2f}%',
                "t1_nav": t1_nav,
                "t_nav": t_nav,
                "est_error_pct": est_error_pct,
                "premium_pct": f'{snapshot.get("premium_pct", 0):.2f}',
                "signal": snapshot.get("signal", ""),
                "method": est_method,
                "status": "成功",
            }

            final_snapshot = snapshot

            self._post_grid_clear_add([row_data])
            tag = ""
            if is_bond and est_method:
                tag = f" | [债基:{est_method}]"
            elif is_commodity and est_method:
                tag = f" | [商品:{est_method}]"
            self._post_status(
                f"{fund_code} {fund_name} | 场内: {row_data['intraday_price']} | "
                f"估算: {row_data['est_nav']} | 溢价: {row_data['premium_pct']}% | "
                f"{final_snapshot.get('signal', '')}"
                + tag
            )
        except Exception as e:
            self._post_status(f"计算出错: {e}")
        finally:
            self._post_set_busy(False)

    # ---- Real-time only (non-blocking) ----

    def on_realtime_only(self, event):
        """仅获取场内价格 + 天天基金估算，快速计算溢价率。"""
        query = self.input_ctrl.GetValue().strip()

        if not query:
            # 无输入: 对所有 LOF 做快照（走确认弹窗后启动后台线程）
            self._confirm_and_start_batch_realtime()
        else:
            # 有输入: 单只基金
            result = self.find_fund_code(query)
            if not result:
                wx.MessageBox(f"未找到: {query}", "错误", wx.OK | wx.ICON_ERROR, self)
                return
            self._run_in_thread(self._do_realtime_one, result)

    def _do_realtime_one(self, result):
        """后台线程：单只基金实时行情。"""
        fund_code, fund_name = result
        self._post_status(f"获取 {fund_code} {fund_name} 实时行情...")

        try:
            snapshot = fetch_fund_snapshot(fund_code)
            row_data = {
                "fund_code": fund_code,
                "fund_name": fund_name,
                "intraday_price": f'{snapshot.get("intraday_price", 0):.4f}',
                "intraday_change": f'{snapshot.get("intraday_change_pct", 0):.2f}%',
                "est_nav": f'{snapshot.get("estimated_nav", 0):.4f}',
                "est_change": f'{snapshot.get("estimate_change_pct", 0):.2f}%',
                "t1_nav": "",
                "t_nav": "",
                "est_error_pct": "",
                "premium_pct": f'{snapshot.get("premium_pct", 0):.2f}',
                "signal": snapshot.get("signal", ""),
                "method": "",
                "status": "成功" if "error" not in snapshot else "数据不足",
            }
            self._post_grid_clear_add([row_data])
            self._post_status(
                f"{fund_code} | 场内: {row_data['intraday_price']} | "
                f"溢价: {row_data['premium_pct']}% | {row_data['signal']}"
            )
        except Exception as e:
            self._post_status(f"行情获取出错: {e}")
        finally:
            self._post_set_busy(False)

    def _confirm_and_start_batch_realtime(self):
        """确认弹窗 + 启动后台批量行情线程（弹窗在主线程执行）。"""
        funds = self._fetch_all_funds_basic()
        if not funds:
            wx.MessageBox("数据库中无基金数据", "错误", wx.OK | wx.ICON_ERROR, self)
            return

        total = len(funds)
        dlg = wx.MessageDialog(
            self,
            f"将对 {total} 只基金获取实时行情和估算净值，\n"
            "此过程可能需要几分钟，请耐心等待。\n"
            "是否继续？",
            "确认批量获取",
            wx.YES_NO | wx.NO_DEFAULT | wx.ICON_QUESTION,
        )
        answer = dlg.ShowModal()
        dlg.Destroy()
        if answer != wx.ID_YES:
            self.status_bar_set("已取消")
            return

        fund_codes = [f[0] for f in funds]
        fund_names = {f[0]: f[1] for f in funds}
        self._run_in_thread(self._do_batch_realtime, fund_codes, fund_names, total)

    def _do_batch_realtime(self, fund_codes, fund_names, total):
        """后台线程：批量获取全部 LOF 实时行情快照。"""
        self._post_status(f"共 {total} 只基金，开始获取实时行情...")

        try:
            snapshots = fetch_all_fund_snapshots(fund_codes)
        except Exception as e:
            self._post_status(f"获取快照出错: {e}")
            self._post_set_busy(False)
            return

        self._post_grid_clear_add([])
        self._post_grid_append_rows(len(snapshots))

        success_count = 0
        fail_count = 0

        for i, snap in enumerate(snapshots):
            progress = f"进度: {i + 1}/{total}  [{snap.get('fund_code', '')}]"
            self._post_progress(progress)

            code = snap.get("fund_code", fund_codes[i] if i < len(fund_codes) else "")
            name = snap.get("fund_name", fund_names.get(code, ""))

            row_data = {
                "fund_code": code,
                "fund_name": name,
                "intraday_price": f'{snap.get("intraday_price", 0):.4f}',
                "intraday_change": f'{snap.get("intraday_change_pct", 0):.2f}%',
                "est_nav": f'{snap.get("estimated_nav", 0):.4f}',
                "est_change": f'{snap.get("estimate_change_pct", 0):.2f}%',
                "t1_nav": "",
                "t_nav": "",
                "est_error_pct": "",
                "premium_pct": f'{snap.get("premium_pct", 0):.2f}',
                "signal": snap.get("signal", ""),
                "method": "",
                "status": "成功" if "error" not in snap else "数据不足",
            }
            self._post_append_row(i, row_data)

            if "error" not in snap:
                success_count += 1
            else:
                fail_count += 1

        self._post_progress("")
        self._post_status(
            f"完成! 成功: {success_count}, 失败: {fail_count}, 总计: {total}"
        )
        self._post_set_busy(False)

    # ---- Full batch (estimate_realtime + realtime, non-blocking) ----

    def on_calculate_all(self, event):
        """批量估值计算 (fund_estimator + 场内价格)。"""
        funds = self._fetch_all_funds_basic()
        if not funds:
            wx.MessageBox("数据库中无基金数据", "错误", wx.OK | wx.ICON_ERROR, self)
            return

        total = len(funds)
        dlg = wx.MessageDialog(
            self,
            f"将对 {total} 只基金进行批量估值计算，\n"
            "此过程较慢，请耐心等待。\n"
            "是否继续？",
            "确认批量计算",
            wx.YES_NO | wx.NO_DEFAULT | wx.ICON_QUESTION,
        )
        answer = dlg.ShowModal()
        dlg.Destroy()
        if answer != wx.ID_YES:
            self.status_bar_set("已取消")
            return

        self._run_in_thread(self._do_batch_calculate, total)

    def _do_batch_calculate(self, total):
        """后台线程：并行批量估值计算。"""
        from concurrent.futures import ThreadPoolExecutor, as_completed

        funds = self._fetch_all_funds_basic()
        self._post_status(f"共 {total} 只基金，开始批量计算...")

        self._post_grid_clear_add([])
        self._post_grid_append_rows(total)

        today = datetime.now().strftime("%Y-%m-%d")

        # 每只基金的结果存到预分配的位置，保证顺序正确
        results = [None] * total

        def _calc_one(idx, fund_code, fund_name):
            """单只基金：内部函数（用于 submit）。

            路由：
              - 债券型基金（BOND_MAP 命中 / 名称含债基关键词） → v_bond_sse_gov
              - 商品 / 商品期货基金（COMMODITY_MAP 命中） → v_futures
              - 其它 → estimate_realtime（被动指数 / 主动基金）
            """
            try:
                # 1) 获取场内 + 估算快照
                snapshot = fetch_fund_snapshot(fund_code)

                # 2) 根据基金类型选择估值入口
                is_bond = _is_bond_fund(fund_code, fund_name)
                is_commodity = _is_commodity_fund(fund_code, fund_name)
                if is_bond:
                    est_result = _route_bond_estimate(
                        fund_code, fund_name, today, method="v_bond_sse_gov",
                    )
                elif is_commodity:
                    est_result = _route_commodity_estimate(
                        fund_code, fund_name, today, method="v_futures",
                    )
                else:
                    est_result = estimate_realtime(fund_code, today)

                t1_nav = ""
                est_method = ""
                t_nav = ""
                est_error_pct = ""
                if est_result.get("success"):
                    t1_nav = f"{est_result.get('t1_nav', 0):.4f}"
                    if is_bond:
                        primary_idx = est_result.get("primary_index", {}) or {}
                        idx_name = primary_idx.get("name", "上证国债指数")
                        est_method = (
                            f"v_bond_sse_gov[{idx_name}]"
                        )
                        snapshot["estimated_nav"] = est_result.get(
                            "estimated_nav", snapshot.get("estimated_nav", 0),
                        )
                        snapshot["estimate_change_pct"] = est_result.get(
                            "estimated_change_pct",
                            snapshot.get("estimate_change_pct", 0),
                        )
                    elif is_commodity:
                        est_method = (
                            f"v_futures[{est_result.get('commodity', '商品')}]"
                        )
                        # 用 v_futures 结果覆盖 snapshot
                        snapshot["estimated_nav"] = est_result.get(
                            "estimated_nav", snapshot.get("estimated_nav", 0),
                        )
                        snapshot["estimate_change_pct"] = est_result.get(
                            "estimated_change_pct",
                            snapshot.get("estimate_change_pct", 0),
                        )
                    else:
                        est_method = est_result.get("method_used") or est_result.get("method", "")
                    # 提取 T 日官方净值 + 估值偏离（适用于所有 3 类基金）
                    t_nav, est_error_pct = _format_official_nav(est_result)
                    return {
                        "index": idx,
                        "row_data": {
                            "fund_code": fund_code,
                            "fund_name": fund_name,
                            "intraday_price": f'{snapshot.get("intraday_price", 0):.4f}',
                            "intraday_change": f'{snapshot.get("intraday_change_pct", 0):.2f}%',
                            "est_nav": f'{snapshot.get("estimated_nav", 0):.4f}',
                            "est_change": f'{snapshot.get("estimate_change_pct", 0):.2f}%',
                            "t1_nav": t1_nav,
                            "t_nav": t_nav,
                            "est_error_pct": est_error_pct,
                            "premium_pct": f'{snapshot.get("premium_pct", 0):.2f}',
                            "signal": snapshot.get("signal", ""),
                            "method": est_method,
                            "status": "成功",
                        },
                        "success": True,
                    }
                else:
                    return {
                        "index": idx,
                        "row_data": {
                            "fund_code": fund_code,
                            "fund_name": fund_name,
                            "intraday_price": f'{snapshot.get("intraday_price", 0):.4f}',
                            "intraday_change": f'{snapshot.get("intraday_change_pct", 0):.2f}%',
                            "est_nav": f'{snapshot.get("estimated_nav", 0):.4f}',
                            "est_change": f'{snapshot.get("estimate_change_pct", 0):.2f}%',
                            "t1_nav": "",
                            "t_nav": "",
                            "est_error_pct": "",
                            "premium_pct": f'{snapshot.get("premium_pct", 0):.2f}',
                            "signal": snapshot.get("signal", ""),
                            "method": "",
                            "status": "获取失败",
                        },
                        "success": False,
                    }
            except Exception as e:
                return {
                    "index": idx,
                    "row_data": {
                        "fund_code": fund_code,
                        "fund_name": fund_name,
                        "t1_nav": "",
                        "method": "",
                        "status": f"异常: {str(e)[:8]}",
                    },
                    "success": False,
                }

        # 提交任务 + 并行执行，限制并发数避免 API 限频
        max_workers = min(15, total)
        submitted_count = 0
        success_count = 0
        fail_count = 0

        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            futures = []
            for i, (fund_code, fund_name) in enumerate(funds):
                futures.append(executor.submit(_calc_one, i, fund_code, fund_name))

            for future in as_completed(futures):
                result = future.result()
                idx = result["index"]
                results[idx] = result
                submitted_count += 1

                if result.get("success"):
                    success_count += 1
                else:
                    fail_count += 1

                current_code = funds[idx][0]
                self._post_progress(f"进度: {submitted_count}/{total}  [{current_code}]")

                # 将结果写回对应行（按 index 写入固定位置）
                self._post_append_row(idx, result["row_data"])

        self._post_progress("")
        self._post_status(
            f"计算完成! 成功: {success_count}, 失败: {fail_count}, 总计: {total}"
        )
        self._post_set_busy(False)

    # ---- DB Helpers ----

    def _fetch_all_funds_basic(self):
        """返回 [(fund_code, fund_name), ...]"""
        conn = sqlite3.connect(_DB_PATH)
        cursor = conn.cursor()
        cursor.execute("SELECT fund_code, fund_name FROM active_lofs ORDER BY fund_code")
        rows = cursor.fetchall()
        conn.close()
        return rows

    # ---- Export CSV (non-blocking) ----

    def on_export_csv(self, event):
        """将当前表格内容导出为 CSV 文件。"""
        if self.grid.GetNumberRows() == 0:
            wx.MessageBox("表格没有数据可导出", "提示", wx.OK | wx.ICON_INFORMATION, self)
            return

        save_dlg = wx.FileDialog(
            self,
            message="保存CSV文件",
            defaultDir=os.path.join(_SCRIPT_DIR, 'exports'),
            defaultFile=f"fund_snapshot_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv",
            wildcard="CSV 文件 (*.csv)|*.csv",
            style=wx.FD_SAVE | wx.FD_OVERWRITE_PROMPT,
        )
        if save_dlg.ShowModal() != wx.ID_OK:
            save_dlg.Destroy()
            return

        filepath = save_dlg.GetPath()
        save_dlg.Destroy()

        self._run_in_thread(self._do_export_csv, filepath)

    def _do_export_csv(self, filepath):
        """后台线程：导出 CSV 文件。"""
        try:
            with open(filepath, 'w', newline='', encoding='utf-8-sig') as f:
                writer = csv.writer(f)
                # 表头
                headers = [col[1] for col in FundGrid.COLUMNS]
                writer.writerow(headers)
                # 行数据
                for row in range(self.grid.GetNumberRows()):
                    values = []
                    for col in range(self.grid.GetNumberCols()):
                        values.append(self.grid.GetCellValue(row, col))
                    writer.writerow(values)

            self._post_status(f"导出成功: {filepath}")
            wx.MessageBox(
                f"导出成功!\n已保存到:\n{filepath}",
                "导出完成",
                wx.OK | wx.ICON_INFORMATION,
                self,
            )
        except Exception as e:
            wx.MessageBox(f"导出失败: {str(e)}", "错误", wx.OK | wx.ICON_ERROR, self)

    def on_refresh(self, event):
        """F5 快捷刷新: 获取全部实时行情。"""
        self.on_realtime_only(event)


# ====================================================================
# App Entry
# ====================================================================

class FundValuationApp(wx.App):
    def OnInit(self):
        frame = MainFrame()
        frame.Show(True)
        return True


if __name__ == "__main__":
    app = FundValuationApp(False)
    app.MainLoop()
