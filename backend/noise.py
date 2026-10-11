"""NISQ realism: Eagle-like noise model, noisy shot evaluation, ZNE folding.

Honest design: the variational loop stays on the ideal statevector (fast),
then the FINAL circuit is executed on AerSimulator under an IBM-Eagle-like
noise profile. ZNE folds only 2-qubit gates (standard local folding).
"""
from __future__ import annotations
import numpy as np

EAGLE_PROFILE = {
    "name": "IBM-Eagle-like (127q class)",
    "p1_depol": 1e-3,      # 1-qubit depolarizing rate
    "p2_depol": 1e-2,      # 2-qubit (CNOT-class) depolarizing rate
    "T1_us": 100.0,        # thermal relaxation
    "T2_us": 80.0,         # dephasing
    "t1q_ns": 50.0,        # 1q gate time
    "t2q_ns": 300.0,       # 2q gate time
    "readout_flip": 0.02,  # P(0|1) = P(1|0)
}

_NOISE_CACHE = {}


def get_noise_model(mode="ideal"):
    """Return (NoiseModel | None). Cached per mode."""
    if mode != "eagle":
        return None
    if "eagle" in _NOISE_CACHE:
        return _NOISE_CACHE["eagle"]
    from qiskit_aer.noise import (NoiseModel, depolarizing_error,
                                  thermal_relaxation_error, ReadoutError)
    p = EAGLE_PROFILE
    model = NoiseModel(basis_gates=["h", "rx", "ry", "rz", "rzz", "rxx", "ryy", "cx", "id", "x"])
    err1 = depolarizing_error(p["p1_depol"], 1).compose(
        thermal_relaxation_error(p["T1_us"] * 1e-6, p["T2_us"] * 1e-6, p["t1q_ns"] * 1e-9))
    err2 = depolarizing_error(p["p2_depol"], 2).compose(
        thermal_relaxation_error(p["T1_us"] * 1e-6, p["T2_us"] * 1e-6, p["t2q_ns"] * 1e-9).tensor(
            thermal_relaxation_error(p["T1_us"] * 1e-6, p["T2_us"] * 1e-6, p["t2q_ns"] * 1e-9)))
    model.add_all_qubit_quantum_error(err1, ["h", "rx", "ry", "rz", "x", "id"])
    model.add_all_qubit_quantum_error(err2, ["rzz", "rxx", "ryy", "cx"])
    ro = ReadoutError([[1 - p["readout_flip"], p["readout_flip"]],
                       [p["readout_flip"], 1 - p["readout_flip"]]])
    model.add_all_qubit_readout_error(ro)
    _NOISE_CACHE["eagle"] = model
    return model


def run_noisy(qc, n, E, K, shots=2048, seed=42):
    """Execute circuit (no measurements) on noisy AerSimulator. Real shot noise."""
    from qiskit_aer import AerSimulator
    model = get_noise_model("eagle")
    qcm = qc.copy()
    qcm.measure_all()
    sim = AerSimulator(noise_model=model, seed_simulator=seed)
    result = sim.run(qcm, shots=shots).result()
    counts = result.get_counts()
    total = sum(counts.values()) or 1
    # qiskit keys read q_{n-1}..q_0 left-to-right; display char i = ticker i.
    hist = []
    for key, cnt in counts.items():
        beads = key.replace(" ", "")
        k = int(beads, 2)  # qubit m = bit m: matches _all_energies indexing
        bits = "".join(str((k >> i) & 1) for i in range(n))
        hist.append({"bitstring": bits, "count": int(cnt), "_k": k,
                     "prob": round(cnt / total, 4),
                     "feasible": sum(int(b) for b in bits) == K,
                     "energy": round(float(E[k]), 4)})
    hist.sort(key=lambda d: d["count"], reverse=True)
    energy = float(sum(E[d["_k"]] * d["count"] for d in hist) / total)
    feas_rate = round(sum(d["count"] for d in hist if d["feasible"]) / total, 4)
    for d in hist:
        del d["_k"]
    feas_rate = round(sum(d["count"] for d in hist if d["feasible"]) / total, 4)
    return {"energy": round(energy, 4), "histogram": hist[:10],
            "feasibility_rate": feas_rate, "shots": shots}


def fold_two_qubit(qc, scale=3):
    """Local unitary folding: G -> G (G† G)^((s-1)/2) for each 2q gate."""
    assert scale % 2 == 1 and scale >= 1
    reps = (scale - 1) // 2
    if reps == 0:
        return qc.copy()
    new = qc.copy()
    new.data.clear()
    for instr in qc.data:
        new.append(instr.operation, instr.qubits, instr.clbits)
        if instr.operation.name in ("rzz", "rxx", "ryy", "cx") and len(instr.qubits) == 2:
            theta = float(instr.operation.params[0]) if instr.operation.params else 0.0
            for _ in range(reps):
                new.append(instr.operation.inverse()
                           if hasattr(instr.operation, "inverse") else instr.operation,
                           instr.qubits)
                new.append(instr.operation, instr.qubits)
    _ = theta
    return new


def zne_mitigate(make_qc, E, n, K, shots=1024, seed=42, scales=(1, 3, 5)):
    """Run folded circuits under noise, linearly extrapolate E(scale->0)."""
    pts = []
    for s in scales:
        qc = fold_two_qubit(make_qc(), s)
        r = run_noisy(qc, n, E, K, shots=shots, seed=seed + s)
        pts.append({"scale": s, "energy": r["energy"]})
    xs = np.array([p["scale"] for p in pts], float)
    ys = np.array([p["energy"] for p in pts], float)
    slope, intercept = np.polyfit(xs, ys, 1)
    return {"points": [{"scale": int(x), "energy": round(float(y), 4)}
                       for x, y in zip(xs, ys)],
            "mitigated": round(float(intercept), 4),
            "slope": round(float(slope), 4), "shots_each": shots}
