"""FastAPI middleware: quant terminal API + static frontend hosting."""
from __future__ import annotations
import asyncio
import math
import time
import uuid
from pathlib import Path

import numpy as np
from fastapi import FastAPI, HTTPException, UploadFile, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from .market import get_universe, get_subset, get_price_history
from .qubo import build_qubo, qubo_to_ising, energy_of_selection
from .classical import (exact_solver, simulated_annealing,
                        simulated_quantum_annealing, flow_diagram,
                        anneal_spectrum)
from .quantum_qiskit import qaoa_run, vqe_run, qaoa_xy_run, HAS_QISKIT
from .finance import inv_vol_weights, backtest, frontier, executive_summary
from . import data_live, runs_db

DATASETS: dict[str, dict] = {}

FRONTEND_DIR = Path(__file__).resolve().parent.parent / "frontend"

app = FastAPI(title="Quantum Portfolio Terminal", version="1.0.0")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"],
                   allow_headers=["*"])

DEFAULT_TICKERS = ["AAPL", "MSFT", "GOOGL", "AMZN", "NVDA", "TSLA", "JPM", "JNJ"]


class OptimizeRequest(BaseModel):
    tickers: list[str] = Field(default_factory=lambda: list(DEFAULT_TICKERS))
    K: int = 4
    risk_q: float = 0.5
    algorithm: str = "qaoa"  # qaoa | vqe | classical | annealing | quantum_annealing
    p: int = 2
    shots: int = 2048
    optimizer: str = "COBYLA"
    rebalance: str = "buy_hold"  # buy_hold | monthly
    mixer: str = "standard"  # standard | xy (qaoa only)
    noise: str = "ideal"  # ideal | eagle
    zne: bool = False
    cvar_alpha: float = 1.0
    source: str = "mock"  # mock | yahoo | upload
    dataset_id: str | None = None
    yahoo_period: str = "3y"


def validate_request(req: OptimizeRequest):
    if req.source == "upload" and not req.dataset_id:
        raise HTTPException(400, "Upload a CSV dataset first (source=upload needs dataset_id).")
    if req.source == "upload" and req.dataset_id not in DATASETS:
        raise HTTPException(400, "Unknown dataset_id. Re-upload the CSV.")
    tickers = req.tickers
    if req.source == "upload":
        tickers = DATASETS[req.dataset_id]["tickers"]
    if len(tickers) < 3:
        raise HTTPException(400, "Select at least 3 tickers.")
    if not (1 <= req.K <= len(tickers)):
        raise HTTPException(400, "K must be between 1 and number of tickers.")
    if len(set(tickers)) != len(tickers):
        raise HTTPException(400, "Duplicate tickers in universe.")
    if req.source == "mock":
        get_subset(tickers)  # raises ValueError on unknown tickers
    if req.rebalance not in ("buy_hold", "monthly"):
        raise HTTPException(400, "rebalance must be buy_hold or monthly.")
    if req.mixer not in ("standard", "xy"):
        raise HTTPException(400, "mixer must be standard or xy.")
    if req.mixer == "xy" and req.algorithm != "qaoa":
        raise HTTPException(400, "XY mixer is only available with QAOA.")
    if req.noise not in ("ideal", "eagle"):
        raise HTTPException(400, "noise must be ideal or eagle.")
    if not (0.05 <= req.cvar_alpha <= 1.0):
        raise HTTPException(400, "cvar_alpha must be in [0.05, 1].")
    if req.source not in ("mock", "yahoo", "upload"):
        raise HTTPException(400, "source must be mock, yahoo or upload.")


