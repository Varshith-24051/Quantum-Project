"""Markowitz MIQP -> QUBO -> Ising mapping."""
from __future__ import annotations
import numpy as np


def auto_penalty(mu: np.ndarray, cov: np.ndarray, risk_q: float, n: int) -> float:
    scale = float(np.max(np.abs(cov)) * risk_q * n + np.max(np.abs(mu)))
    return round(max(1.0, 1.5 * scale + 0.5), 4)


def build_qubo(mu, cov, risk_q: float, K: int, penalty=None):
    mu = np.asarray(mu, dtype=float)
    cov = np.asarray(cov, dtype=float)
    n = len(mu)
    P = float(penalty) if penalty else auto_penalty(mu, cov, risk_q, n)
    # Symmetric Q: energy = x^T Qs x - mu^T x ... careful: fold -mu into diag
    Qs = risk_q * cov.copy()
    diag_add = -mu + P * (1 - 2 * K)
    np.fill_diagonal(Qs, np.diag(Qs) + diag_add)
    # off-diagonal penalty 2P for i!=j (since (sum x - K)^2 contributes 2P x_i x_j)
    Qs = Qs + P * 2 * (np.ones((n, n)) - np.eye(n)) / 2 * 2 / 2  # = +P off-diag? fix below
    # Recompute cleanly: penalty matrix Pm with 0 diag-add already in diag, off-diag = 2P? No:
    # (sum x)^2 = sum x_i + 2 sum_{i<j} x_i x_j  => symmetric matrix off-diag = P (each pair counted twice)
    Qs = risk_q * cov.copy()
    np.fill_diagonal(Qs, np.diag(Qs) + (-mu + P * (1 - 2 * K)))
    off = np.ones((n, n)) - np.eye(n)
    Qs = Qs + off * P  # symmetric off-diagonal P  =>  x^T Qs x counts 2P per pair. correct.
    offset = P * K * K
    # Upper-triangular view for display (diag + strictly-upper doubled)
    Qu = np.triu(Qs) + np.triu(Qs, 1)
    return {"Q_symmetric": Qs, "Q_upper": Qu, "offset": float(offset), "penalty": float(P)}


def energy_of_selection(x, mu, cov, risk_q: float, K: int, P: float) -> float:
    x = np.asarray(x, dtype=float)
    return float(risk_q * x @ cov @ x - mu @ x + P * (x.sum() - K) ** 2)


def qubo_to_ising(Q_upper) -> dict:
    """x=(I-Z)/2 mapping. Returns h, J, ising_offset (const)."""
    Q = np.asarray(Q_upper, dtype=float)
    n = Q.shape[0]
    h = np.zeros(n)
    J = np.zeros((n, n))
    const = 0.0
    for i in range(n):
        const += Q[i, i] / 2.0
        h[i] -= Q[i, i] / 2.0
    for i in range(n):
        for j in range(i + 1, n):
            q = Q[i, j]
            if q == 0:
                continue
            const += q / 4.0
            h[i] -= q / 4.0
            h[j] -= q / 4.0
            J[i, j] = J[j, i] = q / 4.0
    return {"h": h, "J": J, "ising_offset": float(const)}
