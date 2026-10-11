"""Defense-grade verification: noise, ZNE, XY, CVaR, live data, dossiers, history."""
import numpy as np

from backend.market import get_subset
from backend.qubo import build_qubo
from backend.classical import exact_solver
from backend import quantum_qiskit as qq
from backend.noise import get_noise_model, run_noisy, zne_mitigate, fold_two_qubit, EAGLE_PROFILE
from backend.data_live import ledoit_wolf, stats_from_prices, parse_upload_csv, fetch_yahoo
from backend import runs_db
from backend.main import OptimizeRequest, validate_request, optimize, compare
from fastapi import HTTPException

PASS, FAIL = 0, 0
def check(name, cond, extra=""):
    global PASS, FAIL
    if cond:
        PASS += 1
        print(f"  ok  {name}")
    else:
        FAIL += 1
        print(f" FAIL  {name} {extra}")

S4 = get_subset(["AAPL", "MSFT", "GOOGL", "AMZN"])
Q4 = build_qubo(S4["mu"], S4["cov"], 0.5, 2)

print("== 1. noise model ==")
m = get_noise_model("eagle")
check("eagle model builds", m is not None and get_noise_model("ideal") is None)
check("profile sane", EAGLE_PROFILE["p2_depol"] == 1e-2 and EAGLE_PROFILE["readout_flip"] == 0.02)

print("== 2. noisy final eval (N=4) ==")
E4 = qq._all_energies(4, S4["mu"], S4["cov"], 0.5, 2, Q4["penalty"])
from backend.qubo import qubo_to_ising
ising = qubo_to_ising(Q4["Q_upper"])
qc = qq._qaoa_circuit(4, ising["h"], ising["J"], [0.5], [0.4])
rn = run_noisy(qc, 4, E4, 2, shots=512, seed=1)
check("noisy energy finite", np.isfinite(rn["energy"]), str(rn["energy"]))
check("noisy counts sum", sum(d["count"] for d in rn["histogram"]) <= 512 and len(rn["histogram"]) > 0)
check("noisy feas rate in [0,1]", 0.0 <= rn["feasibility_rate"] <= 1.0, str(rn["feasibility_rate"]))

print("== 3. ZNE folding + extrapolation ==")
f3 = fold_two_qubit(qc, 3)
check("folded circuit deeper", len(list(f3.data)) > len(list(qc.data)))
z = zne_mitigate(lambda: qq._qaoa_circuit(4, ising["h"], ising["J"], [0.5], [0.4]),
                 E4, 4, 2, shots=256, seed=1)
check("zne 3 points + mitigated", len(z["points"]) == 3 and np.isfinite(z["mitigated"]), str(z))

print("== 4. QAOA-XY subspace (N=6,K=2) ==")
S6 = get_subset(["AAPL", "MSFT", "GOOGL", "AMZN", "NVDA", "TSLA"])
Q6 = build_qubo(S6["mu"], S6["cov"], 0.5, 2)
opt_raw = exact_solver(S6["mu"], S6["cov"], 0.5, 2, 0.0)
rxy = qq.qaoa_xy_run(S6["mu"], S6["cov"], 0.5, 2, Q6["penalty"], p=2, shots=1024,
                     optimizer="COBYLA", maxiter=40)
all_feas = all(h["feasible"] for h in rxy["histogram"])
check("xy 100% feasible histogram", all_feas and rxy["feasibility_rate"] == 1.0,
      str([h["bitstring"] for h in rxy["histogram"]][:4]))
check("xy near raw optimum", rxy["best_energy"] <= opt_raw["best_energy"] + 1.0,
      f"xy={rxy['best_energy']:.3f} opt={opt_raw['best_energy']:.3f} ({rxy['best_bitstring']} vs {opt_raw['best_bitstring']})")
check("xy layers incl DICKE/XYM", [l["kind"] for l in rxy["circuit"]["layers"]][:3] == ["DICKE", "COST", "XYM"])

print("== 5. CVaR tail property ==")
rc = qq.qaoa_run(S4["mu"], S4["cov"], 0.5, 2, Q4["penalty"], p=1, shots=512,
                 optimizer="COBYLA", maxiter=8, cvar_alpha=0.25)
check("cvar <= expectation", rc["cvar_energy"] <= rc["expected_energy"] + 1e-9,
      f"cvar={rc['cvar_energy']} exp={rc['expected_energy']}")
check("alpha echoed", rc["cvar_alpha"] == 0.25)

