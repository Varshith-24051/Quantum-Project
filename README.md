# Q-TERMINAL: Quantum Portfolio Optimization Platform

[![Python](https://img.shields.io/badge/Python-3.10%2B-blue.svg)](https://www.python.org/)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.110%2B-009688.svg)](https://fastapi.tiangolo.com/)
[![Qiskit](https://img.shields.io/badge/Qiskit-1.0%2B-6929C4.svg)](https://qiskit.org/)
[![Qiskit Aer](https://img.shields.io/badge/Qiskit--Aer-0.14%2B-purple.svg)](https://github.com/Qiskit/qiskit-aer)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Status: Production--Grade](https://img.shields.io/badge/Verification-105%2F105%20Passed-brightgreen.svg)]()

> **A Bloomberg-Terminal-grade, full-stack quantum computing platform for discrete Markowitz portfolio optimization.**  
> Features live variational quantum algorithms (QAOA, QAOA-XY, VQE), classical MIQP & simulated annealing baselines, realistic IBM Eagle hardware noise emulation, Zero-Noise Extrapolation (ZNE), CVaR tail risk objectives, and live market data ingestion via Yahoo Finance.

---

## 📑 Table of Contents

- [Overview](#-overview)
- [Key Features](#-key-features)
- [System Architecture](#-system-architecture)
- [Mathematical Formulation](#-mathematical-formulation)
  - [1. Classical Constrained Markowitz Model](#1-classical-constrained-markowitz-model)
  - [2. QUBO Formulation with Penalty Scaling](#2-qubo-formulation-with-penalty-scaling)
  - [3. Mapping QUBO to Ising Spin Hamiltonian](#3-mapping-qubo-to-ising-spin-hamiltonian)
  - [4. Quantum Variational Ansatz & Mixers](#4-quantum-variational-ansatz--mixers)
- [Algorithm & Solver Suite](#-algorithm--solver-suite)
- [NISQ Realism & Quantum Observability](#-nisq-realism--quantum-observability)
  - [IBM Eagle Noise Emulation](#ibm-eagle-noise-emulation)
  - [Zero-Noise Extrapolation (ZNE)](#zero-noise-extrapolation-zne)
  - [Hardware Routing & Transpilation Bounds](#hardware-routing--transpilation-bounds)
  - [Bloch Sphere Vector & Purity Diagnostics](#bloch-sphere-vector--purity-diagnostics)
- [Financial Analytics & Data Pipeline](#-financial-analytics--data-pipeline)
- [Project Structure](#-project-structure)
- [Getting Started](#-getting-started)
  - [Prerequisites](#prerequisites)
  - [Installation](#installation)
  - [Running the Platform](#running-the-platform)
- [REST API & WebSocket Reference](#-rest-api--websocket-reference)
- [Verification & Test Suite](#-verification--test-suite)
- [License](#-license)

---

## 🌟 Overview

Portfolio optimization in modern quantitative finance requires selecting an optimal subset of assets from an investment universe to maximize expected return while minimizing portfolio variance. When discrete cardinality constraints are enforced (e.g., holding exactly $K$ assets with binary selection variables $x_i \in \{0, 1\}$), the problem transitions from continuous quadratic programming into an **NP-hard Mixed-Integer Quadratic Programming (MIQP)** problem.

**Q-TERMINAL** provides a transparent, dual-stack experimental platform that bridges quantum algorithms with financial engineering. The platform maps combinatorial portfolio selection directly onto quantum spin systems, executes variational circuits on Qiskit simulators with realistic hardware noise models, and evaluates results against rigorous classical benchmarks.

---

## 🚀 Key Features

- **Variational Quantum Solvers**:
  - **QAOA (Quantum Approximate Optimization Algorithm)** with parameter depth $p$, multi-start deterministic restarts, and symmetry-breaking seed layers.
  - **QAOA-XY Subspace Mixer**: Enforces exact cardinality conservation via Dicke state $|D_K^N\rangle$ initialization and planar $XY$ ring mixers—yielding **0% subspace leakage** and **100% feasibility by construction**.
  - **VQE (Variational Quantum Eigensolver)** parameterized with `EfficientSU2` ansatz ($R_y / R_z$ rotations and entangling CNOT chains).
- **Comprehensive Classical Benchmarks**:
  - Deterministic **Exact MIQP** ($2^N$ combinatorial branch-and-bound verification).
  - Thermal **Simulated Annealing (SA)** with Metropolis-Hastings transition acceptance.
  - **Simulated Quantum Annealing (SQA)** modeling transverse-field quantum tunneling moves.
- **NISQ Hardware Realism**:
  - IBM Eagle 127-qubit noise profile (depolarizing errors, $T_1=100\mu\text{s}$, $T_2=80\mu\text{s}$ thermal relaxation, and readout flip probabilities).
  - **Zero-Noise Extrapolation (ZNE)** with local two-qubit gate folding ($\lambda = 1, 3, 5$) and Richardson linear extrapolation.
  - Physical compilation bounds: Linear-chain lower bounds and heavy-hex Eagle topology coupling map upper bounds.
- **Advanced Quantitative Analytics**:
  - **CVaR-$\alpha$ Tail Risk**: Variational expectation optimized over the lowest $\alpha$-quantile states ($100\%, 50\%, 25\%, 10\%$).
  - **Multi-Source Data Ingestion**: Deterministic calibrated mock market, live **Yahoo Finance** ticker streams, and custom **CSV upload**.
  - **Ledoit-Wolf Shrinkage**: Guarantees well-conditioned, positive-definite covariance matrices on real-world asset returns.
  - **Full Backtesting Engine**: Buy-and-Hold vs. Monthly Walk-Forward rebalancing with transaction turnover penalties, Sharpe, Sortino, and Max Drawdown metrics.
- **Bloomberg-Terminal Interface**:
  - Zero-dependency, offline-capable, amber-on-black terminal UI.
  - Real-time WebSocket streaming of variational convergence traces.
  - Interactive Bloch sphere projections, dynamic Hilbert subspace slicers, and animated quantum circuit schematics.
  - One-click exportable **Printable Faculty Dossier (PDF/Print)**.

---

## 🏗 System Architecture

```text
┌────────────────────────────────────────────────────────────────────────┐
│                   BROWSER CLIENT (Terminal UI)                         │
│  - Zero-dependency Vanilla JS & CSS      - Live WebSocket Streaming    │
│  - Dynamic Ticker Tape & Setup Heatmap   - Interactive Bloch Carousel  │
│  - Circuit Transpilation Unrolling       - Printable Faculty Dossier   │
└───────────────────────────────────┬────────────────────────────────────┘
                                    │ HTTP / WebSocket (/ws/optimize)
                                    ▼
┌────────────────────────────────────────────────────────────────────────┐
│                      FASTAPI BACKEND (Python)                          │
│  - Schema Validation (Pydantic)          - SQLite Run History DB       │
│  - Dataset & CSV Ingestion Pipeline      - Result Packaging            │
└─────────┬─────────────────────────┬──────────────────────────┬─────────┘
          │                         │                          │
          ▼                         ▼                          ▼
┌──────────────────┐      ┌──────────────────┐      ┌────────────────────┐
│  DATA & FINANCE  │      │  MATHEMATICAL    │      │  CLASSICAL SUITE   │
│  - Yahoo Finance │      │  MAPPING         │      │  - Exact 2^N MIQP  │
│  - Ledoit-Wolf   │      │  - Markowitz     │      │  - Simulated       │
│  - Backtesting   │      │  - QUBO Matrix   │      │    Annealing       │
│  - Frontier Gen  │      │  - Ising Spin H  │      │  - Quantum Proxy   │
└──────────────────┘      └─────────┬────────┘      └────────────────────┘
                                    │
                                    ▼
┌────────────────────────────────────────────────────────────────────────┐
│                       QUANTUM COMPUTING ENGINE                         │
│  ┌──────────────────────────────────────────────────────────────────┐  │
│  │ Qiskit Statevector / NumPy Fallback Simulator                    │  │
│  │  - QAOA (Cost RZ/RZZ + RX Mixer)                                 │  │
│  │  - QAOA-XY (Dicke State Init + Ring XY Preserving Mixer)         │  │
│  │  - VQE (EfficientSU2 Parameterized Ansatz)                       │  │
│  │  - Multi-Start Seed Optimization (COBYLA / SPSA)                 │  │
│  └────────────────────────────────┬─────────────────────────────────┘  │
│                                   │                                    │
│  ┌────────────────────────────────▼─────────────────────────────────┐  │
│  │ NISQ Realism & Error Mitigation                                  │  │
│  │  - Qiskit Aer Noise Model (IBM Eagle: Depolarizing, T1/T2, Read) │  │
│  │  - Zero-Noise Extrapolation (ZNE Gate Folding λ=1,3,5)           │  │
│  │  - Heavy-Hex Topology Routing & CNOT Compilation Bounds          │  │
│  └──────────────────────────────────────────────────────────────────┘  │
└────────────────────────────────────────────────────────────────────────┘
```

---

## 📐 Mathematical Formulation

### 1. Classical Constrained Markowitz Model

Given a universe of $N$ assets with expected annual return vector $\boldsymbol{\mu} \in \mathbb{R}^N$ and covariance matrix $\boldsymbol{\Sigma} \in \mathbb{R}^{N \times N}$, the portfolio selection is parameterized by binary decision variables $\mathbf{x} = [x_1, \dots, x_N]^T \in \{0, 1\}^N$, where $x_i = 1$ indicates asset inclusion.

The risk-return trade-off under a risk aversion parameter $q \in [0, 1]$ and cardinality constraint $K$ is:

$$\min_{\mathbf{x} \in \{0, 1\}^N} \quad q \, \mathbf{x}^T \boldsymbol{\Sigma} \mathbf{x} - \boldsymbol{\mu}^T \mathbf{x} \quad \text{subject to} \quad \sum_{i=1}^N x_i = K$$

### 2. QUBO Formulation with Penalty Scaling

To map this constrained program into an unconstrained objective suitable for quantum optimization, the cardinality equality constraint is incorporated as an $L_2$ quadratic penalty term:

$$H_{\text{QUBO}}(\mathbf{x}) = q \, \mathbf{x}^T \boldsymbol{\Sigma} \mathbf{x} - \boldsymbol{\mu}^T \mathbf{x} + P \left( \sum_{i=1}^N x_i - K \right)^2$$

Expanding the penalty:

$$\left( \sum_{i=1}^N x_i - K \right)^2 = \sum_{i=1}^N (1 - 2K) x_i + 2 \sum_{i < j} x_i x_j + K^2$$

The symmetric QUBO matrix $\mathbf{Q} \in \mathbb{R}^{N \times N}$ is formulated such that $H_{\text{QUBO}}(\mathbf{x}) = \mathbf{x}^T \mathbf{Q} \mathbf{x} + P K^2$:
- **Diagonal elements**: $Q_{ii} = q \, \Sigma_{ii} - \mu_i + P (1 - 2K)$
- **Off-diagonal elements ($i \neq j$)**: $Q_{ij} = q \, \Sigma_{ij} + P$

The penalty scale $P$ is auto-tuned to guarantee that any state with $\sum x_i \neq K$ has higher energy than any feasible state:

$$P \ge 1.5 \left( q \cdot N \cdot \max_{i,j}|\Sigma_{ij}| + \max_i |\mu_i| \right) + 0.5$$

### 3. Mapping QUBO to Ising Spin Hamiltonian

Binary variables $x_i \in \{0, 1\}$ are mapped to spin variables $s_i \in \{-1, +1\}$ and quantum Pauli-$Z$ observables via:

$$x_i = \frac{I - Z_i}{2}$$

Substituting this transformation into the quadratic form produces the problem cost Hamiltonian $H_C$:

$$H_C = \sum_{i=1}^N h_i Z_i + \sum_{i < j} J_{ij} Z_i Z_j + C_{\text{offset}} I$$

Where the longitudinal fields $h_i$ and coupling constants $J_{ij}$ are:

$$h_i = -\frac{Q_{ii}}{2} - \sum_{j \neq i} \frac{Q_{ij}}{4}$$

$$J_{ij} = \frac{Q_{ij}}{4}$$

$$C_{\text{offset}} = \sum_{i=1}^N \frac{Q_{ii}}{2} + \sum_{i < j} \frac{Q_{ij}}{4} + P K^2$$

### 4. Quantum Variational Ansatz & Mixers

#### Standard QAOA
The standard QAOA circuit alternates between the cost Hamiltonian $H_C$ and a non-commuting transverse field mixer $H_M = \sum_{i=1}^N X_i$ for $p$ layers:

$$|\psi(\boldsymbol{\gamma}, \boldsymbol{\beta})\rangle = \prod_{l=1}^p e^{-i \beta_l H_M} e^{-i \gamma_l H_C} |+\rangle^{\otimes N}$$

#### QAOA-XY Subspace Mixer (Penalty-Free)
Instead of penalizing off-cardinality states in the cost function, the XY mixer restricts the variational search strictly to the subspace of Hamming weight $K$, denoted $\mathcal{S}_K = \{|\mathbf{x}\rangle : \sum x_i = K\}$.
1. **Initial State**: Symmetrically prepares the Dicke state $|D_K^N\rangle = \binom{N}{K}^{-1/2} \sum_{\mathbf{x} \in \mathcal{S}_K} |\mathbf{x}\rangle$.
2. **Mixer Hamiltonian**: Generates planar XY exchange interactions over a 1D closed ring topology:
   $$H_{XY} = \frac{1}{2} \sum_{i=1}^N \left( X_i X_{i+1} + Y_i Y_{i+1} \right) \quad (\text{with } N+1 \equiv 1)$$
   Because $[H_{XY}, \sum Z_i] = 0$, every single execution step is **100% feasible by construction**.

---

## 🧪 Algorithm & Solver Suite

| Solver | Paradigm | Ansatz / Architecture | Constraint Enforcement | Subspace Feasibility |
| :--- | :--- | :--- | :--- | :--- |
| **Classical Exact** | Deterministic MIQP | Exhaustive $2^N$ combinatorial branch & bound | Hard check | 100% |
| **Simulated Annealing** | Classical Heuristic | Thermal Metropolis-Hastings Markov Chain | Soft QUBO penalty | $\ge 95\%$ |
| **Quantum Annealing** | Simulated Adiabatic | Transverse tunneling field schedule | Soft Ising penalty | $\ge 95\%$ |
| **Standard QAOA** | Variational Quantum | Cost $R_Z / R_{ZZ}$ mesh + $R_X$ mixer ($p \in [1, 4]$) | Soft QUBO penalty + Seed layer | $85\% - 98\%$ |
| **QAOA-XY** | Subspace Quantum | Dicke $|D_K^N\rangle$ init + Ring $XY$ mixer ($p \in [1, 4]$) | Subspace-preserving mixer | **100% Exact** |
| **VQE** | Variational Quantum | `EfficientSU2` ($R_y, R_z$ + full entangling CNOT chain) | Soft Ising penalty | $75\% - 95\%$ |

---

## 🔬 NISQ Realism & Quantum Observability

### IBM Eagle Noise Emulation
While variational optimization is trained on ideal statevectors for high-speed convergence, the final parameterized circuit is deployed onto `qiskit_aer.AerSimulator` under an emulated **IBM Eagle 127-qubit** noise model:
- **1-Qubit Depolarizing Error**: $p_1 = 1.0 \times 10^{-3}$
- **2-Qubit Depolarizing Error**: $p_2 = 1.0 \times 10^{-2}$
- **Thermal Relaxation**: $T_1 = 100\,\mu\text{s}, \quad T_2 = 80\,\mu\text{s}$
- **Gate Durations**: $t_{1q} = 50\,\text{ns}, \quad t_{2q} = 300\,\text{ns}$
- **Readout Bit-Flip Probability**: $P(0|1) = P(1|0) = 2.0\%$

### Zero-Noise Extrapolation (ZNE)
To mitigate coherent gate errors on physical NISQ processors without requiring full quantum error correction, Q-TERMINAL implements **Local Unitary Gate Folding**:

Each two-qubit gate $G \in \{R_{ZZ}, \text{CX}\}$ is scaled by noise factor $\lambda \in \{1, 3, 5\}$:

$$G \;\longrightarrow\; G \left( G^\dagger G \right)^{\frac{\lambda - 1}{2}}$$

Expected energies $\langle H_C \rangle_\lambda$ are measured at each noise scale, and a Richardson linear polynomial fit extrapolates the expectation back to the ideal zero-noise limit $E(\lambda \to 0)$.

### Hardware Routing & Transpilation Bounds
Circuits designed on all-to-all logical connectivity must be transpiled onto physical sparse coupling maps. The platform computes exact hardware compile ranges:
1. **Linear Chain Lower Bound (Theorem)**: On a 1D chain of $N$ qubits, any interaction mesh with non-adjacent pairs requires at least $\max(0, |E| - (N-1))$ SWAP gates ($3\text{ CNOTs}$ per SWAP).
2. **Heavy-Hex Eagle Upper Bound**: Evaluates all-pairs shortest path distances $d(q_i, q_j)$ on the 127-qubit heavy-hex coupling map to calculate independent routing overhead without gate cancellation credits.

### Bloch Sphere Vector & Purity Diagnostics
For every asset qubit $m \in \{1, \dots, N\}$, the platform computes the single-qubit reduced density matrix $\rho_m = \text{Tr}_{\bar{m}}(|\psi\rangle\langle\psi|)$:

$$\rho_m = \frac{1}{2} \left( I + \mathbf{r}_m \cdot \boldsymbol{\sigma} \right), \quad \mathbf{r}_m = (r_x, r_y, r_z) \in \mathbb{R}^3$$

From $\rho_m$, the platform calculates:
- **Purity**: $\gamma_m = \text{Tr}(\rho_m^2) = \frac{1 + |\mathbf{r}_m|^2}{2} \in [0.5, 1.0]$
- **von Neumann Entropy**: $S_{\text{vN}}(\rho_m) = -\text{Tr}(\rho_m \ln \rho_m)$ (quantifying bipartite entanglement between asset $m$ and the rest of the portfolio)

---

## 📊 Financial Analytics & Data Pipeline

1. **Market Universe Data Sources**:
   - **Calibrated Deterministic Mock**: 10 blue-chip assets with realistic sector correlation blocks (Tech-Tech $\sim 0.70$, Financials $\sim 0.45$, Healthcare $\sim 0.30$) with guaranteed positive-definite covariance.
   - **Live Yahoo Finance API**: Real-time daily adjusted closes for any user-specified ticker set.
   - **User CSV File Ingestion**: Upload any historical time-series with automatic date parsing and return calculation.
2. **Ledoit-Wolf Shrinkage**:
   When sample size $T$ is comparable to asset count $N$, sample covariance $\mathbf{S}$ becomes ill-conditioned. The engine applies optimal shrinkage toward the constant correlation target $\mathbf{F}$:
   $$\boldsymbol{\Sigma}_{\text{LW}} = \delta^* \mathbf{F} + (1 - \delta^*) \mathbf{S}$$
3. **Portfolio Construction & Allocation**:
   Once the discrete selection vector $\mathbf{x}^*$ is identified, asset weights are assigned via inverse volatility:
   $$w_i = \frac{1 / \sigma_i}{\sum_{j \in \text{Selected}} 1 / \sigma_j}$$
4. **Backtesting Engine**:
   - Compares growth of $\$100$ against the S&P 500 benchmark.
   - Evaluates **Buy-and-Hold** vs. **Monthly Walk-Forward** rebalancing (incorporating annual portfolio turnover penalties).
   - Computes **Annualized Return**, **Sharpe Ratio**, **Sortino Ratio**, and **Maximum Drawdown**.

---

## 📁 Project Structure

```text
quantum_portfolio_platform/
├── backend/
│   ├── __init__.py            # Python package initialization
│   ├── main.py                # FastAPI endpoints, WebSocket handler, and orchestration
│   ├── market.py              # Calibrated mock market data and geometric Brownian motion
│   ├── qubo.py                # Markowitz -> QUBO matrix -> Ising Pauli-Z Hamiltonian
│   ├── classical.py           # Exact 2^N MIQP, Simulated Annealing, and Quantum Proxy
│   ├── quantum_qiskit.py      # Qiskit QAOA, QAOA-XY, VQE, and NumPy fallback simulators
│   ├── noise.py               # IBM Eagle noise model, noisy shot sampling, and ZNE folding
│   ├── routing.py             # Linear lower bound & Heavy-Hex CNOT routing bounds
│   ├── finance.py             # Inverse vol weighting, backtesting, Sharpe, and frontier
│   ├── data_live.py           # Yahoo Finance fetcher, Ledoit-Wolf shrinkage, and CSV parser
│   └── runs_db.py             # SQLite persistence for multi-run telemetry and experiments
├── frontend/
│   ├── index.html             # Terminal dashboard DOM structure and tabs
│   ├── styles.css             # Bloomberg-inspired dark terminal design system
│   └── app.js                 # Frontend state, WebSocket streaming, and Canvas renderers
├── requirements.txt           # Production dependencies
├── run.bat                    # One-click Windows launch script
├── test_deep.py               # 47 end-to-end integration tests
└── test_defense.py            # 58 defense-grade physics, routing, and numerical tests
```

---

## ⚡ Getting Started

### Prerequisites

- Python 3.10, 3.11, or 3.12
- Git
- Modern web browser (Chrome, Edge, Firefox, Safari)

### Installation

1. **Clone the repository**:
   ```bash
   git clone https://github.com/Varshith-24051/Quantum-Project.git
   cd Quantum-Project
   ```

2. **Create and activate a virtual environment**:
   ```bash
   # On Windows:
   python -m venv venv
   .\venv\Scripts\activate

   # On macOS / Linux:
   python3 -m venv venv
   source venv/bin/activate
   ```

3. **Install dependencies**:
   ```bash
   pip install -r requirements.txt
   ```

### Running the Platform

#### Option A: Quickstart Script (Windows)
Double-click `run.bat` or run:
```powershell
.\run.bat
```

#### Option B: Direct CLI Execution
```bash
uvicorn backend.main:app --host 127.0.0.1 --port 8000 --reload
```

Once running, navigate to **[http://127.0.0.1:8000](http://127.0.0.1:8000)** in your browser.

---

## 📡 REST API & WebSocket Reference

### Endpoints

| Method | Route | Description |
| :--- | :--- | :--- |
| `GET` | `/api/health` | Healthcheck and Qiskit installation status |
| `GET` | `/api/universe` | Retrieve asset universe, live returns, and covariance matrix |
| `POST` | `/api/datasets` | Upload custom CSV price time-series dataset |
| `POST` | `/api/optimize` | Execute single portfolio optimization (QAOA, VQE, Classical) |
| `POST` | `/api/compare` | Run all 6 solvers simultaneously for side-by-side benchmarking |
| `GET` | `/api/runs` | Retrieve persisted experiment runs from SQLite database |
| `DELETE`| `/api/runs` | Clear SQLite run history |
| `GET` | `/api/qpu/status` | Check physical IBM Quantum hardware connection status |
| `WS` | `/ws/optimize` | Live WebSocket streaming of variational optimization steps |

### Optimization Request Schema (`POST /api/optimize`)

```json
{
  "tickers": ["AAPL", "MSFT", "GOOGL", "AMZN", "NVDA", "TSLA", "JPM", "JNJ"],
  "K": 4,
  "risk_q": 0.5,
  "algorithm": "qaoa",
  "p": 2,
  "shots": 2048,
  "optimizer": "COBYLA",
  "rebalance": "buy_hold",
  "mixer": "xy",
  "noise": "ideal",
  "zne": false,
  "cvar_alpha": 1.0,
  "source": "mock"
}
```

---

## 🛡 Verification & Test Suite

The repository contains an exhaustive two-tier test suite covering 105 automated unit and integration tests:

1. **`test_deep.py` (47 Tests)**:
   - Validates all 5 algorithms across COBYLA and SPSA optimizers.
   - Verifies pure NumPy statevector fallback when Qiskit is not present.
   - Tests boundary universes ($N=3, K=1$ and $N=10, K=5$).
   - End-to-end WebSocket iteration streaming verification.

2. **`test_defense.py` (58 Tests)**:
   - Validates IBM Eagle noise profiles and Aer simulation.
   - ZNE linear extrapolation slope and intercept recovery.
   - QAOA-XY Dicke state synthesis and zero-leakage conservation.
   - Ledoit-Wolf positive-definiteness guarantee on real market returns.
   - Heavy-hex routing bounds and linear chain inequalities ($LB \le UB$).
   - SQLite persistence and schema integrity.

To execute the test suites:
```bash
python test_deep.py
python test_defense.py
```

---

## 📜 License

This project is open-source and distributed under the [MIT License](LICENSE).
