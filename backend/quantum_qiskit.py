"""Gate-based quantum solvers: QAOA + VQE via Qiskit Aer/Statevector.

Primary path uses Qiskit. A pure-NumPy fallback guarantees the demo
works even where Qiskit is unavailable. Both paths expose the same API.
"""
from __future__ import annotations
import numpy as np

try:
    from qiskit import QuantumCircuit
    from qiskit.quantum_info import Statevector
    HAS_QISKIT = True
except Exception:  # pragma: no cover
    HAS_QISKIT = False

from scipy.optimize import minimize

from .qubo import energy_of_selection, qubo_to_ising


def tail_expectation(probs, E, alpha=1.0):
    """CVaR_alpha: mean over the lowest-energy alpha-tail of the distribution."""
    if alpha is None or alpha >= 1.0:
        return float(np.asarray(probs, float) @ np.asarray(E, float))
    idx = np.argsort(np.asarray(E, float))
    remaining, acc = float(alpha), 0.0
    for i in idx:
        take = min(float(probs[i]), remaining)
        acc += take * float(E[i])
        remaining -= take
        if remaining <= 1e-12:
            break
    return float(acc / max(float(alpha) - remaining, 1e-12))


def _top_from(probs, amps, n, top_k=48):
    order = np.argsort(np.asarray(probs, float))[::-1][:top_k]
    out = []
    for k in order:
        if probs[k] <= 0:
            continue
        ph = round(float(np.angle(amps[k])), 3) if amps is not None else 0.0
        out.append({"bitstring": _bits_of(int(k), n),
                    "prob": round(float(probs[k]), 5), "phase": ph})
    return out


def top_amplitudes_qiskit(qc, n, top_k=48):
    """Brightest basis states with phases (for the state-density grid)."""
    from qiskit.quantum_info import Statevector as _SV
    a = np.asarray(_SV(qc).data)
    p = np.abs(a) ** 2
    s = p.sum()
    probs = p / s if s > 0 else p
    return _top_from(probs, a, n, top_k)


def _final_state_info(qc, n):
    """One statevector eval -> (probs, top states, per-qubit info)."""
    from qiskit.quantum_info import Statevector as _SV
    a = np.asarray(_SV(qc).data)
    p = np.abs(a) ** 2
    s = p.sum()
    probs = p / s if s > 0 else p
    return probs, _top_from(probs, a, n), _qubit_info(a, n)


# ---------------------------------------------------------------- optimizers
def _spsa(fun, x0, maxiter=80, seed=0, on_step=None, track=None):
    rng = np.random.default_rng(seed)
    x = np.array(x0, float)
    a, c, A = 0.25, 0.12, maxiter / 10.0
    alpha, gamma = 0.602, 0.101
    best_x, best_f = x.copy(), float(fun(x))
    hist = [{"iter": 0, "energy": best_f}]
    if track is not None:
        track.append([round(float(v), 4) for v in x])
    if on_step:
        on_step(hist[0])
    for k in range(1, maxiter + 1):
        ak = a / (k + A) ** alpha
        ck = c / (k) ** gamma
        delta = rng.choice([-1.0, 1.0], size=x.shape)
        fp = float(fun(x + ck * delta))
        fm = float(fun(x - ck * delta))
        grad = (fp - fm) / (2 * ck) * delta
        x = x - ak * grad
        f = float(fun(x))
        if f < best_f:
            best_f, best_x = f, x.copy()
        pt = {"iter": k, "energy": float(f)}
        hist.append(pt)
        if track is not None:
            track.append([round(float(v), 4) for v in x])
        if on_step:
            on_step(pt)
    return best_x, best_f, hist


def _cobyla(fun, x0, maxiter=80, on_step=None, track=None):
    hist = []
    def wrapped(x):
        f = float(fun(x))
        pt = {"iter": len(hist), "energy": f}
        hist.append(pt)
        if track is not None:
            track.append([round(float(v), 4) for v in np.asarray(x, float)])
        if on_step:
            on_step(pt)
        return f
    res = minimize(wrapped, np.array(x0, float), method="COBYLA",
                   options={"maxiter": maxiter, "rhobeg": 0.5})
    return res.x, float(res.fun), hist


