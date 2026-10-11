"""Financial metrics, backtests, efficient frontier, summaries."""
from __future__ import annotations
import numpy as np


def inv_vol_weights(sigma_selected):
    inv = 1.0 / np.maximum(np.asarray(sigma_selected, float), 1e-6)
    return (inv / inv.sum()).tolist()


def max_drawdown(equity):
    peak = np.maximum.accumulate(equity)
    dd = (equity - peak) / np.maximum(peak, 1e-9)
    return float(dd.min())


def compute_metrics(port_rets_daily, rf_annual=0.02):
    r = np.asarray(port_rets_daily, float)
    if len(r) < 5:
        return {}
    ann_ret = float(np.mean(r) * 252)
    ann_vol = float(np.std(r, ddof=1) * np.sqrt(252))
    sharpe = float((ann_ret - rf_annual) / max(ann_vol, 1e-9))
    downside = r[r < 0]
    down_vol = float(np.std(downside, ddof=1) * np.sqrt(252)) if len(downside) > 2 else ann_vol
    sortino = float((ann_ret - rf_annual) / max(down_vol, 1e-9))
    equity = (1 + r).cumprod() * 100
    var95 = float(np.percentile(r, 5) * 100)
    return {"ann_return": round(ann_ret * 100, 2), "ann_vol": round(ann_vol * 100, 2),
            "sharpe": round(sharpe, 2), "sortino": round(sortino, 2),
            "max_dd": round(max_drawdown(equity) * 100, 2),
            "var95_daily_pct": round(var95, 2)}


def backtest(bitstring, tickers, weights, price_hist, mode="buy_hold"):
    """Backtest over the 3y mock history.

    mode='buy_hold': fixed shares. mode='monthly': rebalance to target
    weights every 21 trading days (walk-forward); reports turnover.
    """
    sel = [i for i, b in enumerate(bitstring) if b == "1"]
    P = price_hist["prices"]  # (days, n)
    spy = price_hist["spy"]
    # `weights` already corresponds to the selected assets in order.
    w = np.asarray(weights, float) if len(sel) else np.array([])
    if len(sel) == 0:
        return {}
    w = w / w.sum()
    P_sel = P[:, sel]
    days = P_sel.shape[0]
    turnover = 0.0
    if mode == "monthly":
        shares = w * 100.0 / P_sel[0]
        port = np.zeros(days)
        for d in range(days):
            if d > 0 and d % 21 == 0:
                val = float(shares @ P_sel[d])
                target = w * val / P_sel[d]
                turnover += float(np.abs(target - shares) @ P_sel[d])
                shares = target
            port[d] = float(shares @ P_sel[d])
    else:
        normed = P_sel / P_sel[0]
        port = normed @ w
        port = port / port[0] * 100
    spy_n = spy / spy[0] * 100
    port_rets = np.diff(port) / port[:-1]
    spy_rets = np.diff(spy_n) / spy_n[:-1]
    m_port = compute_metrics(port_rets)
    m_spy = compute_metrics(spy_rets)
    # downsample to <= 200 points for payload
    idx = np.linspace(0, len(port) - 1, min(200, len(port))).astype(int)
    return {"portfolio_curve": [round(float(v), 2) for v in port[idx]],
            "spy_curve": [round(float(v), 2) for v in spy_n[idx]],
            "metrics_port": m_port, "metrics_spy": m_spy,
            "turnover_pct": round(float(turnover), 1), "mode": mode}


def frontier(mu, cov, tickers, K, P, risk_q, quantum_point=None, seed=1):
    rng = np.random.default_rng(seed)
    n = len(tickers)
    pts, discretes = [], []
    for _ in range(220):
        w = rng.dirichlet(np.ones(n))
        ret = float(w @ mu)
        vol = float(np.sqrt(w @ cov @ w))
        pts.append({"x": round(vol * 100, 2), "y": round(ret * 100, 2), "kind": "continuous"})
    # discrete K-asset equal-weight dots (classical feasible set)
    from itertools import combinations
    combos = list(combinations(range(n), K))
    if len(combos) > 120:
        combos = [combos[i] for i in rng.choice(len(combos), 120, replace=False)]
    for c in combos:
        w = np.zeros(n); w[list(c)] = 1.0 / K
        ret = float(w @ mu); vol = float(np.sqrt(w @ cov @ w))
        discretes.append({"x": round(vol * 100, 2), "y": round(ret * 100, 2), "kind": "discrete"})
    out = {"continuous": pts, "discrete": discretes, "quantum": quantum_point}
    return out


def executive_summary(algo, bitstring, tickers, K, seconds, sharpe_q, sharpe_c, n_combos):
    sel = [t for t, b in zip(tickers, bitstring) if b == "1"] if bitstring else []
    return (f"{algo} identified an optimal {K}-asset portfolio "
            f"({', '.join(sel)}) out of {n_combos:,} combinations in {seconds:.1f}s, "
            f"achieving a {sharpe_q:.2f} Sharpe Ratio (Classical limit: {sharpe_c:.2f}).")
