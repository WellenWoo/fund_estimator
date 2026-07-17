# -*- coding: utf-8 -*-
"""
Fund Real-time Valuation GUI
Uses wxPython to display real-time fund valuations.
"""

import sys
import os
import sqlite3
import wx
import wx.grid
from datetime import datetime

# --- Path setup: make fund_estimator_index_agent importable ---
_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
_PROJECT_CODE = os.path.join(_SCRIPT_DIR, '..', 'code', 'fund_estimator')
if _PROJECT_CODE not in sys.path:
    sys.path.insert(0, _PROJECT_CODE)

from fund_estimator_index_agent import estimate_realtime, classify_fund_type

# --- Database path ---
_DB_PATH = os.path.join(_SCRIPT_DIR, '..', 'lof_database', 'lof_master.db')


class FundGrid(wx.grid.Grid):
    """Custom wx.Grid with column labels for fund valuation display."""

    COLUMNS = [
        ("fund_code", "基金代码", 90),
        ("fund_name", "基金名称", 220),
        ("est_nav", "估算净值", 100),
        ("est_change", "估算涨幅(%)", 110),
        ("t1_nav", "T-1净值", 90),
        ("method", "估算方法", 160),
        ("status", "状态", 80),
    ]

    def __init__(self, parent):
        super().__init__(parent)
        n_cols = len(self.COLUMNS)
        self.CreateGrid(0, n_cols)

        for idx, (key, label, width) in enumerate(self.COLUMNS):
            self.SetColLabelValue(idx, label)
            self.SetColMinimalWidth(idx, width)
            self.AutoSizeColumn(idx, False)

        self.EnableEditing(False)
        self.SetRowLabelSize(0)  # hide row labels

    def append_row(self, row_idx, data_dict):
        """Append a single row of data. data_dict keys match COLUMNS keys."""
        for idx, (key, _, _) in enumerate(self.COLUMNS):
            val = str(data_dict.get(key, ""))
            self.SetCellValue(row_idx, idx, val)

    def clear_and_add(self, rows_data):
        """Clear grid and add a list of row dicts."""
        self.ClearGrid()
        if rows_data:
            self.AppendRows(len(rows_data))
            for i, row_data in enumerate(rows_data):
                self.append_row(i, row_data)