def _optimize(fun, x0, optimizer, maxiter, on_step=None, track=None):
    if optimizer.upper() == "SPSA":
        return _spsa(fun, x0, maxiter, on_step=on_step, track=track)
    return _cobyla(fun, x0, maxiter, on_step=on_step, track=track)


# ------------------------------------------------------- Qiskit circuit paths
def _qaoa_circuit(n, h, J, gammas, betas, seed_eps=None):
    qc = QuantumCircuit(n)
    qc.h(range(n))
    if seed_eps is not None:
        for i in range(n):  # symmetry-breaking seed (fixed, deterministic)
            qc.rz(float(seed_eps[i]), i)
    p = len(gammas)
    for layer in range(p):
        g, b = float(gammas[layer]), float(betas[layer])
        for i in range(n):
            if abs(h[i]) > 1e-12:
                qc.rz(2 * g * h[i], i)
        for i in range(n):
            for j in range(i + 1, n):
                if abs(J[i, j]) > 1e-12:
                    qc.rzz(2 * g * J[i, j], i, j)
        for i in range(n):
            qc.rx(2 * b, i)
    return qc


def _vqe_circuit(n, reps, theta):
    qc = QuantumCircuit(n)
    idx = 0
    for i in range(n):
        qc.ry(float(theta[idx]), i); idx += 1
    for i in range(n):
        qc.rz(float(theta[idx]), i); idx += 1
    for _ in range(reps):
        for i in range(n - 1):
            qc.cx(i, i + 1)
        for i in range(n):
            qc.ry(float(theta[idx]), i); idx += 1
        for i in range(n):
            qc.rz(float(theta[idx]), i); idx += 1
    return qc


def _probs_qiskit(qc) -> np.ndarray:
    sv = Statevector(qc)
    probs = np.abs(np.asarray(sv.data)) ** 2
    s = probs.sum()
    return probs / s if s > 0 else probs


# ------------------------------------------------------- NumPy fallback sim
def _apply_1q(state, mat, qubit, n):
    """Apply single-qubit gate. Logical qubit m <-> bit m of the state index
    (qiskit little-endian convention), i.e. C-order axis n-1-m."""
    state = state.reshape([2] * n)
    axis = n - 1 - qubit
    state = np.moveaxis(state, axis, -1)
    state = state @ mat.T
    state = np.moveaxis(state, -1, axis)
    return state.reshape(-1)


def _fallback_probas(n, kind, params, h, J, reps=1, seed_eps=None):
    I = np.eye(2, dtype=complex)
    H = np.array([[1, 1], [1, -1]], complex) / np.sqrt(2)
    def RX(t): return np.array([[np.cos(t/2), -1j*np.sin(t/2)], [-1j*np.sin(t/2), np.cos(t/2)]], complex)
    def RZ(t): return np.array([[np.exp(-1j*t/2), 0], [0, np.exp(1j*t/2)]], complex)
    def RY(t): return np.array([[np.cos(t/2), -np.sin(t/2)], [np.sin(t/2), np.cos(t/2)]], complex)
    state = np.zeros(2 ** n, complex); state[0] = 1.0
    if kind == "qaoa":
        p = len(params) // 2
        gammas, betas = params[:p], params[p:]
        for q in range(n):
            state = _apply_1q(state, H, q, n)
        if seed_eps is not None:
            for i in range(n):
                state = _apply_1q(state, RZ(float(seed_eps[i])), i, n)
        for layer in range(p):
            g, b = gammas[layer], betas[layer]
            for i in range(n):
                state = _apply_1q(state, RZ(2 * g * h[i]), i, n)
            for i in range(n):  # RZZ via CNOT-RZ-CNOT
                for j in range(i + 1, n):
                    if abs(J[i, j]) < 1e-12:
                        continue
                    state = _cx(state, i, j, n)
                    state = _apply_1q(state, RZ(2 * g * J[i, j]), j, n)
                    state = _cx(state, i, j, n)
            for i in range(n):
                state = _apply_1q(state, RX(2 * b), i, n)
    else:
        theta = list(params); idx = 0
        for i in range(n):
            state = _apply_1q(state, RY(theta[idx]), i, n); idx += 1
        for i in range(n):
            state = _apply_1q(state, RZ(theta[idx]), i, n); idx += 1
        for _ in range(reps):
            for i in range(n - 1):
                state = _cx(state, i, i + 1, n)
            for i in range(n):
                state = _apply_1q(state, RY(theta[idx]), i, n); idx += 1
            for i in range(n):
                state = _apply_1q(state, RZ(theta[idx]), i, n); idx += 1
    probs = np.abs(state) ** 2
    return probs / probs.sum()