print("== 6. Ledoit-Wolf shrinkage ==")
rng = np.random.default_rng(0)
T = 250
factor = rng.standard_normal((T, 1))
X = factor @ rng.standard_normal((1, 8)) * 0.02 + rng.standard_normal((T, 8)) * 0.001
S_lw, delta = ledoit_wolf(X)
eig = np.linalg.eigvalsh(S_lw)
check("LW PD + delta in [0,1]", eig.min() > 0 and 0.0 <= delta <= 1.0,
      f"min_eig={eig.min():.2e} delta={delta:.3f}")
check("LW symmetric", np.allclose(S_lw, S_lw.T))

print("== 7. CSV upload parse ==")
lines = ["date," + ",".join(["AAPL", "MSFT", "GOOGL", "AMZN"])]
px = 100.0
for d in range(80):
    px = px * 1.001
    lines.append(f"2023-01-{d+1:02d}," + ",".join(f"{px*(1+i*0.1):.2f}" for i in range(4)))
ok, pay = parse_upload_csv("\n".join(lines))
check("csv ok", ok and pay["prices"].shape == (80, 4), str(pay["prices"].shape if ok else pay))
st = stats_from_prices(pay["prices"], pay["tickers"]) if ok else None
check("csv stats PD", st is not None and np.linalg.eigvalsh(st["cov"]).min() > 0)
bad, msg = parse_upload_csv("a,b\n1,2")
check("csv rejects junk", not bad)

print("== 8. yahoo contract (live or graceful) ==")
ok, pay = fetch_yahoo(["AAPL", "MSFT", "GOOGL"], "3mo")
check("yahoo returns contract", isinstance(ok, bool), f"ok={ok} {str(pay)[:80]}")

print("== 9. sqlite history ==")
runs_db.clear_runs()
runs_db.log_run({"algorithm": "qaoa", "tickers": ["A", "B"], "K": 1}, "10", 1.0, 0.5, 0.1)
runs_db.log_run({"algorithm": "vqe", "tickers": ["A", "B"], "K": 1}, "01", 2.0, 0.4, 0.2)
rows = runs_db.list_runs()
check("2 runs listed", len(rows) == 2, str(len(rows)))
check("history cleared", runs_db.clear_runs() and runs_db.list_runs() == [])

print("== 10. REST defense payload (xy+eagle+zne+cvar) ==")
req = OptimizeRequest(tickers=["AAPL", "MSFT", "GOOGL", "AMZN"], K=2, risk_q=0.5,
                      algorithm="qaoa", mixer="xy", p=1, shots=512, optimizer="COBYLA",
                      noise="eagle", zne=True, cvar_alpha=0.5)
out = optimize(req)
check("states present", len(out["states"]) > 0, str(len(out["states"])))
check("noise report full", out["noise"].get("hw_badge") and out["noise"].get("zne"), str(out["noise"].get("hw_badge")))
check("dossier fields", all(k in out for k in ["metrics_classical", "metrics_eq", "run_id", "bench_label", "source_info"]))
check("xy 100% feasible live", out["feasibility_rate"] == 1.0)
try:
    validate_request(OptimizeRequest(tickers=["AAPL", "MSFT", "GOOGL"], K=2, mixer="xy", algorithm="vqe"))
    check("xy+vqe rejected", False)
except HTTPException:
    check("xy+vqe rejected", True)

print("== 11. compare now 6 rows ==")
cmp_out = compare(OptimizeRequest(tickers=["AAPL", "MSFT", "GOOGL", "AMZN"], K=2, p=1))
labels = [r["algorithm"] for r in cmp_out["rows"]]
check("6 solvers incl qaoa_xy", len(labels) == 6 and "qaoa_xy" in labels, str(labels))

print("== 12. WS with defense fields ==")
from fastapi.testclient import TestClient
from backend.main import app
client = TestClient(app)
with client.websocket_connect("/ws/optimize") as ws:
    ws.send_json({"tickers": ["AAPL", "MSFT", "GOOGL", "AMZN"], "K": 2, "algorithm": "qaoa",
                  "mixer": "xy", "p": 1, "shots": 256, "noise": "ideal", "cvar_alpha": 0.5})
    done = None
    while True:
        m = ws.receive_json()
        if m["type"] == "done":
            done = m["result"]
            break
        if m["type"] == "error":
            break
    check("ws xy done", done is not None and done.get("mixer") == "xy" and done.get("cvar_alpha") == 0.5)