def resolve_data(req: OptimizeRequest):
    """Return tickers, mu, cov, sigma, price_hist, bench_label, source_info."""
    if req.source == "yahoo":
        ok, payload = data_live.fetch_yahoo(req.tickers, req.yahoo_period)
        if not ok:
            raise HTTPException(502, f"{payload} (Tip: switch source back to MOCK.)")
        tickers = payload["tickers"]
        if not (1 <= req.K <= len(tickers)):
            raise HTTPException(400, f"Yahoo returned {len(tickers)} tickers; adjust K.")
        spy = payload.get("spy")
        bench = "S&P 500 (live)"
        if spy is None:
            eq = payload["prices"] / payload["prices"][0]
            spy = eq.mean(axis=1) * 400.0
            bench = "EQ BASKET (live)"
        hist = {"prices": payload["prices"], "spy": np.asarray(spy, float),
                "days": payload["days"]}
        info = {"source": "yahoo", "period": req.yahoo_period,
                "shrinkage": payload.get("shrinkage")}
        return {"tickers": tickers, "mu": payload["mu"], "cov": payload["cov"],
                "sigma": payload["sigma"], "hist": hist, "bench": bench, "info": info}
    if req.source == "upload":
        ds = DATASETS[req.dataset_id]
        st = data_live.stats_from_prices(ds["prices"], ds["tickers"])
        if st is None:
            raise HTTPException(400, "Stored dataset is invalid. Re-upload.")
        tickers = st["tickers"]
        eq = st["prices"] / st["prices"][0]
        hist = {"prices": st["prices"], "spy": eq.mean(axis=1) * 100.0,
                "days": st["days"]}
        info = {"source": "upload", "filename": ds.get("filename"),
                "shrinkage": st.get("shrinkage")}
        return {"tickers": tickers, "mu": st["mu"], "cov": st["cov"],
                "sigma": st["sigma"], "hist": hist, "bench": "EQ BASKET (csv)",
                "info": info}
    sub = get_subset(req.tickers)
    hist = get_price_history(req.tickers)
    return {"tickers": req.tickers, "mu": sub["mu"], "cov": sub["cov"],
            "sigma": sub["sigma"], "hist": hist, "bench": "S&P 500 (mock)",
            "info": {"source": "mock", "seed": 42}}


def _run_algorithm(algo, mu, cov, risk_q, K, P, p, shots, optimizer, on_step=None,
                   mixer="standard", noise="ideal", zne=False, cvar_alpha=1.0,
                   n_restarts=1):
    t0 = time.perf_counter()
    n = len(mu)
    kw = dict(noise=noise, zne=zne, cvar_alpha=cvar_alpha, n_restarts=n_restarts)
    if algo == "qaoa" and mixer == "xy":
        try:
            res = qaoa_xy_run(mu, cov, risk_q, K, P, p=p, shots=shots,
                              optimizer=optimizer, on_step=on_step, **kw)
        except RuntimeError as e:
            raise HTTPException(400, str(e))
    elif algo == "qaoa":
        res = qaoa_run(mu, cov, risk_q, K, P, p=p, shots=shots,
                       optimizer=optimizer, on_step=on_step, **kw)
    elif algo == "vqe":
        res = vqe_run(mu, cov, risk_q, K, P, p=p, shots=shots,
                      optimizer=optimizer, on_step=on_step, **kw)
    elif algo == "classical":
        r = exact_solver(mu, cov, risk_q, K, P)
        res = {"algorithm": "Classical Exact (MIQP Branch-and-Bound)",
               "best_bitstring": r["best_bitstring"], "best_energy": r["best_energy"],
               "histogram": [{"bitstring": b, "prob": 1.0, "count": shots,
                              "feasible": True, "energy": round(e, 4)} for b, e in r["ranked"][:8]],
               "convergence": [{"iter": 0, "energy": r["best_energy"]}],
               "backend": "brute-force exact (2^N enumeration)",
               "circuit": {"n_qubits": n, "depth_p": 0, "layers": [],
                           "flow": flow_diagram("classical", n, K, r["best_bitstring"]),
                           "summary": f"no quantum circuit - exact enumeration of 2^{n}"}}
        if on_step:
            on_step({"iter": 0, "energy": r["best_energy"]})
    elif algo == "annealing":
        r = simulated_annealing(mu, cov, risk_q, K, P, on_step=on_step)
        res = {"algorithm": "Simulated Annealing", **r, "backend": "classical thermal anneal",
               "circuit": {"n_qubits": n, "depth_p": 0, "layers": [],
                           "flow": flow_diagram("annealing", n, K, r["best_bitstring"]),
                           "summary": "no quantum circuit - thermal annealing schedule"}}
    elif algo == "quantum_annealing":
        r = simulated_quantum_annealing(mu, cov, risk_q, K, P, on_step=on_step)
        res = {"algorithm": "Quantum Annealing (simulated D-Wave proxy)", **r,
               "backend": "simulated adiabatic + tunneling",
               "spectral": anneal_spectrum(mu, cov, risk_q, K, P),
               "circuit": {"n_qubits": n, "depth_p": 0, "layers": [],
                           "flow": flow_diagram("quantum_annealing", n, K, r["best_bitstring"]),
                           "summary": "annealer schedule - no gate circuit"}}
    else:
        raise HTTPException(400, f"Unknown algorithm: {algo}")
    dt = time.perf_counter() - t0
    res["seconds"] = round(dt, 2)
    return res