def _cx(state, ctrl, tgt, n):
    s = state.reshape([2] * n)
    # logical qubit m lives on C-order axis n-1-m (little-endian indexing)
    ax_c, ax_t = n - 1 - ctrl, n - 1 - tgt
    out = s.copy()
    for basis in np.ndindex(*([2] * n)):
        if basis[ax_c] == 1:
            flipped = list(basis); flipped[ax_t] ^= 1
            out[basis] = s[tuple(flipped)]
    return out.reshape(-1)


# ------------------------------------------------------------------ runners
def _bits_of(k, n):
    """Display bitstring: char i <-> ticker/qubit i (little-endian order)."""
    return "".join(str((k >> i) & 1) for i in range(n))


def _all_energies(n, mu, cov, risk_q, K, P):
    E = np.zeros(2 ** n)
    for k in range(2 ** n):
        bits = [(k >> i) & 1 for i in range(n)]  # x_m = bit m: qubit m = ticker m
        E[k] = energy_of_selection(bits, mu, cov, risk_q, K, P)
    return E


def _noise_report(kind, use_qiskit, noise, zne, E, n, K, shots, seed, make_qc):
    rep = {"mode": noise or "ideal", "hw_badge": None, "noisy_energy": None,
           "feasibility_rate": None, "zne": None, "note": ""}
    if (noise or "ideal") == "ideal" or not use_qiskit:
        rep["note"] = ("ideal statevector (noiseless)" if use_qiskit
                       else "numpy fallback: no noise model available")
        return rep
    from .noise import EAGLE_PROFILE, run_noisy, zne_mitigate
    r = run_noisy(make_qc(), n, E, K, shots=min(shots, 4096), seed=seed)
    rep.update({"hw_badge": "EMULATING IBM EAGLE NOISE PROFILE",
                "profile": {k: v for k, v in EAGLE_PROFILE.items() if k != "name"},
                "noisy_energy": r["energy"], "noisy_histogram": r["histogram"],
                "feasibility_rate": r["feasibility_rate"]})
    if zne and kind in ("qaoa", "qaoa_xy"):
        rep["zne"] = zne_mitigate(make_qc, E, n, K, shots=1024, seed=seed)
    return rep


def _feasible_bounds(E, n, K):
    feas = [float(E[k]) for k in range(2 ** n) if bin(k).count("1") == K]
    return round(min(feas), 4), round(max(feas), 4)


def _weight_dist(probs, n):
    d = {}
    for k in range(len(probs)):
        w = bin(k).count("1")
        d[w] = d.get(w, 0.0) + float(probs[k])
    return {str(w): round(d.get(w, 0.0), 5) for w in range(n + 1)}


def _cvar_cutoff(probs, E, alpha):
    if alpha is None or alpha >= 1.0:
        return None
    idx = np.argsort(np.asarray(E, float))
    cum = 0.0
    for i in idx:
        cum += float(probs[i])
        if cum >= float(alpha) - 1e-12:
            return round(float(E[i]), 4)
    return round(float(E[idx[-1]]), 4)


def _qubit_info(amps, n):
    """Per-qubit reduced states from amplitudes: Bloch vector, purity, entropy.

    rho_k built directly (no API risk): p0, coherence over the other n-1 bits.
    """
    amps = np.asarray(amps, dtype=complex)
    out = []
    for m in range(n):
        p0, coh = 0.0, 0.0j
        for k in range(2 ** n):
            if (k >> m) & 1 == 0:
                k1 = k | (1 << m)
                p0 += float(abs(amps[k]) ** 2)
                coh += amps[k] * np.conj(amps[k1])
        p1 = 1.0 - p0
        x, y, z = 2 * float(coh.real), -2 * float(coh.imag), float(p0 - p1)
        r = min(1.0, float(np.sqrt(x * x + y * y + z * z)))
        purity = round(float(p0 * p0 + p1 * p1 + 2 * abs(coh) ** 2), 4)
        lam = [(1 + r) / 2, (1 - r) / 2]
        ent = round(float(-sum(l * np.log(l) for l in lam if l > 1e-12)), 4)
        out.append({"qubit": m, "bloch": [round(x, 3), round(y, 3), round(z, 3)],
                    "rlen": round(r, 3), "purity": purity, "entropy": ent})
    return out


