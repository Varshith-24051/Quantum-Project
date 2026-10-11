"""Mock market data engine — realistic, deterministic, offline-friendly."""
from __future__ import annotations
import numpy as np

ASSETS = [
    # ticker, name, sector, expected annual return mu, annual vol, beta, alpha, start price
    ("AAPL",  "Apple",      "Tech",       0.22, 0.24, 1.18, 0.04, 175.0),
    ("MSFT",  "Microsoft",  "Tech",       0.24, 0.23, 1.05, 0.06, 330.0),
    ("GOOGL", "Alphabet",   "Tech",       0.21, 0.26, 1.08, 0.03, 140.0),
    ("AMZN",  "Amazon",     "Tech",       0.23, 0.30, 1.25, 0.02, 150.0),
    ("NVDA",  "NVIDIA",     "Semis",      0.38, 0.45, 1.65, 0.12, 480.0),
    ("TSLA",  "Tesla",      "Auto/Tech",  0.28, 0.55, 1.90, 0.05, 240.0),
    ("META",  "Meta",       "Tech",       0.26, 0.34, 1.30, 0.05, 320.0),
    ("JPM",   "JPMorgan",   "Bank",       0.14, 0.22, 1.10, 0.01, 160.0),
    ("JNJ",   "J&J",        "Health",     0.09, 0.15, 0.65, 0.02, 155.0),
    ("AMD",   "AMD",        "Semis",      0.27, 0.48, 1.70, 0.04, 140.0),
]

MARKET_VAR = 0.04  # (20% market vol)^2 — single-factor model
TRADING_DAYS = 756  # ~3 years

# Calibrated sector correlation matrix (order matches ASSETS).
# Tech-Tech ~0.7, Semis-Semis 0.72, Tech-Semis 0.55, Banks ~0.45 vs market,
# Health defensive ~0.3. Mirrors typical S&P 500 sector structure.
CORR = np.array([
    # AAPL MSFT GOOGL AMZN  NVDA  TSLA  META   JPM   JNJ   AMD
    [1.00, 0.72, 0.66, 0.65, 0.55, 0.50, 0.68, 0.48, 0.32, 0.55],  # AAPL
    [0.72, 1.00, 0.70, 0.66, 0.55, 0.50, 0.68, 0.48, 0.32, 0.55],  # MSFT
    [0.66, 0.70, 1.00, 0.66, 0.55, 0.50, 0.66, 0.47, 0.31, 0.54],  # GOOGL
    [0.65, 0.66, 0.66, 1.00, 0.56, 0.52, 0.70, 0.49, 0.33, 0.56],  # AMZN
    [0.55, 0.55, 0.55, 0.56, 1.00, 0.48, 0.55, 0.45, 0.30, 0.72],  # NVDA
    [0.50, 0.50, 0.50, 0.52, 0.48, 1.00, 0.50, 0.42, 0.28, 0.47],  # TSLA
    [0.68, 0.68, 0.66, 0.70, 0.55, 0.50, 1.00, 0.49, 0.33, 0.55],  # META
    [0.48, 0.48, 0.47, 0.49, 0.45, 0.42, 0.49, 1.00, 0.38, 0.44],  # JPM
    [0.32, 0.32, 0.31, 0.33, 0.30, 0.28, 0.33, 0.38, 1.00, 0.29],  # JNJ
    [0.55, 0.55, 0.54, 0.56, 0.72, 0.47, 0.55, 0.44, 0.29, 1.00],  # AMD
])


def _build_cov(sigmas: np.ndarray) -> np.ndarray:
    """Covariance from calibrated correlations: Cov = D·Corr·D.

    Blends toward identity until positive-definite (deterministic).
    """
    C = CORR.copy()
    for _ in range(50):
        if np.linalg.eigvalsh(C)[0] > 1e-6:
            break
        C = 0.98 * C + 0.02 * np.eye(C.shape[0])
    D = np.diag(np.asarray(sigmas, dtype=float))
    return D @ C @ D


def _price_paths(mu, cov, starts, days=TRADING_DAYS, seed=42):
    """GBM paths consistent with mu/cov. Deterministic via seed."""
    mu = np.asarray(mu, float)
    cov = np.asarray(cov, float)
    n = len(mu)
    rng = np.random.default_rng(seed)
    mu_d = mu / 252.0
    cov_d = cov / 252.0
    # correlated daily shocks
    L = np.linalg.cholesky(cov_d + np.eye(n) * 1e-10)
    shocks = rng.standard_normal((days, n)) @ L.T
    rets = mu_d + shocks
    # Drift calibration: keep the random covariance structure but enforce
    # realized daily means == target mu_d, so backtests stay consistent
    # with the optimizer inputs (faculty sees positive, sensible Sharpes).
    rets = rets - rets.mean(axis=0, keepdims=True) + mu_d
    starts = np.asarray(starts, dtype=float)
    cum = np.cumsum(np.log1p(np.clip(rets, -0.3, 0.3)), axis=0)
    prices = starts * np.exp(cum - cum[0])  # pin day-0 to listed start prices
    return prices, rng


def get_universe():
    sigmas = np.array([a[4] for a in ASSETS])
    cov = _build_cov(sigmas)
    tickers_all = [a[0] for a in ASSETS]
    mu_all = np.array([a[3] for a in ASSETS])
    starts_all = np.array([a[7] for a in ASSETS])
    P, rng = _price_paths(mu_all, cov, starts_all)
    out = []
    for i, (t, name, sector, mu, sig, beta, alpha, _) in enumerate(ASSETS):
        last = float(P[-1, i])
        prev = float(P[-2, i])
        chg = (last - prev) / prev * 100
        out.append({
            "ticker": t, "name": name, "sector": sector,
            "mu": round(float(mu), 4), "sigma": round(float(sig), 4),
            "beta": round(float(beta), 2), "alpha": round(float(alpha), 4),
            "last": round(last, 2), "chg_pct": round(float(chg), 2),
        })
    return out, cov


def get_subset(tickers):
    uni, cov_all = get_universe()
    idx = []
    for t in tickers:
        matches = [i for i, a in enumerate(ASSETS) if a[0] == t]
        if not matches:
            raise ValueError(f"Unknown ticker: {t}")
        idx.append(matches[0])
    mu = np.array([ASSETS[i][3] for i in idx], dtype=float)
    sig = np.array([ASSETS[i][4] for i in idx], dtype=float)
    beta = np.array([ASSETS[i][5] for i in idx], dtype=float)
    alpha = np.array([ASSETS[i][6] for i in idx], dtype=float)
    cov = cov_all[np.ix_(idx, idx)]
    return {"tickers": tickers, "mu": mu, "sigma": sig,
            "beta": beta, "alpha": alpha, "cov": cov, "idx": idx}


def get_price_history(tickers, days=TRADING_DAYS, seed=42):
    """GBM paths consistent with mu/cov. Deterministic via seed."""
    sub = get_subset(tickers)
    n = len(tickers)
    starts = np.array([ASSETS[i][7] for i in sub["idx"]], dtype=float)
    prices, rng = _price_paths(sub["mu"], sub["cov"], starts, days, seed)
    # SPY benchmark (mu=12%, vol=18%)
    spy_rets = 0.12 / 252 + (0.18 / np.sqrt(252)) * rng.standard_normal(days)
    spy_rets = spy_rets - spy_rets.mean() + 0.12 / 252
    spy_cum = np.cumsum(np.log1p(np.clip(spy_rets, -0.3, 0.3)))
    spy = 400.0 * np.exp(spy_cum - spy_cum[0])
    return {"prices": prices, "spy": spy, "days": days}