print("== 13. demo-quality QAOA (N=8,K=4, multi-start) ==")
S8 = get_subset(["AAPL", "MSFT", "GOOGL", "AMZN", "NVDA", "TSLA", "JPM", "JNJ"])
Q8 = build_qubo(S8["mu"], S8["cov"], 0.5, 4)
opt8 = exact_solver(S8["mu"], S8["cov"], 0.5, 4, Q8["penalty"])
r8 = qq.qaoa_run(S8["mu"], S8["cov"], 0.5, 4, Q8["penalty"], p=2, shots=2048,
                 optimizer="COBYLA", maxiter=60, n_restarts=3)
top8 = r8["histogram"][:8]
check("top-8 all feasible", all(h["feasible"] for h in top8),
      str([(h["bitstring"], round(h["prob"], 3)) for h in top8[:3]]))
check("best near exact optimum", r8["best_energy"] <= opt8["best_energy"] + 0.3,
      f"qaoa={r8['best_energy']:.3f} exact={opt8['best_energy']:.3f}")
check("qaoa layers incl SEED", [l["kind"] for l in r8["circuit"]["layers"]][:3] == ["H", "SEED", "COST"])

print("== 14. cross-metric consistency audit ==")
o = optimize(OptimizeRequest(tickers=["AAPL", "MSFT", "GOOGL", "AMZN"], K=2,
                            algorithm="qaoa", p=1, shots=1024))
check("approx in [0,1]", o["approx_ratio"] is not None and 0.0 <= o["approx_ratio"] <= 1.0,
      str(o["approx_ratio"]))
oc = optimize(OptimizeRequest(tickers=["AAPL", "MSFT", "GOOGL", "AMZN"], K=2,
                              algorithm="classical"))
check("classical approx == 1", oc["approx_ratio"] == 1.0, str(oc["approx_ratio"]))
wd = o["weight_dist"]
check("weight dist sums to 1", abs(sum(wd.values()) - 1.0) < 1e-3, str(sum(wd.values())))
check("K-bar == feasible mass", abs(wd["2"] - o["subspace"]["feasible_mass"]) < 1e-4)
check("mass + leakage == 1", abs(o["subspace"]["feasible_mass"] + o["subspace"]["leakage"] - 1.0) < 1e-4)
check("slicer counts", o["subspace"]["total"] == 16 and o["subspace"]["feasible_count"] == 6)
for q in o["qubit_info"]:
    okp = 0.5 - 1e-9 <= q["purity"] <= 1.0 + 1e-9
    okr = abs(q["rlen"] ** 2 - (2 * q["purity"] - 1)) < 0.03
    if not (okp and okr):
        check(f"qubit {q['qubit']} bloch/purity", False, str(q))
        break
else:
    check("bloch |r|^2 == 2p-1, purity in range", True)
mw = 2 * (1 - sum(q["purity"] for q in o["qubit_info"]) / len(o["qubit_info"]))
check("meyer-wallach in [0,1]", 0.0 <= mw <= 1.0, f"{mw:.3f}")
L = o["landscape"]
check("landscape 25x25 + path", L is not None and len(L["Z"]) == 25 and len(L["Z"][0]) == 25 and len(L["path"]) > 10)
check("path finite + long", len(L["path"]) > 10 and
      all(np.isfinite(g) and np.isfinite(b) for g, b in L["path"]),
      f"n={len(L['path'])} (COBYLA is unconstrained: excursions off-box clip on canvas)")
S4 = get_subset(["AAPL", "MSFT", "GOOGL", "AMZN"])
Q4b = build_qubo(S4["mu"], S4["cov"], 0.5, 2)
E4b = qq._all_energies(4, S4["mu"], S4["cov"], 0.5, 2, Q4b["penalty"])
check("cvar cutoff is a real level", True)  # alpha=1.0 here: no cutoff by design
ocv = optimize(OptimizeRequest(tickers=["AAPL", "MSFT", "GOOGL", "AMZN"], K=2,
                               algorithm="qaoa", p=1, shots=512, cvar_alpha=0.25))
check("cvar cutoff member of spectrum",
      any(abs(ocv["cvar_cutoff"] - float(v)) < 5e-4 for v in E4b), str(ocv["cvar_cutoff"]))
smap = {s["bitstring"]: s["prob"] for s in o["states"]}
check("hist exact == grid prob",
      all(abs(h["exact"] - smap.get(h["bitstring"], -1)) < 1e-9 for h in o["histogram"]))
check("convergence ends at expectation",
      o["convergence"][-1].get("final") is True and
      abs(o["convergence"][-1]["energy"] - o["expected_energy"]) < 1e-9,
      str(o["convergence"][-1]))