def _landscape_grid(build_probs, E, alpha, n_grid=25):
    """Full (gamma, beta) energy map for p=1 (625 ideal evaluations)."""
    gs = np.linspace(0, 2 * np.pi, n_grid)
    bs = np.linspace(0, np.pi, n_grid)
    Z = np.zeros((n_grid, n_grid))
    for i, g in enumerate(gs):
        for j, b in enumerate(bs):
            Z[j, i] = round(tail_expectation(build_probs(float(g), float(b)), E, alpha), 4)
    return {"gamma": [round(float(v), 3) for v in gs],
            "beta": [round(float(v), 3) for v in bs],
            "Z": Z.tolist(), "path": []}


def _bloch_traj(build_qc, trace, n, frames=10):
    """Rebuilt Bloch vectors at sampled optimization steps (qiskit only).

    NOTE: QAOA frames reuse the WINNING seed layer (per-restart eps varies);
    XY/VQE rebuilds are exact. Trail thus shows the true path up to the
    fixed ±0.5 rad seed-phase choice on standard QAOA.
    """
    from qiskit.quantum_info import Statevector as _SV
    if not trace:
        return []
    idxs = sorted(set(int(round(i)) for i in
                      np.linspace(0, len(trace) - 1, min(frames, len(trace)))))
    out = []
    for ii in idxs:
        v = np.asarray(trace[ii], float)
        a = np.asarray(_SV(build_qc(v)).data)
        qi = _qubit_info(a, n)
        out.append({"trace_idx": ii, "bloch": [q["bloch"] for q in qi]})
    return out


def _finish(probs, E, n, K, shots, seed, history, extra):
    rng = np.random.default_rng(seed)
    counts = rng.multinomial(shots, probs / probs.sum())
    order = np.argsort(counts)[::-1]
    hist = []
    for k in order[:10]:
        if counts[k] <= 0:
            continue
        bits = _bits_of(int(k), n)
        hist.append({"bitstring": bits, "count": int(counts[k]),
                     "prob": round(float(counts[k] / shots), 4),
                     "exact": round(float(probs[k]), 5),
                     "feasible": sum(int(b) for b in bits) == K,
                     "energy": round(float(E[k]), 4)})
    # best feasible by probability
    feas = [h for h in hist if h["feasible"]]
    best = max(feas, key=lambda d: d["prob"]) if feas else (hist[0] if hist else None)
    expected = round(float(np.asarray(probs, float) @ np.asarray(E, float)), 4)
    # close the convergence trace exactly at the reported expectation so the
    # chart endpoint always equals the headline number (consistency gate)
    history = list(history) + [{"iter": len(history), "energy": expected,
                                "final": True}]
    out = {"best_bitstring": best["bitstring"] if best else None,
           "best_energy": best["energy"] if best else None,
           "histogram": hist, "convergence": history,
           "backend": extra.get("backend", "unknown"), **extra}
    return out


def _optimize_restarts(make_bundle, optimizer, maxiter, on_step, seeds, trace=None):
    """Multi-start search. Returns (theta, f, history, extra, marks, trace).

    marks = history-iter where each restart begins (restart delimiters);
    trace = full param vector per evaluation (landscape path + Bloch movie).
    """
    best, history, base, marks = None, [], 0, []
    for sd in seeds:
        marks.append(base)
        expectation_fn, x0, extra = make_bundle(sd)
        local = []

        def _cap(pt, _l=local, _b=base, _cb=on_step):
            _l.append(pt)
            if _cb:
                _cb({"iter": _b + pt["iter"], "energy": pt["energy"]})

        th, f, _ = _optimize(expectation_fn, x0, optimizer, maxiter, _cap, trace)
        history.extend([{"iter": base + d["iter"], "energy": d["energy"]} for d in local])
        base += len(local)
        if best is None or f < best[0]:
            best = (f, th, extra)
    return best[1], best[0], history, best[2], marks, trace or []