class MainFrame(wx.Frame):
    """Main application window."""

    def __init__(self, parent=None):
        super().__init__(
            parent,
            title="基金实时估值系统",
            size=(1100, 700),
        )

        # --- Status bar ---
        self.CreateStatusBar(2)
        self.SetStatusText("就绪", 1)

        # --- Panel & Sizer ---
        panel = wx.Panel(self)
        main_sizer = wx.BoxSizer(wx.VERTICAL)

        # ===== TOOLBAR AREA =====
        toolbar_panel = wx.Panel(panel)
        tb_sizer = wx.BoxSizer(wx.HORIZONTAL)

        # Label
        lbl = wx.StaticText(toolbar_panel, label="基金代码/名称:")
        tb_sizer.Add(lbl, 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 5)

        # Input
        self.input_ctrl = wx.TextCtrl(
            toolbar_panel,
            size=(200, -1),
            style=wx.TE_PROCESS_ENTER,
        )
        self.input_ctrl.Bind(wx.EVT_TEXT_ENTER, self.on_calculate)
        tb_sizer.Add(self.input_ctrl, 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 5)

        # Calculate button
        btn_calc = wx.Button(toolbar_panel, label="计 算")
        btn_calc.Bind(wx.EVT_BUTTON, self.on_calculate)
        tb_sizer.Add(btn_calc, 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 5)

        # Calculate All button
        btn_calc_all = wx.Button(toolbar_panel, label="计算全部")
        btn_calc_all.Bind(wx.EVT_BUTTON, self.on_calculate_all)
        tb_sizer.Add(btn_calc_all, 0, wx.ALIGN_CENTER_VERTICAL)

        toolbar_panel.SetSizer(tb_sizer)
        main_sizer.Add(toolbar_panel, 0, wx.EXPAND | wx.ALL, 5)

        # ===== GRID =====
        self.grid = FundGrid(panel)
        main_sizer.Add(self.grid, 1, wx.EXPAND | wx.ALL | wx.CENTER, 5)

        # ===== BOTTOM STATUS LINE =====
        bottom_panel = wx.Panel(panel)
        bottom_sizer = wx.BoxSizer(wx.HORIZONTAL)
        self.progress_label = wx.StaticText(
            bottom_panel,
            label="",
            style=wx.ST_ELLIPSIZE_MIDDLE,
        )
        bottom_sizer.Add(self.progress_label, 1, wx.ALIGN_CENTER_VERTICAL | wx.ALL, 3)
        bottom_panel.SetSizer(bottom_sizer)
        main_sizer.Add(bottom_panel, 0, wx.EXPAND)

        panel.SetSizer(main_sizer)

        # ===== MENU BAR =====
        menubar = wx.MenuBar()

        file_menu = wx.Menu()
        refresh_item = file_menu.Append(wx.ID_REFRESH, "刷新(&R)\tF5", "重新加载表格数据")
        exit_item = file_menu.Append(wx.ID_EXIT, "退出(&X)")
        menubar.Append(file_menu, "文件(&F)")
        self.Bind(wx.EVT_MENU, self.on_refresh, refresh_item)
        self.Bind(wx.EVT_MENU, self.on_exit, exit_item)

        help_menu = wx.Menu()
        about_item = help_menu.Append(wx.ID_ABOUT, "关于(&A)")
        menubar.Append(help_menu, "帮助(&H)")
        self.Bind(wx.EVT_MENU, self.on_about, about_item)

        self.SetMenuBar(menubar)

        # Bind keyboard shortcut
        self.Bind(wx.EVT_KEY_DOWN, self.on_key_down)

    # ---- Event Handlers ----

    def on_key_down(self, event):
        if event.GetKeyCode() == wx.WXK_F5:
            self.on_refresh(event)
        else:
            event.Skip()

    def on_exit(self, event):
        self.Close(True)

    def on_refresh(self, event):
        """Reload the grid with all funds from DB (basic info only)."""
        self.status_bar_set("正在加载...")
        wx.Yield()
        funds = self._fetch_all_funds()
        if not funds:
            self.status_bar_set("数据库中无基金数据")
            return
        self.grid.clear_and_add(funds)
        self.status_bar_set(f"已加载 {len(funds)} 只基金基本信息")

    def on_about(self, event):
        wx.MessageBox(
            "基金实时估值系统 v1.1\n"
            "基于 fund_estimator_index_agent\n"
            "数据来源: 天天基金 / 东方财富 / 新浪财经实时行情\n"
            "估值日期: {}".format(datetime.now().strftime("%Y-%m-%d")),
            "关于",
            wx.OK | wx.ICON_INFORMATION,
            self,
        )

    def status_bar_set(self, msg):
        self.SetStatusText(msg, 0)
        self.SetStatusText(msg, 1)

    def progress_set(self, msg):
        self.progress_label.SetLabel(msg)
        wx.Yield()

    # ---- Fund Lookup ----

    def find_fund_code(self, query):
        """
        Return (fund_code, fund_name) tuple, or None.
        If query is 6-digit number, treat as code directly.
        Otherwise search by name/pinyin/full_name in DB.
        """
        query = query.strip()
        if not query:
            return None

        conn = sqlite3.connect(_DB_PATH)
        cursor = conn.cursor()

        # Try exact code match first
        if len(query) == 6 and query.isdigit():
            cursor.execute(
                "SELECT fund_code, fund_name FROM master_lof WHERE fund_code = ?",
                (query,),
            )
            row = cursor.fetchone()
            conn.close()
            if row:
                return row
            return None

        # Search by name, full_name, pinyin (partial match)
        cursor.execute(
            "SELECT fund_code, fund_name FROM master_lof "
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

        # Multiple matches: show dialog
        choices = [f"{code}  {name}" for code, name in rows]
        dlg = wx.SingleChoiceDialog(
            self,
            f"找到 {len(rows)} 只匹配基金，请选择：",
            "选择基金",
            choices,
        )
        if dlg.ShowModal() == wx.ID_OK:
            sel = dlg.GetStringSelection()
            code = sel.split()[0]
            name = sel.split(" ", 1)[1] if " " in sel else ""
            return (code, name)
        return None

    # ---- Calculation ----

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

        fund_code, fund_name = result
        self.status_bar_set(f"正在计算 {fund_code} {fund_name} ...")
        wx.Yield()

        today = datetime.now().strftime("%Y-%m-%d")
        try:
            est_result = estimate_realtime(fund_code, today)
        except Exception as e:
            wx.MessageBox(f"计算出错: {e}", "错误", wx.OK | wx.ICON_ERROR, self)
            self.status_bar_set("计算出错")
            return

        # Build row data
        row_data = {
            "fund_code": fund_code,
            "fund_name": fund_name,
            "est_nav": "",
            "est_change": "",
            "t1_nav": "",
            "method": "",
            "status": "",
        }

        if est_result.get("success"):
            row_data["est_nav"] = f"{est_result.get('estimated_nav', 0):.4f}"
            row_data["est_change"] = f"{est_result.get('estimated_change_pct', 0):.2f}%"
            row_data["t1_nav"] = f"{est_result.get('t1_nav', 0):.4f}"
            method = est_result.get("method_used") or est_result.get("method", "")
            row_data["method"] = method
            row_data["status"] = "成功"
            self.status_bar_set(
                f"{fund_code} {fund_name} 估算净值: {row_data['est_nav']}  涨幅: {row_data['est_change']}"
            )
        else:
            err_msg = est_result.get("error", "未知错误")
            row_data["status"] = f"失败: {err_msg[:20]}"
            self.status_bar_set(f"计算失败: {err_msg}")

        # Refresh grid
        self.grid.clear_and_add([row_data])

    def on_calculate_all(self, event):
        self.status_bar_set("正在获取基金列表...")
        wx.Yield()

        funds = self._fetch_all_funds_basic()
        if not funds:
            wx.MessageBox("数据库中无基金数据", "错误", wx.OK | wx.ICON_ERROR, self)
            self.status_bar_set("无数据")
            return

        total = len(funds)
        self.status_bar_set(f"共 {total} 只基金，开始批量计算...")
        wx.MessageBox(
            f"将对 {total} 只基金进行批量估值计算，\n"
            "此过程可能需要较长时间，请耐心等待。\n"
            "是否继续？",
            "确认批量计算",
            wx.YES_NO | wx.ICON_QUESTION,
            self,
        )
        if not self.IsYes():
            self.status_bar_set("已取消")
            return

        self.grid.clear_and_add([])
        self.grid.AppendRows(total)

        today = datetime.now().strftime("%Y-%m-%d")
        success_count = 0
        fail_count = 0

        for i, (fund_code, fund_name) in enumerate(funds):
            self.progress_set(f"进度: {i + 1}/{total}  [{fund_code}]")

            try:
                est_result = estimate_realtime(fund_code, today)
                row_data = {
                    "fund_code": fund_code,
                    "fund_name": fund_name,
                    "est_nav": "",
                    "est_change": "",
                    "t1_nav": "",
                    "method": "",
                    "status": "",
                }

                if est_result.get("success"):
                    row_data["est_nav"] = f"{est_result.get('estimated_nav', 0):.4f}"
                    row_data["est_change"] = f"{est_result.get('estimated_change_pct', 0):.2f}%"
                    row_data["t1_nav"] = f"{est_result.get('t1_nav', 0):.4f}"
                    method = est_result.get("method_used") or est_result.get("method", "")
                    row_data["method"] = method
                    row_data["status"] = "成功"
                    success_count += 1
                else:
                    err_msg = est_result.get("error", "未知错误")
                    row_data["status"] = f"失败: {err_msg[:15]}"
                    fail_count += 1

                self.grid.append_row(i, row_data)

            except Exception as e:
                row_data = {
                    "fund_code": fund_code,
                    "fund_name": fund_name,
                    "status": f"异常: {str(e)[:10]}",
                }
                self.grid.append_row(i, row_data)
                fail_count += 1

        self.progress_set("")
        self.status_bar_set(
            f"计算完成! 成功: {success_count}, 失败: {fail_count}, 总计: {total}"
        )

    # ---- DB Helpers ----

    def _fetch_all_funds_basic(self):
        """Return list of (fund_code, fund_name) from master_lof."""
        conn = sqlite3.connect(_DB_PATH)
        cursor = conn.cursor()
        cursor.execute("SELECT fund_code, fund_name FROM master_lof ORDER BY fund_code")
        rows = cursor.fetchall()
        conn.close()
        return rows

    def _fetch_all_funds(self):
        """Return list of dicts with basic info for grid display (no estimation)."""
        conn = sqlite3.connect(_DB_PATH)
        cursor = conn.cursor()
        cursor.execute(
            "SELECT fund_code, fund_name, fund_type, is_index_fund, tracker_index "
            "FROM master_lof ORDER BY fund_code"
        )
        rows = cursor.fetchall()
        conn.close()

        result = []
        for code, name, ftype, is_idx, tracker in rows:
            result.append({
                "fund_code": code,
                "fund_name": name,
                "est_nav": "",
                "est_change": "",
                "t1_nav": "",
                "method": f"{ftype}{'(指数)' if is_idx else ''}" + (f"→{tracker}" if tracker else ""),
                "status": "基本信息",
            })
        return result


class FundValuationApp(wx.App):
    def OnInit(self):
        frame = MainFrame()
        frame.Show(True)
        return True


if __name__ == "__main__":
    app = FundValuationApp(False)
    app.MainLoop()
