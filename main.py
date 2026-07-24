#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
LOF基金折价/溢价套利分析工具
============================

用法：
    python main.py                      # 使用默认配置（config/config.yaml）
    python main.py -c my_config.yaml    # 指定配置文件
    python main.py 501098 160119        # 直接指定基金代码
    python main.py --format text        # 指定输出格式
    python main.py --monitor            # 持续监控模式
"""

import os
import sys
import time
import argparse
from datetime import datetime

# 确保可以导入 lof_arbitrage 包
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from lof_arbitrage.core import run_analysis, FundAnalyzer
from lof_arbitrage.report import (
    generate_text_report,
    generate_json_report,
    generate_simple_html_report,
    save_report,
)


def load_config(config_path: str) -> dict:
    """加载配置文件"""
    config = {}

    if not os.path.exists(config_path):
        print(f"⚠️  配置文件不存在：{config_path}，使用默认配置")
        return _default_config()

    # 尝试使用 yaml
    try:
        import yaml
        with open(config_path, "r", encoding="utf-8") as f:
            config = yaml.safe_load(f) or {}
    except ImportError:
        # 如果没有 pyyaml，尝试简单解析（仅支持最基础的key: value）
        print("ℹ️  未安装 PyYAML，将使用简单配置解析（建议：pip install pyyaml）")
        config = _simple_yaml_parse(config_path)
    except Exception as e:
        print(f"⚠️  配置文件解析失败：{e}，使用默认配置")
        return _default_config()

    return config


def _simple_yaml_parse(path: str) -> dict:
    """简单的YAML解析（仅支持两层缩进的key: value）"""
    config = {}
    current_section = None
    current_sub = None

    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.rstrip()
            # 跳过空行和注释
            if not line or line.strip().startswith("#"):
                continue
            # 顶层（无缩进）
            if not line.startswith(" "):
                if ":" in line:
                    key = line.split(":")[0].strip()
                    current_section = key
                    config[key] = {}
                    current_sub = None
            # 二层（2空格缩进）
            elif line.startswith("  ") and not line.startswith("    "):
                stripped = line.strip()
                if ":" in stripped:
                    key, val = stripped.split(":", 1)
                    key = key.strip()
                    val = val.strip()
                    # 列表项
                    if val.startswith("- "):
                        val = [val[2:].strip()]
                    # 类型转换
                    val = _auto_convert(val)
                    if current_section:
                        config[current_section][key] = val
                        current_sub = key
            # 三层（4空格缩进）- 列表项
            elif line.startswith("    - "):
                item = line.strip()[2:].strip()  # 去掉 "- "
                if current_section and current_sub:
                    if not isinstance(config[current_section].get(current_sub), list):
                        config[current_section][current_sub] = []
                    if ":" in item:
                        # dict 项
                        d = {}
                        k, v = item.split(":", 1)
                        d[k.strip()] = _auto_convert(v.strip())
                        config[current_section][current_sub].append(d)
                    else:
                        config[current_section][current_sub].append(item)

    return config


def _auto_convert(val: str):
    """自动类型转换"""
    if val.lower() in ("true", "yes"):
        return True
    if val.lower() in ("false", "no"):
        return False
    if val == "":
        return ""
    # 整数
    try:
        return int(val)
    except ValueError:
        pass
    # 浮点数
    try:
        return float(val)
    except ValueError:
        pass
    # 去掉引号
    if val.startswith('"') and val.endswith('"'):
        return val[1:-1]
    if val.startswith("'") and val.endswith("'"):
        return val[1:-1]
    return val


def _default_config() -> dict:
    """默认配置"""
    return {
        "funds": [
            {"code": "501098", "name": "建信优享科技创新混合(LOF)", "type": "auto"},
            {"code": "160119", "name": "南方中证500ETF联接(LOF)A", "type": "auto"},
        ],
        "arbitrage": {
            "premium_threshold": 1.5,
            "discount_threshold": 1.5,
            "fee_multiplier": 1.2,
        },
        "output": {
            "dir": "./output",
            "format": "all",
            "print_to_console": True,
            "filename_prefix": "lof_arbitrage",
        },
        "data": {
            "timeout": 10,
            "request_interval": 0.5,
            "fetch_holdings_quotes": True,
        },
        "monitor": {
            "enabled": False,
            "interval": 60,
            "only_signal": True,
        },
    }


def extract_fund_codes(config: dict) -> list:
    """从配置中提取基金代码列表"""
    funds = config.get("funds", [])
    codes = []
    for f in funds:
        if isinstance(f, str):
            codes.append(f)
        elif isinstance(f, dict):
            code = f.get("code", "")
            if code:
                codes.append(code)
    return codes


def build_config_dict(config: dict) -> dict:
    """构建分析配置字典"""
    arb = config.get("arbitrage", {})
    return {
        "premium_threshold": arb.get("premium_threshold", 1.5),
        "discount_threshold": -abs(arb.get("discount_threshold", 1.5)),
        "fee_multiplier": arb.get("fee_multiplier", 1.2),
    }


def progress_callback(current: int, total: int, fund_code: str):
    """进度回调"""
    print(f"[{current}/{total}] 正在分析 {fund_code} ...", flush=True)


def run_once(config: dict, output_format: str = None) -> dict:
    """运行一次分析"""
    codes = extract_fund_codes(config)
    analysis_config = build_config_dict(config)

    if not codes:
        print("❌ 未配置任何基金代码")
        return {}

    print(f"🚀 开始分析 {len(codes)} 只LOF基金...")
    print()

    result = run_analysis(codes, analysis_config, progress_callback=progress_callback)

    print()
    print("✅ 分析完成！")
    print()

    # 输出
    output_cfg = config.get("output", {})
    fmt = output_format or output_cfg.get("format", "text")
    output_dir = output_cfg.get("dir", "./output")
    print_console = output_cfg.get("print_to_console", True)
    prefix = output_cfg.get("filename_prefix", "lof_arbitrage")

    os.makedirs(output_dir, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")

    saved_files = []

    if fmt == "all" or fmt == "text":
        path = os.path.join(output_dir, f"{prefix}_{timestamp}.txt")
        save_report(result, path, "text")
        saved_files.append(path)

    if fmt == "all" or fmt == "json":
        path = os.path.join(output_dir, f"{prefix}_{timestamp}.json")
        save_report(result, path, "json")
        saved_files.append(path)

    if fmt == "all" or fmt == "html":
        path = os.path.join(output_dir, f"{prefix}_{timestamp}.html")
        save_report(result, path, "html")
        saved_files.append(path)

    # 控制台输出
    if print_console and fmt != "json":
        print(generate_text_report(result))

    if saved_files:
        print(f"📄 报告已保存到：")
        for f in saved_files:
            print(f"   - {os.path.abspath(f)}")

    return result


def run_monitor(config: dict):
    """持续监控模式"""
    monitor_cfg = config.get("monitor", {})
    interval = monitor_cfg.get("interval", 60)
    only_signal = monitor_cfg.get("only_signal", True)

    print(f"📡 进入持续监控模式，间隔 {interval} 秒")
    print(f"   按 Ctrl+C 退出")
    print()

    count = 0
    try:
        while True:
            count += 1
            now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            print(f"━━━ 第 {count} 轮监控 [{now}] ━━━")

            result = run_once(config, output_format="text")

            summary = result.get("summary", {})
            opportunities = summary.get("arbitrage_opportunities", 0)

            if only_signal and opportunities == 0:
                print("   无套利机会，继续监控...")
            elif opportunities > 0:
                print(f"   ⚠️  发现 {opportunities} 个套利机会！")
                buy = summary.get("buy_arbitrage_signals", [])
                sell = summary.get("sell_arbitrage_signals", [])
                if buy:
                    print(f"   折价套利：{', '.join(buy)}")
                if sell:
                    print(f"   溢价套利：{', '.join(sell)}")

            print()
            time.sleep(interval)

    except KeyboardInterrupt:
        print()
        print("👋 监控已停止")


def main():
    parser = argparse.ArgumentParser(
        description="LOF基金折价/溢价套利分析工具",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例：
  python main.py                      # 使用默认配置
  python main.py -c config.yaml       # 指定配置文件
  python main.py 501098 160119        # 分析指定基金
  python main.py --format html        # 输出HTML格式报告
  python main.py --monitor            # 持续监控模式
        """,
    )
    parser.add_argument("fund_codes", nargs="*", help="基金代码（可多个）")
    parser.add_argument("-c", "--config", default=None, help="配置文件路径")
    parser.add_argument("-f", "--format", default=None,
                        choices=["text", "json", "html", "all"],
                        help="输出格式")
    parser.add_argument("--monitor", action="store_true", help="持续监控模式")
    parser.add_argument("--interval", type=int, default=None, help="监控间隔（秒）")
    parser.add_argument("-o", "--output", default=None, help="输出目录")

    args = parser.parse_args()

    # 确定配置文件路径
    if args.config:
        config_path = args.config
    else:
        script_dir = os.path.dirname(os.path.abspath(__file__))
        config_path = os.path.join(script_dir, "config", "config.yaml")

    # 加载配置
    config = load_config(config_path)

    # 命令行参数覆盖配置
    if args.fund_codes:
        config["funds"] = [{"code": c, "type": "auto"} for c in args.fund_codes]

    if args.format:
        config.setdefault("output", {})["format"] = args.format

    if args.output:
        config.setdefault("output", {})["dir"] = args.output

    if args.interval:
        config.setdefault("monitor", {})["interval"] = args.interval

    if args.monitor:
        config.setdefault("monitor", {})["enabled"] = True

    # 运行
    if config.get("monitor", {}).get("enabled", False):
        run_monitor(config)
    else:
        run_once(config, args.format)


if __name__ == "__main__":
    main()
