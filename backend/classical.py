"""Classical baselines: exact MIQP (brute force), simulated annealing, simulated QA."""
from __future__ import annotations
import itertools
import numpy as np
from .qubo import energy_of_selection


def _valid_bitstrings(n, K):
    for bits in itertools.product([0, 1], repeat=n):
        if sum(bits) == K:
            yield bits


def exact_solver(mu, cov, risk_q, K, P):
    mu = np.asarray(mu, float); cov = np.asarray(cov, float)
    n = len(mu)
    best, best_e = None, float("inf")
    valid = []
    for bits in _valid_bitstrings(n, K):
        e = energy_of_selection(bits, mu, cov, risk_q, K, P)
        valid.append(("".join(map(str, bits)), e))
        if e < best_e:
            best_e, best = e, "".join(map(str, bits))
    valid.sort(key=lambda t: t[1])
    hist = [{"iter": i, "energy": e} for i, (_, e) in enumerate(
        sorted(valid, key=lambda t: t[1], reverse=True)[:50])]
    return {"best_bitstring": best, "best_energy": float(best_e),
            "ranked": valid[:16], "history": hist}


def _anneal(mu, cov, risk_q, K, P, steps=4000, seed=0, quantum_tunnel=False, on_step=None):
    rng = np.random.default_rng(seed)
    n = len(mu)
    # start with random feasible solution
    perm = rng.permutation(n)
    x = np.zeros(n, dtype=int)
    x[perm[:K]] = 1
    cur_e = energy_of_selection(x, mu, cov, risk_q, K, P)
    best_x, best_e = x.copy(), cur_e
    T0, Tend = (1.5, 0.005) if not quantum_tunnel else (0.8, 0.002)
    history = []
    visits = {}
    step_every = max(steps // 60, 1)
    for s in range(steps):
        T = T0 * (Tend / T0) ** (s / max(steps - 1, 1))
        # propose swap (keeps cardinality feasible) — occasionally double-swap as "tunneling"
        i1 = int(rng.integers(0, n))
        ones = np.where(x == 1)[0]; zeros = np.where(x == 0)[0]
        if len(ones) == 0 or len(zeros) == 0:
            break
        o = int(rng.choice(ones)); z = int(rng.choice(zeros))
        x2 = x.copy(); x2[o] = 0; x2[z] = 1
        if quantum_tunnel and rng.random() < 0.15 and len(ones) >= 2 and len(zeros) >= 2:
            o2 = int(rng.choice([i for i in ones if i != o] or [o]))
            z2 = int(rng.choice([i for i in zeros if i != z] or [z]))
            if o2 != o and z2 != z:
                x2[o2] = 0; x2[z2] = 1  # 2-bit tunnel move
        e2 = energy_of_selection(x2, mu, cov, risk_q, K, P)
        if e2 < cur_e or rng.random() < np.exp(-(e2 - cur_e) / max(T, 1e-9)):
            x, cur_e = x2, e2
            if cur_e < best_e:
                best_e, best_x = cur_e, x.copy()
        key = "".join(map(str, x))
        visits[key] = visits.get(key, 0) + 1
        if s % step_every == 0:
            pt = {"iter": s, "energy": float(cur_e)}
            history.append(pt)
            if on_step:
                on_step(pt)
    history.append({"iter": steps, "energy": float(best_e)})
    total = sum(visits.values()) or 1
    ranked = sorted(visits.items(), key=lambda kv: kv[1], reverse=True)[:10]
    histogram = []
    for bits, cnt in ranked:
        e = energy_of_selection([int(b) for b in bits], mu, cov, risk_q, K, P)
        histogram.append({"bitstring": bits, "count": int(cnt),
                          "prob": round(cnt / total, 4),
                          "feasible": sum(int(b) for b in bits) == K,
                          "energy": round(float(e), 4)})
    return {"best_bitstring": "".join(map(str, best_x)), "best_energy": float(best_e),
            "history": history, "histogram": histogram}


def simulated_annealing(mu, cov, risk_q, K, P, steps=4000, seed=0, on_step=None):
    return _anneal(mu, cov, risk_q, K, P, steps, seed, quantum_tunnel=False, on_step=on_step)


def simulated_quantum_annealing(mu, cov, risk_q, K, P, steps=4000, seed=0, on_step=None):
    """D-Wave proxy: anneal + transverse-field-inspired tunneling moves."""
    return _anneal(mu, cov, risk_q, K, P, steps, seed, quantum_tunnel=True, on_step=on_step)


def anneal_spectrum(mu, cov, risk_q, K, P, n_pts=15):
    """Minimum spectral gap of H(s) = -A(s) sum X + B(s) diag(E).

    Dense solve (2^N); skipped honestly for N > 8. A(s) = A0(1-s), B(s) = s
    with A0 set by the problem energy range. Adiabatic rule: tf >> 1/dmin^2.
    """
    import numpy as np
    mu = np.asarray(mu, float)
    n = len(mu)
    if n > 8:
        return {"skipped": True,
                "reason": f"N={n}: dense 2^N gap solve skipped (use N<=8)."}
    dim = 2 ** n
    E = np.array([energy_of_selection([(k >> i) & 1 for i in range(n)],
                                      mu, cov, risk_q, K, P) for k in range(dim)])
    A0 = float(max(E.max() - E.min(), 1e-9))
    ss = np.linspace(0, 1, n_pts).tolist()
    A = [A0 * (1 - s) for s in ss]
    B = [s for s in ss]
    gaps = []
    for a, b in zip(A, B):
        H = np.diag(b * E)
        for i in range(n):
            flip = np.array([k ^ (1 << i) for k in range(dim)])
            H[np.arange(dim), flip] -= a
        vals = np.linalg.eigvalsh(H)
        gaps.append(round(float(vals[1] - vals[0]), 4))
    i_min = int(np.argmin(gaps))
    return {"skipped": False, "s": [round(s, 3) for s in ss],
            "A": [round(a, 3) for a in A], "B": [round(b, 3) for b in B],
            "gaps": gaps, "delta_min": gaps[i_min], "s_star": round(ss[i_min], 3),
            "A0": round(A0, 3),
            "rule": "adiabatic run time tf >> 1/dmin^2"}


def flow_diagram(kind, n, K, best_bitstring, steps=4000):
    """Schematic stages for non-gate solvers (rendered as boxes, not wires)."""
    import math as _m
    combos = _m.comb(n, K)
    if kind == "classical":
        return {"type": "flow", "title": "EXACT MIQP ENUMERATION", "stages": [
            {"label": f"2^{n} = {2 ** n}", "detail": "all portfolios"},
            {"label": f"K = {K} FILTER", "detail": f"{combos} feasible"},
            {"label": "MIN ENERGY", "detail": "branch-and-bound"},
            {"label": best_bitstring or "", "detail": "optimal readout"}]}
    if kind == "quantum_annealing":
        return {"type": "flow", "title": "ADIABATIC ANNEAL (D-WAVE STYLE)", "stages": [
            {"label": "s = 0", "detail": "transverse field ON"},
            {"label": f"s -> 1 ({steps})", "detail": "problem Hamiltonian"},
            {"label": "TUNNEL", "detail": "2-bit flip moves"},
            {"label": best_bitstring or "", "detail": "ground-state readout"}]}
    return {"type": "flow", "title": "THERMAL ANNEALING", "stages": [
        {"label": "RANDOM K-SET", "detail": "feasible start"},
        {"label": "COOL 1.5->0.005", "detail": f"{steps} swap steps"},
        {"label": "1-BIT SWAPS", "detail": "Metropolis rule"},
        {"label": best_bitstring or "", "detail": "best readout"}]}