def _assemble(req: OptimizeRequest, res: dict, data: dict):
    tickers = data["tickers"]
    mu, cov, sig = data["mu"], data["cov"], data["sigma"]
    hist = data["hist"]
    Q = build_qubo(mu, cov, req.risk_q, req.K)
    # exact baseline always (for the red flat line + comparison)
    base = exact_solver(mu, cov, req.risk_q, req.K, Q["penalty"])
    bitstring = res.get("best_bitstring") or base["best_bitstring"]
    sel_idx = [i for i, b in enumerate(bitstring) if b == "1"]
    sel_sig = [float(sig[i]) for i in sel_idx] or [1.0]
    sel_weights = inv_vol_weights(sel_sig)
    wmap = {tickers[i]: round(sel_weights[k], 4) for k, i in enumerate(sel_idx)}
    mode = getattr(req, "rebalance", "buy_hold") or "buy_hold"
    bt = backtest(bitstring, tickers,
                  [wmap[t] for t in tickers if t in wmap] or [1.0],
                  hist, mode=mode)
    m_port = bt.get("metrics_port", {})
    m_spy = bt.get("metrics_spy", {})
    sharpe_q = m_port.get("sharpe", 0) or 0
    # classical portfolio sharpe for summary
    bt_c = backtest(base["best_bitstring"], tickers,
                    inv_vol_weights([float(sig[i]) for i, b in enumerate(base["best_bitstring"]) if b == "1"]),
                    hist, mode=mode)
    sharpe_c = (bt_c.get("metrics_port", {}) or {}).get("sharpe", 0) or 0
    m_classical = bt_c.get("metrics_port", {})
    # equal-weight benchmark (for the dossier comparison table)
    bt_eq = backtest("1" * len(tickers), tickers, [1.0 / len(tickers)] * len(tickers),
                     hist, mode=mode)
    m_eq = bt_eq.get("metrics_port", {})
    n_combos = math.comb(len(tickers), req.K)
    # quantum point for frontier (equal selected weights)
    wq = np.zeros(len(tickers)); wq[sel_idx] = np.array(sel_weights)
    qpoint = {"x": round(float(np.sqrt(wq @ cov @ wq)) * 100, 2),
              "y": round(float(wq @ mu) * 100, 2), "kind": "quantum"}
    fr = frontier(mu, cov, tickers, req.K, Q["penalty"], req.risk_q, qpoint)
    ising = qubo_to_ising(Q["Q_upper"])
    mixer_suffix = " + XY" if req.mixer == "xy" and req.algorithm == "qaoa" else ""
    algo_label = ({"qaoa": "QAOA", "vqe": "VQE", "classical": "Classical Exact",
                   "annealing": "Simulated Annealing",
                   "quantum_annealing": "Quantum Annealing"}.get(req.algorithm, req.algorithm)
                  + mixer_suffix)
    summary = executive_summary(algo_label, bitstring, tickers, req.K,
                                res.get("seconds", 0), sharpe_q, sharpe_c, n_combos)
    selected = [{"ticker": tickers[i], "weight_pct": round(sel_weights[k] * 100, 1),
                 "mu_pct": round(float(mu[i]) * 100, 2),
                 "sigma_pct": round(float(sig[i]) * 100, 2)}
                for k, i in enumerate(sel_idx)]
    math_payload = {
        "markowitz": "minimize  q · xᵀΣx  −  μᵀx  +  P·(Σxᵢ − K)²   over x ∈ {0,1}ⁿ",
        "qubo": Q["Q_upper"].round(4).tolist(),
        "ising_h": [round(float(v), 4) for v in ising["h"]],
        "ising_J": np.asarray(ising["J"]).round(4).tolist(),
        "ising_offset": round(float(ising["ising_offset"]), 4),
        "penalty": Q["penalty"], "risk_q": req.risk_q, "K": req.K,
        "mapping": "xᵢ = (1 − Zᵢ)/2  →  H_C = Σ hᵢZᵢ + Σ JᵢⱼZᵢZⱼ + const",
    }
    run_id = runs_db.log_run(req.model_dump(), bitstring, res.get("best_energy"),
                             sharpe_q, res.get("seconds", 0))
    # --- consistency gate: one feasible-manifold scale for every number ---
    from itertools import combinations as _comb
    _fe = []
    for _c in _comb(range(len(tickers)), req.K):
        _x = [1 if _i in _c else 0 for _i in range(len(tickers))]
        _fe.append(energy_of_selection(_x, mu, cov, req.risk_q, req.K, Q["penalty"]))
    emin_feas, emax_feas = round(min(_fe), 4), round(max(_fe), 4)
    # Headline ratio is answer-based: best feasible bitstring always lies in
    # [emin, emax], so alpha is in [0,1] by construction (fp-clamped).
    e_best = res.get("best_energy")
    if e_best is None or emax_feas == emin_feas:
        approx_ratio = 1.0 if req.algorithm == "classical" else None
    else:
        approx_ratio = round(min(1.0, max(0.0, (e_best - emax_feas) /
                                                 (emin_feas - emax_feas))), 4)
    # Distribution ratio uses the spec formula on <H_C>; unbounded when the
    # state leaks onto infeasible configurations (that IS the signal).
    e_exp = res.get("expected_energy")
    approx_expect = (round((e_exp - emax_feas) / (emin_feas - emax_feas), 4)
                     if e_exp is not None and emax_feas != emin_feas else None)
    feas_mass = res.get("feasibility_rate")
    if feas_mass is None and req.algorithm == "classical":
        feas_mass = 1.0
    import math as _m2
    subspace = {"N": len(tickers), "K": req.K, "total": 2 ** len(tickers),
                "feasible_count": _m2.comb(len(tickers), req.K),
                "feasible_mass": feas_mass,
                "leakage": (round(1 - feas_mass, 4) if feas_mass is not None else None)}
    # --- transpilation routing bounds (linear LB + heavy-hex UB) ---
    circ = res.get("circuit", {}) or {}
    if circ.get("layers"):
        from .routing import routing_bounds
        nq = circ.get("n_qubits", len(tickers))
        rpairs = [p for ly in circ["layers"] if ly.get("kind") == "COST"
                  for p in (ly.get("pairs") or [])]
        cx = sum(len(ly.get("pairs") or []) for ly in circ["layers"]
                 if ly.get("kind") == "CX")
        circ["routing"] = routing_bounds(nq, rpairs, cx)
    return {
        "summary": summary, "algorithm": algo_label,
        "best_bitstring": bitstring, "selected": selected,
        "weights": wmap, "energy": res.get("best_energy"),
        "expected_energy": res.get("expected_energy"),
        "cvar_alpha": res.get("cvar_alpha", 1.0),
        "cvar_energy": res.get("cvar_energy"),
        "feasibility_rate": res.get("feasibility_rate"),
        "penalty_note": res.get("penalty_note"),
        "mixer": req.mixer, "noise": res.get("noise", {"mode": "ideal"}),
        "states": res.get("states", []),
        "approx_ratio": approx_ratio,
        "approx_expect": approx_expect,
        "e_min_feas": emin_feas, "e_max_feas": emax_feas,
        "subspace": subspace,
        "weight_dist": res.get("weight_dist"),
        "qubit_info": res.get("qubit_info"),
        "landscape": res.get("landscape"),
        "cvar_cutoff": res.get("cvar_cutoff"),
        "spectral": res.get("spectral"),
        "restart_marks": res.get("restart_marks", [0]),
        "bloch_traj": res.get("bloch_traj"),
        "classical_energy": base["best_energy"],
        "classical_bitstring": base["best_bitstring"],
        "histogram": res.get("histogram", []),
        "convergence": res.get("convergence", []),
        "circuit": res.get("circuit", {}),
        "backend": res.get("backend", ""),
        "seconds": res.get("seconds", 0),
        "metrics": m_port, "metrics_spy": m_spy, "metrics_eq": m_eq,
        "metrics_classical": m_classical,
        "turnover_pct": bt.get("turnover_pct", 0.0), "rebalance": mode,
        "backtest": {"portfolio": bt.get("portfolio_curve", []), "spy": bt.get("spy_curve", [])},
        "bench_label": data["bench"],
        "frontier": fr, "math": math_payload,
        "cov": np.asarray(cov).round(4).tolist(), "tickers": tickers,
        "source_info": data["info"],
        "has_qiskit": HAS_QISKIT, "run_id": run_id,
    }