def qaoa_run(mu, cov, risk_q, K, P, p=2, shots=2048, optimizer="COBYLA",
             maxiter=60, seed=42, on_step=None, noise="ideal", zne=False,
             cvar_alpha=1.0, n_restarts=1):
    mu = np.asarray(mu, float); cov = np.asarray(cov, float)
    n = len(mu)
    from .qubo import build_qubo
    Q = build_qubo(mu, cov, risk_q, K, P)
    h, J = qubo_to_ising(Q["Q_upper"])["h"], qubo_to_ising(Q["Q_upper"])["J"]
    # Normalize the cost Hamiltonian so circuit angles are O(1): with raw
    # penalty-scale coefficients, gamma oscillates dozens of times and the
    # classical optimizer stalls on infeasible states. Argmin is unchanged.
    esc = float(np.abs(Q["Q_upper"]).max()) or 1.0
    h, J = np.asarray(h) / esc, np.asarray(J) / esc
    E = _all_energies(n, mu, cov, risk_q, K, P)

    use_qiskit = HAS_QISKIT
    alpha = float(cvar_alpha or 1.0)

    def make_bundle(sd):
        r = np.random.default_rng(sd)
        # Wide init is safe now that h, J are normalized (max angle ~ pi).
        x0 = np.concatenate([r.uniform(0, 2 * np.pi, p), r.uniform(0, np.pi, p)])
        e = np.random.default_rng(sd + 999).uniform(-0.5, 0.5, n)  # SEED phases

        def expectation(params):
            params = np.asarray(params, float)
            gammas, betas = params[:p], params[p:]
            if use_qiskit:
                qc = _qaoa_circuit(n, h, J, gammas, betas, e)
                probs = _probs_qiskit(qc)
            else:
                probs = _fallback_probas(n, "qaoa", params, h, J, seed_eps=e)
            return tail_expectation(probs, E, alpha)

        return expectation, x0, e

    trace = []
    theta_opt, _, history, eps, marks, trace = _optimize_restarts(
        make_bundle, optimizer, maxiter, on_step,
        [seed + i for i in range(max(1, n_restarts))], trace)
    gammas, betas = np.asarray(theta_opt[:p], float), np.asarray(theta_opt[p:], float)
    if use_qiskit:
        qc_final = _qaoa_circuit(n, h, J, gammas, betas, eps)
        probs, states, qinfo = _final_state_info(qc_final, n)
        backend_name = "qiskit-statevector (Aer-compatible)"
    else:
        probs = _fallback_probas(n, "qaoa", np.asarray(theta_opt, float), h, J, seed_eps=eps)
        backend_name = "numpy-fallback-statevector"
        states = [{"bitstring": _bits_of(int(k), n), "prob": round(float(probs[k]), 5),
                   "phase": 0.0} for k in np.argsort(probs)[::-1][:48] if probs[k] > 0]

    layers = [{"title": "INIT H", "sub": f"superposition |+>^{n}",
               "kind": "H",
               "gates": [{"gate": "H", "qubit": i} for i in range(n)]},
              {"title": "SEED", "sub": "symmetry-break RZ",
               "kind": "SEED",
               "gates": [{"gate": "RZ", "qubit": i} for i in range(n)]}]
    landscape = None
    bloch_traj = None
    if p == 1:
        def _bp(g, b):
            if use_qiskit:
                return _probs_qiskit(_qaoa_circuit(n, h, J, [g], [b], eps))
            return _fallback_probas(n, "qaoa", np.array([g, b]), h, J, seed_eps=eps)
        landscape = _landscape_grid(_bp, E, alpha)
        landscape["path"] = [[t[0], t[1]] for t in trace if len(t) == 2][:600]
        landscape["note"] = "landscape for winning SEED layer; path = all restarts"
    if use_qiskit:
        bloch_traj = _bloch_traj(
            lambda v: _qaoa_circuit(n, h, J, v[:p], v[p:], eps), trace, n)
    for layer in range(p):
        pairs = [[i, j] for i in range(n) for j in range(i + 1, n) if abs(J[i, j]) > 1e-9]
        layers.append({
            "title": f"COST g{layer+1}={gammas[layer]:.2f}",
            "sub": f"RZ+RZZ x{len(pairs)} (money math)",
            "kind": "COST",
            "rz": list(range(n)),
            "mesh": len(pairs),
            "pairs": pairs,
            "rzz": [{"pair": [i, j],
                     "angle": round(float(2 * gammas[layer] * J[i, j]), 3)}
                    for i, j in pairs]})
        layers.append({
            "title": f"MIX b{layer+1}={betas[layer]:.2f}",
            "sub": "RX explore",
            "kind": "MIXER",
            "rx": list(range(n))})
    extra = {"backend": backend_name, "algorithm": "QAOA",
             "expected_energy": round(float(probs @ E), 4),
             "cvar_alpha": alpha,
             "cvar_energy": round(tail_expectation(probs, E, alpha), 4),
             "cvar_cutoff": _cvar_cutoff(probs, E, alpha),
             "e_min_feas": _feasible_bounds(E, n, K)[0],
             "e_max_feas": _feasible_bounds(E, n, K)[1],
             "weight_dist": _weight_dist(probs, n),
             "qubit_info": qinfo if use_qiskit else None,
             "states": states,
             "feasibility_rate": round(float(sum(probs[k] for k in range(2 ** n)
                                                 if bin(k).count("1") == K)), 4),
             "noise": _noise_report("qaoa", use_qiskit, noise, zne, E, n, K, shots, seed,
                                    lambda: _qaoa_circuit(n, h, J, gammas, betas, eps)),
             "circuit": {"n_qubits": n, "depth_p": p, "layers": layers, "flow": None,
                         "summary": f"{n} qubits - p={p} - {2*p} params - shots={shots}"},
             "landscape": landscape,
             "restart_marks": marks,
             "bloch_traj": bloch_traj}
    return _finish(probs, E, n, K, shots, seed, history, extra)


