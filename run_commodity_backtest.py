"""完整回测脚本：在 161226 上跑所有 4 种可回测算法横向对比，并输出 JSON 结果。"""
import sys
import json
sys.path.insert(0, 'code')
from fund_estimator.fund_estimator_product import (
    load_common_inputs, backtest_all_methods, METHODS, METHOD_LABELS
)


def fmt_table_row(name, n, mae, rmse, mx, mean, over):
    return "{:<35} {:>5} {:>9.4f} {:>9.4f} {:>9.4f} {:>+9.4f} {:>10}".format(
        name, n, mae, rmse, mx, mean, over
    )


def main():
    inputs = load_common_inputs('161226')
    print(f'Fund: {inputs.commodity.fund_name} ({inputs.fund_code})')
    print(f'Commodity: {inputs.commodity.commodity} | Symbol: {inputs.commodity.symbol} | Beta: {inputs.commodity.beta}')
    print(f'Loaded {len(inputs.nav_rows)} days for {inputs.fund_code}')
    print(f'Trading days: {inputs.trading_days[0]} to {inputs.trading_days[-1]}')

    # 收集两个样本的 stats
    samples = {
        "full_11y": (inputs.trading_days[0], inputs.trading_days[-1]),
        "recent_60d": (inputs.trading_days[-61], inputs.trading_days[-1]),
        "2026_full_ytd": ("2026-01-01", inputs.trading_days[-1]),
    }
    out = {
        "fund": inputs.commodity.to_dict(),
        "samples": {},
    }

    for sample_name, (start, end) in samples.items():
        results = backtest_all_methods(inputs, start, end)
        per = []
        print()
        print(f'=== {sample_name}: {start} ~ {end} ===')
        header = "{:<35} {:>5} {:>9} {:>9} {:>9} {:>9} {:>10}".format(
            "Method", "N", "MAE", "RMSE", "MAX", "Mean", "OverTH"
        )
        print(header)
        print('-' * len(header) + '-' * 5)
        for m, r in results.items():
            s = r.stats()
            per.append(s)
            print(fmt_table_row(
                METHOD_LABELS[m], s["n"], s["mae_pp"], s["rmse_pp"],
                s["max_pp"], s["mean_pp"], s["over_ratio"]
            ))
        out["samples"][sample_name] = {
            "start": start, "end": end,
            "per_method": per,
        }

    # 保存 JSON
    with open('code/fund_estimator/fund_estimator_product/backtest_161226_result.json', 'w', encoding='utf-8') as f:
        json.dump(out, f, ensure_ascii=False, indent=2)
    print()
    print('Saved to code/fund_estimator/fund_estimator_product/backtest_161226_result.json')


if __name__ == "__main__":
    main()