@app.get("/api/health")
def health():
    return {"ok": True, "qiskit": HAS_QISKIT}


@app.get("/api/universe")
def universe(source: str = "mock", tickers: str = "", period: str = "3y"):
    if source == "yahoo":
        wanted = [t.strip().upper() for t in tickers.split(",") if t.strip()][:10]
        if len(wanted) < 3:
            raise HTTPException(400, "Provide at least 3 tickers for Yahoo mode.")
        ok, payload = data_live.fetch_yahoo(wanted, period)
        if not ok:
            raise HTTPException(502, payload)
        assets = [{"ticker": t, "name": t, "sector": "LIVE",
                   "mu": round(float(payload["mu"][i]), 4),
                   "sigma": round(float(payload["sigma"][i]), 4),
                   "beta": round(float(payload["beta"][i]), 2),
                   "alpha": round(float(payload["alpha"][i]), 4),
                   "last": round(float(payload["last"][i]), 2),
                   "chg_pct": round(float(payload["chg_pct"][i]), 2)}
                  for i, t in enumerate(payload["tickers"])]
        return {"assets": assets, "cov": np.asarray(payload["cov"]).round(4).tolist(),
                "source": "yahoo", "shrinkage": payload.get("shrinkage")}
    assets, cov = get_universe()
    return {"assets": assets, "cov": np.asarray(cov).round(4).tolist(), "source": "mock"}


