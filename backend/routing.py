"""Physical-hardware routing bounds + Dicke preparation compile stats.

Routing is reported as a RANGE, never a single invented number:
  * linear chain lower bound  (theorem: non-adjacent pairs need >=1 SWAP)
  * heavy-hex independent-pair upper bound (no SWAP sharing/cancellation)

Dicke stats come from a real level-0 basis unrolling (upper bound by
construction); skipped honestly when synthesis is too heavy (N > 8).
"""
from __future__ import annotations
import numpy as np

_HEAVY_CACHE: dict = {}


def heavy_hex_dist(n):
    """All-pairs shortest-path distances for n physical qubits on heavy-hex.

    Returns (dist n x n, note) or (None, reason). Physical qubits are the n
    most central connected qubits of a 3-shell heavy-hex patch (BFS order
    from the graph center = min total distance). Deterministic.
    """
    if n in _HEAVY_CACHE:
        return _HEAVY_CACHE[n]
    try:
        from qiskit.transpiler import CouplingMap
        from collections import deque
        cm = CouplingMap.from_heavy_hex(3)
        size = cm.size()
        INF = 10 ** 9
        D = np.full((size, size), INF)
        np.fill_diagonal(D, 0)
        adj = [[] for _ in range(size)]
        for a, b in cm.get_edges():
            D[a, b] = D[b, a] = 1
            adj[a].append(b)
            adj[b].append(a)
        for m in range(size):  # Floyd-Warshall (patch is small)
            D = np.minimum(D, D[:, [m]] + D[[m], :])
        center = int(np.argmin(D.sum(axis=1)))
        seen, order = {center}, deque([center])
        while order and len(seen) < n * 4:
            u = order.popleft()
            for v in adj[u]:
                if v not in seen:
                    seen.add(v)
                    order.append(v)
        # most central n of the BFS ball
        ball = sorted(seen, key=lambda v: D[center, v])[:max(n, 1)]
        cand = sorted(ball, key=lambda v: D[np.ix_(ball, ball)].sum(axis=1)[ball.index(v)])[:n]
        sub = D[np.ix_(cand, cand)]
        if not np.all(sub < INF):
            _HEAVY_CACHE[n] = (None, "heavy-hex patch disconnected for selection")
            return _HEAVY_CACHE[n]
        _HEAVY_CACHE[n] = (sub, f"{n} most-central qubits of Eagle-class heavy-hex patch")
        return _HEAVY_CACHE[n]
    except Exception as e:
        _HEAVY_CACHE[n] = (None, f"heavy-hex unavailable: {e}")
        return _HEAVY_CACHE[n]


def routing_bounds(n_qubits, rzz_pair_list, cx_pairs=0):
    """Virtual vs routed CNOT range from the ACTUAL interaction pairs.

    rzz_pair_list: [[i, j], ...] that need an RZZ (CNOT-RZ-CNOT each).
    Linear lower bound (theorem): on a line, non-adjacent pairs need >=1 SWAP.
    Heavy-hex upper bound: identity-mapped pairs routed independently on real
    Eagle-class distances (no SWAP sharing/cancellation credited).
    """
    rzz = len(rzz_pair_list)
    virt = 2 * rzz + cx_pairs
    lin_swaps = max(rzz - (n_qubits - 1), 0)  # line holds <= n-1 adjacent pairs
    out = {"rzz_pairs": rzz, "cx_pairs": cx_pairs, "virtual_cnot": virt,
           "linear": {"swaps_lb": lin_swaps, "physical_cnot_lb": virt + 3 * lin_swaps,
                      "topology": "linear chain (lower bound)"},
           "heavy_hex": None,
           "note": "RZZ=CNOT-RZ-CNOT (2 CNOTs); SWAP=3 CNOTs; XY pairs excluded (native RXX/RYY)"}
    dist, note = heavy_hex_dist(n_qubits)
    if dist is not None:
        swaps = sum(max(int(dist[min(i, j) % n_qubits, max(i, j) % n_qubits]) - 1, 0)
                    for i, j in rzz_pair_list)
        out["heavy_hex"] = {
            "swaps_ub": int(swaps), "physical_cnot_ub": int(virt + 3 * swaps),
            "topology": "heavy-hex Eagle-class (independent-pair upper bound)",
            "selection": note}
    return out


_DICKE_CACHE: dict = {}


def dicke_compile_stats(n, K):
    """Unoptimized basis unrolling of Dicke(N,K) prep (upper bound).

    Uses level-0 transpile to ['rx','ry','rz','cx'] — no optimization passes,
    so counts can only overstate an optimized synthesis. Skipped for N > 8.
    """
    key = (n, K)
    if key in _DICKE_CACHE:
        return _DICKE_CACHE[key]
    if n > 8:
        _DICKE_CACHE[key] = {"skipped": True,
                             "reason": f"N={n}: unitary synthesis too heavy for live demo (N<=8 only)."}
        return _DICKE_CACHE[key]
    try:
        from qiskit import QuantumCircuit, transpile
        from .quantum_qiskit import _dicke_vector
        qc = QuantumCircuit(n)
        qc.initialize(_dicke_vector(n, K), list(range(n)))
        t = transpile(qc, basis_gates=["rx", "ry", "rz", "cx"],
                      optimization_level=0)
        ops = t.count_ops()
        res = {"skipped": False, "cx": int(ops.get("cx", 0)),
               "single_q": int(sum(ops.get(g, 0) for g in ("rx", "ry", "rz"))),
               "depth": int(t.depth()),
               "method": "level-0 basis unrolling (upper bound; optimized synthesis uses fewer)"}
        _DICKE_CACHE[key] = res
        return res
    except Exception as e:
        _DICKE_CACHE[key] = {"skipped": True, "reason": f"synthesis failed: {e}"}
        return _DICKE_CACHE[key]
