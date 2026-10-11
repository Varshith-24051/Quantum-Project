"""Live market data: Yahoo Finance fetch, Ledoit-Wolf shrinkage, CSV upload.

All network access is optional — every function degrades gracefully to None
so the terminal always falls back to the deterministic mock universe.
"""
from __future__ import annotations
import io
import time
import numpy as np

_CACHE = {}
_CACHE_TTL = 3600


def ledoit_wolf(X):
    """Ledoit-Wolf (2004) optimal shrinkage of the sample covariance.

    X: (T, N) returns. Returns (shrunk_cov, shrinkage_delta).
    shrunk = delta * mu*I + (1-delta) * S,  delta in [0, 1].
    """
    X = np.asarray(X, dtype=float)
    T_, N = X.shape
    m = X.mean(axis=0)
    Xc = X - m
    S = (Xc.T @ Xc) / T_
    mu = np.trace(S) / N
    # pi_hat: sum of asymptotic variances of entries of S
    pi_ = 0.0
    for t in range(T_):
        outer = Xc[t][:, None] @ Xc[t][None, :]
        pi_ += float(((outer - S) ** 2).sum())
    pi_ /= T_
    # rho_hat (diagonal exact, off-diagonal correlation-adjusted)
    rho = 0.0
    for i in range(N):
        col = Xc[:, i]
        rho += float((((col ** 2 - S[i, i]) ** 2).sum()) / T_)
    with np.errstate(divide="ignore", invalid="ignore"):
        std = np.sqrt(np.diag(S))
        corr = S / np.outer(std, std)
        corr = np.nan_to_num(corr)
    for i in range(N):
        for j in range(i + 1, N):
            if std[i] <= 0 or std[j] <= 0:
                continue
            th = float((((Xc[:, i] ** 2 - S[i, i]) * (Xc[:, j] ** 2 - S[j, j])).sum()) / T_)
            term = 0.5 * (np.sqrt(S[j, j] / S[i, i]) * th + np.sqrt(S[i, i] / S[j, j]) * th)
            rho += term * float(corr[i, j])
    gamma = float(((S - mu * np.eye(N)) ** 2).sum())
    kappa = (pi_ - rho) / gamma if gamma > 1e-16 else 0.0
    delta = float(max(0.0, min(kappa / T_, 1.0)))
    shrunk = delta * mu * np.eye(N) + (1 - delta) * S
    return shrunk, delta


def stats_from_prices(prices, tickers):
    """Annualized mu/cov (Ledoit-Wolf) + last/change from a price matrix.

    prices: (T, N) closes, oldest first. Returns dict or None on bad input.
    """
    P = np.asarray(prices, dtype=float)
    if P.ndim != 2 or P.shape[0] < 60 or P.shape[1] != len(tickers):
        return None
    if not np.all(np.isfinite(P)) or np.any(P <= 0):
        return None
    rets = np.diff(P, axis=0) / P[:-1]
    rets = rets[np.all(np.isfinite(rets), axis=1)]
    if len(rets) < 60:
        return None
    mu = rets.mean(axis=0) * 252.0
    cov, delta = ledoit_wolf(rets)
    cov = cov * 252.0
    sigma = np.sqrt(np.diag(cov))
    beta = np.clip(cov.mean(axis=1) / max(cov.mean(), 1e-9), 0.2, 3.0)
    alpha = mu - beta * mu.mean()
    return {"tickers": list(tickers), "mu": mu, "cov": cov, "sigma": sigma,
            "beta": beta, "alpha": alpha, "prices": P,
            "last": P[-1], "chg_pct": (P[-1] - P[-2]) / P[-2] * 100.0,
            "shrinkage": round(float(delta), 3), "days": int(P.shape[0])}


def fetch_yahoo(tickers, period="3y"):
    """Fetch adjusted closes via yfinance. Returns (ok, payload|message)."""
    key = (tuple(sorted(tickers)), period)
    now = time.time()
    if key in _CACHE and now - _CACHE[key][0] < _CACHE_TTL:
        return True, _CACHE[key][1]
    try:
        import yfinance as yf
        df = yf.download(list(tickers) + ["SPY"], period=period,
                         auto_adjust=True, progress=False, threads=True)
        if df is None or len(df) < 60:
            return False, "Yahoo returned too little data."
        closes = df["Close"] if "Close" in df else df
        have = [t for t in tickers if t in closes.columns]
        if len(have) < 3:
            return False, f"Yahoo missing tickers (got {have})."
        P = closes[have].dropna()
        spy = closes["SPY"].reindex(P.index).dropna() if "SPY" in closes.columns else None
        if len(P) < 60:
            return False, "Not enough overlapping history."
        st = stats_from_prices(P.values, have)
        if st is None:
            return False, "Could not compute stats from Yahoo data."
        st["spy"] = np.asarray(spy.loc[P.index].values, float) if spy is not None else None
        st["source"] = "yahoo"
        _CACHE[key] = (now, st)
        return True, st
    except Exception as e:
        return False, f"Yahoo fetch failed: {e}"


def parse_upload_csv(text):
    """Parse user CSV: first column dates (ignored), rest ticker closes.

    Returns (ok, {tickers, prices}|message).
    """
    try:
        import pandas as pd
        df = pd.read_csv(io.StringIO(text))
        if df.shape[1] < 4:
            return False, "Need a date column + at least 3 ticker columns."
        tickers = [str(c).strip().upper() for c in df.columns[1:11]]
        P = df.iloc[:, 1:1 + len(tickers)].apply(pd.to_numeric, errors="coerce").values
        P = P[np.all(np.isfinite(P), axis=1)]
        if P.shape[0] < 60:
            return False, "Need at least 60 clean rows of prices."
        return True, {"tickers": tickers, "prices": P}
    except Exception as e:
        return False, f"CSV parse failed: {e}"