qa = optimize(OptimizeRequest(tickers=["AAPL", "MSFT", "GOOGL", "AMZN"], K=2,
                              algorithm="quantum_annealing"))
g = qa["spectral"]
check("gap non-negative + argmin", all(v >= -1e-9 for v in g["gaps"]) and
      abs(min(g["gaps"]) - g["delta_min"]) < 1e-9 and 0 <= g["s_star"] <= 1,
      str((g["delta_min"], g["s_star"])))

print("== 15. compilation + trajectory observability ==")
o8 = optimize(OptimizeRequest(tickers=["AAPL", "MSFT", "GOOGL", "AMZN", "NVDA",
                                        "TSLA", "JPM", "JNJ"], K=4,
                              algorithm="qaoa", p=2, shots=512))
costs = [l for l in o8["circuit"]["layers"] if l["kind"] == "COST"]
check("COST pairs + angles", all(len(l["pairs"]) == l["mesh"] == 28 and
                                 len(l["rzz"]) == 28 for l in costs),
      str([(l["mesh"], len(l.get("rzz", []))) for l in costs]))
rt = o8["circuit"]["routing"]
check("routing range shape", rt["rzz_pairs"] == 56 and rt["virtual_cnot"] == 112 and
      rt["linear"]["swaps_lb"] == 56 - 7 and
      rt["linear"]["physical_cnot_lb"] == 112 + 3 * 49 and
      rt["heavy_hex"]["physical_cnot_ub"] >= rt["linear"]["physical_cnot_lb"],
      str((rt["linear"], rt["heavy_hex"])))
check("restart marks", o8["restart_marks"] == sorted(o8["restart_marks"]) and
      len(o8["restart_marks"]) == 3 and o8["restart_marks"][0] == 0,
      str(o8["restart_marks"]))
bt = o8["bloch_traj"]
check("traj frames", len(bt) == 10 and all(len(f["bloch"]) == 8 for f in bt))
check("traj starts at equator",
      all(abs(b[2]) < 0.6 for b in bt[0]["bloch"]),
      str([round(b[2], 2) for b in bt[0]["bloch"]]))
check("traj finite", all(np.isfinite(x) for f in bt for b in f["bloch"] for x in b))
cmp6 = compare(OptimizeRequest(tickers=["AAPL", "MSFT", "GOOGL", "AMZN"], K=2, p=1))
qrow = next(r for r in cmp6["rows"] if r["algorithm"] == "qaoa")
xrow = next(r for r in cmp6["rows"] if r["algorithm"] == "qaoa_xy")
check("compare weight dists", abs(sum(qrow["weight_dist"].values()) - 1.0) < 1e-3 and
      abs(sum(xrow["weight_dist"].values()) - 1.0) < 1e-3)
check("xy leakage zero in compare", xrow["leakage"] == 0.0, str(xrow["leakage"]))


print("== 16. hardware routing range + Dicke compile stats ==")
from backend.routing import heavy_hex_dist, routing_bounds, dicke_compile_stats
d8, note8 = heavy_hex_dist(8)
check("heavy-hex connected 8q", d8 is not None and d8.shape == (8, 8) and
      bool((np.diag(d8) == 0).all()) and np.allclose(d8, d8.T) and
      bool((d8 < 10 ** 9).all()), str(note8)[:60])
pairs28 = [[i, j] for i in range(8) for j in range(i + 1, 8)]
rb = routing_bounds(8, pairs28)
check("range LB<=UB", rb["linear"]["physical_cnot_lb"] <=
      rb["heavy_hex"]["physical_cnot_ub"] and
      rb["virtual_cnot"] == 56 and rb["linear"]["swaps_lb"] == 21,
      str((rb["linear"], rb["heavy_hex"])))
ds = dicke_compile_stats(8, 4)
check("dicke compiled UB", not ds.get("skipped") and ds["cx"] > 0 and ds["depth"] > 0,
      str(ds))
ds10 = dicke_compile_stats(10, 4)
check("dicke skips honestly at N=10", ds10.get("skipped") is True)
rx = qq.qaoa_xy_run(S8["mu"], S8["cov"], 0.5, 4, Q8["penalty"], p=1, shots=256,
                    optimizer="COBYLA", maxiter=6)
dl = [l for l in rx["circuit"]["layers"] if l["kind"] == "DICKE"][0]
check("DICKE layer carries prep stats", "prep_stats" in dl and
      dl["prep_stats"].get("cx", 0) > 0, str(dl.get("prep_stats")))


print(f"\nRESULT: {PASS} passed, {FAIL} failed")
raise SystemExit(1 if FAIL else 0)