@app.post("/api/datasets")
async def upload_dataset(file: UploadFile):
    text = (await file.read()).decode("utf-8", errors="replace")
    ok, payload = data_live.parse_upload_csv(text)
    if not ok:
        raise HTTPException(400, payload)
    st = data_live.stats_from_prices(payload["prices"], payload["tickers"])
    if st is None:
        raise HTTPException(400, "Could not compute stats from CSV.")
    ds_id = uuid.uuid4().hex[:8]
    DATASETS[ds_id] = {"tickers": st["tickers"], "prices": st["prices"],
                       "filename": file.filename}
    assets = [{"ticker": t, "name": t, "sector": "CSV",
               "mu": round(float(st["mu"][i]), 4),
               "sigma": round(float(st["sigma"][i]), 4),
               "beta": round(float(st["beta"][i]), 2),
               "alpha": round(float(st["alpha"][i]), 4),
               "last": round(float(st["last"][i]), 2),
               "chg_pct": round(float(st["chg_pct"][i]), 2)}
              for i, t in enumerate(st["tickers"])]
    return {"dataset_id": ds_id, "assets": assets,
            "cov": np.asarray(st["cov"]).round(4).tolist(),
            "days": st["days"], "shrinkage": st.get("shrinkage")}


@app.get("/api/runs")
def run_history(limit: int = 20):
    return {"runs": runs_db.list_runs(min(limit, 100))}


@app.delete("/api/runs")
def clear_history():
    return {"cleared": runs_db.clear_runs()}


@app.get("/api/qpu/status")
def qpu_status():
    try:
        import qiskit_ibm_runtime  # noqa
        runtime = True
    except Exception:
        runtime = False
    return {"connected": False,
            "runtime_installed": runtime,
            "message": ("qiskit-ibm-runtime is installed — paste an IBM Quantum API token "
                        "to connect (not stored)." if runtime else
                        "qiskit-ibm-runtime is not installed; running in Aer emulation mode. "
                        "pip install qiskit-ibm-runtime + IBM token required for real QPUs.")}


@app.post("/api/optimize")
def optimize(req: OptimizeRequest):
    try:
        validate_request(req)
    except ValueError as e:
        raise HTTPException(400, str(e))
    data = resolve_data(req)
    Q = build_qubo(data["mu"], data["cov"], req.risk_q, req.K)
    res = _run_algorithm(req.algorithm, data["mu"], data["cov"], req.risk_q,
                         req.K, Q["penalty"], max(1, min(req.p, 4)),
                         max(256, min(req.shots, 8192)), req.optimizer,
                         mixer=req.mixer, noise=req.noise, zne=req.zne,
                         cvar_alpha=req.cvar_alpha, n_restarts=3)
    return _assemble(req, res, data)


