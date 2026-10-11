"""Deep verification: all solvers x optimizers, fallback sim, edges, WS stream."""
import itertools
import numpy as np

from backend.market import get_universe, get_subset, get_price_history
from backend.qubo import build_qubo, qubo_to_ising
from backend.classical import exact_solver, simulated_annealing, simulated_quantum_annealing, flow_diagram
from backend.finance import backtest, inv_vol_weights
from backend import quantum_qiskit as qq
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

UNI = ["AAPL", "MSFT", "GOOGL", "AMZN", "NVDA", "TSLA"]
K = 2

def sub(tickers):
    s = get_subset(tickers)
    return s["mu"], s["cov"], s["sigma"]

print("== 1. all algos x optimizers (N=6,K=2,p=1,short budget) ==")
mu, cov, sig = sub(UNI)
Q = build_qubo(mu, cov, 0.5, K)
base = exact_solver(mu, cov, 0.5, K, Q["penalty"])
print(f"   exact baseline: {base['best_bitstring']} E={base['best_energy']:.3f}")
for algo, fn in [("qaoa", qq.qaoa_run), ("vqe", qq.vqe_run)]:
    for opt in ["COBYLA", "SPSA"]:
        r = fn(mu, cov, 0.5, K, Q["penalty"], p=1, shots=256, optimizer=opt, maxiter=6)
        feas = sum(int(b) for b in r["best_bitstring"]) == K
        check(f"{algo}/{opt} feasible={r['best_bitstring']}", feas)
        check(f"{algo}/{opt} hist+conv", len(r["histogram"]) > 0 and len(r["convergence"]) > 0)
        check(f"{algo}/{opt} layers", len(r["circuit"]["layers"]) > 0)
for algo, fn in [("sa", simulated_annealing), ("qa", simulated_quantum_annealing)]:
    r = fn(mu, cov, 0.5, K, Q["penalty"], steps=500, seed=1)
    check(f"{algo} feasible={r['best_bitstring']}", sum(int(b) for b in r["best_bitstring"]) == K)
    check(f"{algo} visit-histogram", len(r["histogram"]) > 0)
    check(f"{algo} streamed-history", len(r["history"]) > 0)

print("== 2. on_step streaming callbacks ==")
seen = []
r = qq.qaoa_run(mu, cov, 0.5, K, Q["penalty"], p=1, shots=256, optimizer="COBYLA", maxiter=4, on_step=seen.append)
check("qaoa on_step fired", len(seen) > 0, f"got {len(seen)}")
seen2 = []
simulated_annealing(mu, cov, 0.5, K, Q["penalty"], steps=400, seed=1, on_step=seen2.append)
check("anneal on_step fired", len(seen2) > 0, f"got {len(seen2)}")

print("== 3. numpy fallback (no qiskit) ==")
old = qq.HAS_QISKIT
qq.HAS_QISKIT = False
try:
    r = qq.qaoa_run(mu, cov, 0.5, K, Q["penalty"], p=1, shots=256, optimizer="COBYLA", maxiter=4)
    check("fallback qaoa", r["backend"].startswith("numpy") and len(r["histogram"]) > 0, r["backend"])
    r = qq.vqe_run(mu, cov, 0.5, K, Q["penalty"], p=1, shots=256, optimizer="COBYLA", maxiter=4)
    check("fallback vqe", r["backend"].startswith("numpy") and len(r["histogram"]) > 0, r["backend"])
finally:
    qq.HAS_QISKIT = old

print("== 4. edge universes ==")
for tickers, k in [(["AAPL", "MSFT", "JPM"], 1), (["AAPL", "MSFT", "JPM"], 3),
                   (["AAPL", "MSFT", "GOOGL", "AMZN", "NVDA", "TSLA", "META", "JPM", "JNJ", "AMD"], 5)]:
    m2, c2, s2 = sub(tickers)
    Q2 = build_qubo(m2, c2, 0.5, k)
    b2 = exact_solver(m2, c2, 0.5, k, Q2["penalty"])
    check(f"N={len(tickers)},K={k} -> {b2['best_bitstring']}", sum(int(x) for x in b2["best_bitstring"]) == k)
    r2 = qq.qaoa_run(m2, c2, 0.5, k, Q2["penalty"], p=1, shots=256, optimizer="COBYLA", maxiter=4)
    check(f"  qaoa layers={len(r2['circuit']['layers'])}", len(r2["circuit"]["layers"]) == 4)

