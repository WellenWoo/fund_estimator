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

# --- Database path ---
_DB_PATH = os.path.join(_SCRIPT_DIR, '..', 'lof_database', 'lof_info.db')


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
        ("premium_pct", "溢价率(%)", 90),
        ("signal", "套利信号", 150),
        ("status", "状态", 70),
    ]

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

    def _color_cell(self, row, col, value_str):
        """对溢价率列着色。"""
        if col == 6:  # premium_pct
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

    def append_row(self, row_idx, data_dict):
        """写入一行数据。"""
        for idx, (key, _, _) in enumerate(self.COLUMNS):
            val = str(data_dict.get(key, ""))
            self.SetCellValue(row_idx, idx, val)
            self._color_cell(row_idx, idx, val)

    def clear_and_add(self, rows_data):
        """清空并重绘表格。"""
        self.ClearGrid()
        if rows_data:
            self.AppendRows(len(rows_data))
            for i, row_data in enumerate(rows_data):
                self.append_row(i, row_data)


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
            "  溢价率 > +1% → 溢价卖出 (申购→转场内→卖出)\n"
            "  溢价率 < -1% → 折价买入 (买入→转场内→赎回)\n"
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
                "SELECT fund_code, fund_name FROM master_lof WHERE fund_code = ?",
                (query,),
            )
            row = cursor.fetchone()
            conn.close()
            if row:
                return row
            return None

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
        """后台线程：单只基金估值计算。"""
        fund_code, fund_name = result
        self._post_status(f"正在计算 {fund_code} {fund_name} ...")

        try:
            # 1) 获取场内实时价格 + 估算净值 + 溢价率
            snapshot = fetch_fund_snapshot(fund_code)

            # 2) 同时用 fund_estimator 计算 T-1 基准净值
            today = datetime.now().strftime("%Y-%m-%d")
            t1_nav = ""
            est_method = ""
            try:
                est_result = estimate_realtime(fund_code, today)
                if est_result.get("success"):
                    t1_nav = f"{est_result.get('t1_nav', 0):.4f}"
                    est_method = est_result.get("method_used") or est_result.get("method", "")
            except Exception:
                pass

            # 3) 构建行数据
            row_data = {
                "fund_code": fund_code,
                "fund_name": fund_name,
                "intraday_price": f'{snapshot.get("intraday_price", 0):.4f}',
                "intraday_change": f'{snapshot.get("intraday_change_pct", 0):.2f}%',
                "est_nav": f'{snapshot.get("estimated_nav", 0):.4f}',
                "est_change": f'{snapshot.get("estimate_change_pct", 0):.2f}%',
                "premium_pct": f'{snapshot.get("premium_pct", 0):.2f}',
                "signal": snapshot.get("signal", ""),
                "status": f"T-1:{t1_nav}" + (f" {est_method}" if est_method else ""),
            }

            final_snapshot = snapshot

            self._post_grid_clear_add([row_data])
            self._post_status(
                f"{fund_code} {fund_name} | 场内: {row_data['intraday_price']} | "
                f"估算: {row_data['est_nav']} | 溢价: {row_data['premium_pct']}% | "
                f"{final_snapshot.get('signal', '')}"
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
                "premium_pct": f'{snapshot.get("premium_pct", 0):.2f}',
                "signal": snapshot.get("signal", ""),
                "status": "实时",
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
                "premium_pct": f'{snap.get("premium_pct", 0):.2f}',
                "signal": snap.get("signal", ""),
                "status": "OK" if "error" not in snap else "数据不足",
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
            """单只基金：内部函数（用于 submit）。"""
            try:
                # 1) 获取场内 + 估算快照
                snapshot = fetch_fund_snapshot(fund_code)

                # 2) fund_estimator 估值
                est_result = estimate_realtime(fund_code, today)

                t1_nav = ""
                est_method = ""
                if est_result.get("success"):
                    t1_nav = f"{est_result.get('t1_nav', 0):.4f}"
                    est_method = est_result.get("method_used") or est_result.get("method", "")
                    return {
                        "index": idx,
                        "row_data": {
                            "fund_code": fund_code,
                            "fund_name": fund_name,
                            "intraday_price": f'{snapshot.get("intraday_price", 0):.4f}',
                            "intraday_change": f'{snapshot.get("intraday_change_pct", 0):.2f}%',
                            "est_nav": f'{snapshot.get("estimated_nav", 0):.4f}',
                            "est_change": f'{snapshot.get("estimate_change_pct", 0):.2f}%',
                            "premium_pct": f'{snapshot.get("premium_pct", 0):.2f}',
                            "signal": snapshot.get("signal", ""),
                            "status": f"T-1:{t1_nav}" + (f" {est_method}" if est_method else "失败"),
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
                            "premium_pct": f'{snapshot.get("premium_pct", 0):.2f}',
                            "signal": snapshot.get("signal", ""),
                            "status": "失败",
                        },
                        "success": False,
                    }
            except Exception as e:
                return {
                    "index": idx,
                    "row_data": {
                        "fund_code": fund_code,
                        "fund_name": fund_name,
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
        cursor.execute("SELECT fund_code, fund_name FROM master_lof ORDER BY fund_code")
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