@app.post("/api/compare")
def compare(req: OptimizeRequest):
    """Run every solver with a capped budget and return a comparison table."""
    try:
        validate_request(req)
    except ValueError as e:
        raise HTTPException(400, str(e))
    data = resolve_data(req)
    mu, cov, sig = data["mu"], data["cov"], data["sigma"]
    tickers = data["tickers"]
    Q = build_qubo(mu, cov, req.risk_q, req.K)
    mode = req.rebalance or "buy_hold"
    rows = []
    jobs = [("classical", {}), ("annealing", {}), ("quantum_annealing", {}),
            ("qaoa", {}), ("qaoa_xy", {"mixer": "xy"}), ("vqe", {})]
    for algo_key, extra in jobs:
        algo = "qaoa" if algo_key == "qaoa_xy" else algo_key
        r = _run_algorithm(algo, mu, cov, req.risk_q, req.K,
                           Q["penalty"], max(1, min(req.p, 3)), 2048, req.optimizer,
                           cvar_alpha=req.cvar_alpha, **extra)
        b = r.get("best_bitstring")
        if b:
            sel = [float(sig[i]) for i, c in enumerate(b) if c == "1"]
            bt = backtest(b, tickers, inv_vol_weights(sel), data["hist"], mode=mode)
            sharpe = (bt.get("metrics_port", {}) or {}).get("sharpe")
        else:
            sharpe = None
        rows.append({"algorithm": algo_key, "label": r.get("algorithm", algo_key),
                     "bitstring": b, "energy": r.get("best_energy"),
                     "sharpe": sharpe, "seconds": r.get("seconds"),
                     "weight_dist": r.get("weight_dist"),
                     "leakage": (round(1 - r["feasibility_rate"], 4)
                                 if r.get("feasibility_rate") is not None else None)})
    rows.sort(key=lambda d: (d["energy"] is None, d["energy"] or 1e18))
    return {"rows": rows, "classical_energy": rows[0]["energy"] if rows else None}


@app.websocket("/ws/optimize")
async def ws_optimize(ws: WebSocket):
    """Live execution stream: baseline -> per-iteration energy -> done+result."""
    await ws.accept()
    try:
        cfg = await ws.receive_json()
        req = OptimizeRequest(**cfg)
        try:
            validate_request(req)
        except ValueError as e:
            raise HTTPException(400, str(e))
        data = resolve_data(req)
        mu, cov = data["mu"], data["cov"]
        Q = build_qubo(mu, cov, req.risk_q, req.K)
        base = exact_solver(mu, cov, req.risk_q, req.K, Q["penalty"])
        await ws.send_json({"type": "baseline",
                            "classical_energy": base["best_energy"],
                            "classical_bitstring": base["best_bitstring"],
                            "penalty": Q["penalty"]})
        loop = asyncio.get_running_loop()
        queue: asyncio.Queue = asyncio.Queue()

        def on_step(pt):
            loop.call_soon_threadsafe(queue.put_nowait, pt)

        def blocking():
            return _run_algorithm(
                req.algorithm, mu, cov, req.risk_q, req.K,
                Q["penalty"], max(1, min(req.p, 4)),
                max(256, min(req.shots, 8192)), req.optimizer, on_step=on_step,
                mixer=req.mixer, noise=req.noise, zne=req.zne,
                cvar_alpha=req.cvar_alpha, n_restarts=3)

        task = asyncio.create_task(asyncio.to_thread(blocking))
        while not task.done():
            try:
                pt = await asyncio.wait_for(queue.get(), timeout=0.1)
                await ws.send_json({"type": "progress", "iter": pt["iter"],
                                    "energy": pt["energy"]})
            except asyncio.TimeoutError:
                continue
        while not queue.empty():
            pt = queue.get_nowait()
            await ws.send_json({"type": "progress", "iter": pt["iter"],
                                "energy": pt["energy"]})
        res = await task
        await ws.send_json({"type": "done", "result": _assemble(req, res, data)})
    except WebSocketDisconnect:
        return
    except Exception as e:
        try:
            await ws.send_json({"type": "error", "message": str(e)})
        except Exception:
            pass
    finally:
        try:
            await ws.close()
        except Exception:
            pass


# ---- static frontend -------------------------------------------------------
@app.get("/", include_in_schema=False)
def index():
    return FileResponse(FRONTEND_DIR / "index.html")


if FRONTEND_DIR.exists():
    app.mount("/static", StaticFiles(directory=str(FRONTEND_DIR)), name="static")

    @app.get("/app.js", include_in_schema=False)
    def app_js():
        return FileResponse(FRONTEND_DIR / "app.js", media_type="application/javascript")

    @app.get("/styles.css", include_in_schema=False)
    def styles():
        return FileResponse(FRONTEND_DIR / "styles.css", media_type="text/css")