print("== 5. invalid inputs rejected ==")
def expect_400(name, **kw):
    try:
        validate_request(OptimizeRequest(**kw))
        check(name, False, "no error raised")
    except (HTTPException, ValueError):
        check(name, True)
expect_400("K=0", tickers=UNI, K=0)
expect_400("K>N", tickers=UNI, K=99)
expect_400("unknown ticker", tickers=["AAPL", "MSFT", "FAKE"], K=2)
expect_400("duplicates", tickers=["AAPL", "AAPL", "MSFT"], K=2)
expect_400("too few", tickers=["AAPL", "MSFT"], K=1)
expect_400("bad rebalance", tickers=UNI, K=2, rebalance="weekly")

print("== 6. walk-forward backtest ==")
h = get_price_history(UNI)
w = inv_vol_weights(list(sig))
bhold = backtest("110000", UNI, w[:2], h, mode="buy_hold")
bwlk = backtest("110000", UNI, w[:2], h, mode="monthly")
check("buy_hold curves", len(bhold["portfolio_curve"]) == 200 and bhold["turnover_pct"] == 0.0)
check("monthly turnover>0", bwlk["turnover_pct"] > 0, str(bwlk["turnover_pct"]))
check("monthly metrics", bwlk["metrics_port"].get("sharpe") is not None)

print("== 7. flow diagrams ==")
for kind in ["classical", "annealing", "quantum_annealing"]:
    f = flow_diagram(kind, 8, 4, "11110000")
    check(f"flow {kind}", f["type"] == "flow" and len(f["stages"]) == 4 and all("label" in s and "detail" in s for s in f["stages"]))

print("== 8. REST optimize/compare incl. rebalance ==")
req = OptimizeRequest(tickers=UNI, K=2, risk_q=0.5, algorithm="classical", rebalance="monthly")
out = optimize(req)
check("optimize keys", all(k in out for k in ["summary", "circuit", "histogram", "convergence", "frontier", "math", "turnover_pct", "rebalance"]))
check("optimize turnover", out["turnover_pct"] > 0 and out["rebalance"] == "monthly")
cmp_out = compare(OptimizeRequest(tickers=UNI, K=2, risk_q=0.5, algorithm="qaoa", p=1))
check("compare 6 rows", len(cmp_out["rows"]) == 6, str(len(cmp_out["rows"])))

print("== 9. universe last/chg ==")
assets, _ = get_universe()
check("last+chg present", all("last" in a and "chg_pct" in a for a in assets) and len(assets) == 10)

print("== 10. websocket live stream ==")
from fastapi.testclient import TestClient
from backend.main import app
client = TestClient(app)
with client.websocket_connect("/ws/optimize") as ws:
    ws.send_json({"tickers": UNI, "K": 2, "risk_q": 0.5, "algorithm": "qaoa",
                  "p": 1, "shots": 512, "optimizer": "COBYLA"})
    got_base, n_prog, done = False, 0, None
    while True:
        m = ws.receive_json()
        if m["type"] == "baseline":
            got_base = "classical_energy" in m
        elif m["type"] == "progress":
            n_prog += 1
        elif m["type"] == "done":
            done = m["result"]
            break
        elif m["type"] == "error":
            break
    check("ws baseline", got_base)
    check("ws progress msgs", n_prog > 3, f"got {n_prog}")
    check("ws done+summary", done is not None and "summary" in done and len(done["circuit"]["layers"]) == 4)

print(f"\nRESULT: {PASS} passed, {FAIL} failed")
raise SystemExit(1 if FAIL else 0)