def vqe_run(mu, cov, risk_q, K, P, p=2, shots=2048, optimizer="COBYLA",
            maxiter=60, seed=42, on_step=None, noise="ideal", zne=False,
            cvar_alpha=1.0, n_restarts=1):
    from .qubo import build_qubo
    mu = np.asarray(mu, float); cov = np.asarray(cov, float)
    n = len(mu)
    Q = build_qubo(mu, cov, risk_q, K, P)
    ising = qubo_to_ising(Q["Q_upper"])
    h, J = ising["h"], ising["J"]
    E = _all_energies(n, mu, cov, risk_q, K, P)
    reps = max(1, int(p))
    n_params = n * 2 * (reps + 1)
    use_qiskit = HAS_QISKIT
    alpha = float(cvar_alpha or 1.0)

    def make_bundle(sd):
        x0 = np.random.default_rng(sd + 7).uniform(0, 2 * np.pi, n_params)

        def expectation(params):
            if use_qiskit:
                probs = _probs_qiskit(_vqe_circuit(n, reps, np.asarray(params, float)))
            else:
                probs = _fallback_probas(n, "vqe", np.asarray(params, float), h, J, reps)
            return tail_expectation(probs, E, alpha)

        return expectation, x0, None

    trace = []
    theta_opt, _, history, _, marks, trace = _optimize_restarts(
        make_bundle, optimizer, maxiter, on_step,
        [seed + i for i in range(max(1, n_restarts))], trace)
    bloch_traj = None
    if use_qiskit:
        qc_final = _vqe_circuit(n, reps, np.asarray(theta_opt, float))
        probs, states, qinfo = _final_state_info(qc_final, n)
        backend_name = "qiskit-statevector EfficientSU2 (Aer-compatible)"
        bloch_traj = _bloch_traj(
            lambda v: _vqe_circuit(n, reps, np.asarray(v, float)), trace, n)
    else:
        probs = _fallback_probas(n, "vqe", np.asarray(theta_opt, float), h, J, reps)
        backend_name = "numpy-fallback EfficientSU2"
        states = [{"bitstring": _bits_of(int(k), n), "prob": round(float(probs[k]), 5),
                   "phase": 0.0} for k in np.argsort(probs)[::-1][:48] if probs[k] > 0]
    layers = [{"title": "ROT in", "sub": "RY+RZ layer", "kind": "ROT",
               "ry": list(range(n)), "rz": list(range(n))}]
    for r in range(reps):
        layers.append({"title": f"ENT r{r+1}", "sub": "CNOT chain", "kind": "CX",
                       "pairs": [[i, i + 1] for i in range(n - 1)]})
        layers.append({"title": f"ROT r{r+1}", "sub": "RY+RZ layer", "kind": "ROT",
                       "ry": list(range(n)), "rz": list(range(n))})
    extra = {"backend": backend_name, "algorithm": "VQE",
             "expected_energy": round(float(probs @ E), 4),
             "cvar_alpha": alpha,
             "cvar_energy": round(tail_expectation(probs, E, alpha), 4),
             "cvar_cutoff": _cvar_cutoff(probs, E, alpha),
             "e_min_feas": _feasible_bounds(E, n, K)[0],
             "e_max_feas": _feasible_bounds(E, n, K)[1],
             "weight_dist": _weight_dist(probs, n),
             "qubit_info": qinfo if use_qiskit else None,
             "states": states,
             "feasibility_rate": round(float(sum(probs[k] for k in range(2 ** n)
                                                 if bin(k).count("1") == K)), 4),
             "noise": _noise_report("vqe", use_qiskit, noise, False, E, n, K, shots, seed,
                                    lambda: _vqe_circuit(n, reps, np.asarray(theta_opt, float))),
             "circuit": {"n_qubits": n, "depth_p": reps, "layers": layers, "flow": None,
                         "summary": f"{n} qubits - EfficientSU2 reps={reps} - {n_params} params - shots={shots}"},
             "landscape": None,
             "restart_marks": marks,
             "bloch_traj": bloch_traj}
    return _finish(probs, E, n, K, shots, seed, history, extra)


def _dicke_vector(n, K):
    """Equal superposition over all Hamming-weight-K bitstrings."""
    from math import comb
    vec = np.zeros(2 ** n, dtype=complex)
    amp = 1.0 / np.sqrt(comb(n, K))
    for k in range(2 ** n):
        if bin(k).count("1") == K:
            vec[k] = amp
    return vec


def _qaoa_xy_circuit(n, h, J, gammas, betas, K):
    qc = QuantumCircuit(n)
    qc.initialize(_dicke_vector(n, K), list(range(n)))
    p = len(gammas)
    for layer in range(p):
        g, b = float(gammas[layer]), float(betas[layer])
        for i in range(n):
            if abs(h[i]) > 1e-12:
                qc.rz(2 * g * h[i], i)
        for i in range(n):
            for j in range(i + 1, n):
                if abs(J[i, j]) > 1e-12:
                    qc.rzz(2 * g * J[i, j], i, j)
        for i in range(n):  # XY ring mixer: conserves Hamming weight
            j = (i + 1) % n
            qc.rxx(b, i, j)
            qc.ryy(b, i, j)
    return qc


def qaoa_xy_run(mu, cov, risk_q, K, P=0.0, p=2, shots=2048, optimizer="COBYLA",
                maxiter=60, seed=42, on_step=None, noise="ideal", zne=False,
                cvar_alpha=1.0, n_restarts=1):
    """Subspace QAOA: Dicke-state init + XY ring mixer. No penalty needed.

    Searches only the C(N,K) feasible subspace — 100% feasible by construction.
    Requires Qiskit (initialize + rxx/ryy).
    """
    if not HAS_QISKIT:
        raise RuntimeError("QAOA-XY requires Qiskit (not installed).")
    from .qubo import build_qubo
    mu = np.asarray(mu, float); cov = np.asarray(cov, float)
    n = len(mu)
    Q0 = build_qubo(mu, cov, risk_q, K, penalty=0.0)
    ising = qubo_to_ising(Q0["Q_upper"])
    h, J = ising["h"], ising["J"]
    esc = float(np.abs(Q0["Q_upper"]).max()) or 1.0
    h, J = np.asarray(h) / esc, np.asarray(J) / esc
    E = _all_energies(n, mu, cov, risk_q, K, 0.0)  # raw objective, no penalty
    alpha = float(cvar_alpha or 1.0)

    def make_bundle(sd):
        r = np.random.default_rng(sd)
        x0 = np.concatenate([r.uniform(0, 2 * np.pi, p), r.uniform(0, np.pi, p)])

        def expectation(params):
            params = np.asarray(params, float)
            probs = _probs_qiskit(_qaoa_xy_circuit(n, h, J, params[:p], params[p:], K))
            return tail_expectation(probs, E, alpha)

        return expectation, x0, None

    trace = []
    theta_opt, _, history, _, marks, trace = _optimize_restarts(
        make_bundle, optimizer, maxiter, on_step,
        [seed + i for i in range(max(1, n_restarts))], trace)
    gammas, betas = np.asarray(theta_opt[:p], float), np.asarray(theta_opt[p:], float)
    qc_final = _qaoa_xy_circuit(n, h, J, gammas, betas, K)
    probs, states, qinfo = _final_state_info(qc_final, n)
    mesh = int(sum(1 for i in range(n) for j in range(i + 1, n) if abs(J[i, j]) > 1e-9))
    landscape = None
    bloch_traj = None
    if p == 1:
        landscape = _landscape_grid(
            lambda g, b: _probs_qiskit(_qaoa_xy_circuit(n, h, J, [g], [b], K)),
            E, alpha)
        landscape["path"] = [[t[0], t[1]] for t in trace if len(t) == 2][:600]
        landscape["note"] = "XY subspace landscape; path = all restarts"
    bloch_traj = _bloch_traj(
        lambda v: _qaoa_xy_circuit(n, h, J, v[:p], v[p:], K), trace, n)
    mesh = int(sum(1 for i in range(n) for j in range(i + 1, n) if abs(J[i, j]) > 1e-9))
    from .routing import dicke_compile_stats
    layers = [{"title": f"DICKE D({n},{K})", "sub": "feasible subspace only", "kind": "DICKE",
               "prep_stats": dicke_compile_stats(n, K)}]
    for layer in range(p):
        pairs = [[i, j] for i in range(n) for j in range(i + 1, n) if abs(J[i, j]) > 1e-9]
        layers.append({"title": f"COST g{layer+1}={gammas[layer]:.2f}",
                       "sub": "no penalty needed", "kind": "COST",
                       "rz": list(range(n)), "mesh": len(pairs), "pairs": pairs,
                       "rzz": [{"pair": [i, j],
                                "angle": round(float(2 * gammas[layer] * J[i, j]), 3)}
                               for i, j in pairs]})
        layers.append({"title": f"XY-MIX b{layer+1}={betas[layer]:.2f}",
                       "sub": "ring conserves weight", "kind": "XYM",
                       "pairs": [[i, (i + 1) % n] for i in range(n)]})
    extra = {"backend": "qiskit-statevector Dicke+XY (Aer-compatible)",
             "algorithm": "QAOA-XY (subspace)",
             "expected_energy": round(float(probs @ E), 4),
             "cvar_alpha": alpha,
             "cvar_energy": round(tail_expectation(probs, E, alpha), 4),
             "cvar_cutoff": _cvar_cutoff(probs, E, alpha),
             "e_min_feas": _feasible_bounds(E, n, K)[0],
             "e_max_feas": _feasible_bounds(E, n, K)[1],
             "weight_dist": _weight_dist(probs, n),
             "qubit_info": qinfo,
             "states": states,
             "feasibility_rate": 1.0,
             "penalty_note": "none - particle-number-conserving XY mixer",
             "noise": _noise_report("qaoa_xy", True, noise, zne, E, n, K, shots, seed,
                                    lambda: _qaoa_xy_circuit(n, h, J, gammas, betas, K)),
              "circuit": {"n_qubits": n, "depth_p": p, "layers": layers, "flow": None,
                          "summary": f"{n} qubits - XY p={p} - Dicke({n},{K}) - shots={shots}"},
              "landscape": landscape,
              "restart_marks": marks,
              "bloch_traj": bloch_traj}
    return _finish(probs, E, n, K, shots, seed, history, extra)
