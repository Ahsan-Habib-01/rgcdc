# RGCDC Debate Tournament Tabulation System (Calico Tab / Tabbycat Clone)

A full-stack, production-grade Debate Tournament Tabulation System engineered for **Rangpur Government College Debating Club (RGCDC)** and the **3rd RGCDC Dialogues 2026**.

## Core Capabilities

1. **100% Pixel-Perfect Calico Tab / Tabbycat UI/UX**:
   - Authentic `#1b2432` dark-slate navigation header, structural left sidebar (`#f8f9fa`), subtle `#f1f5f9` data-table row hover states, tabular monospace score pills, and responsive views.
2. **Dynamic Admin Data Entry (AP & BP Conditional Rendering)**:
   - **Asian Parliamentary (AP)**: Dynamically renders **3 Speaker input blocks** per team (Prime Minister, Deputy Prime Minister, Whip) and pairs **2 teams per room** (`GOV` vs `OPP`).
   - **British Parliamentary (BP)**: Dynamically renders **2 Speaker input blocks** per team (Speaker 1, Speaker 2) and pairs **4 teams per room** (`OG`, `OO`, `CG`, `CO`).
   - **Adjudicator Conflict Registry**: Captures primary institution and multi-institution conflict codes.
3. **Superior Draw & Adjudicator Allocation Algorithm (`backend/algorithm.py`)**:
   - **Strict Power-Pairing**: Sorts teams by `(total_points, total_speaks, first_places)` and pairs strictly within point brackets while balancing sides and avoiding repeat matchups.
   - **Hungarian Algorithm / Minimum Weight Perfect Matching ($O(V^3)$)**: Models adjudicator allocation on a bipartite graph $G = (J \cup R, E)$ and evaluates an $R \times J$ Cost Matrix $C[i, j]$:
     - **Hard Constraint 1 (Institutional Conflict)**: $C[i, j] = 10^9$ ($\infty$) if Judge $i$ belongs to or conflicts with any team's institution in Room $j$.
     - **Hard Constraint 2 (Team History Conflict)**: $C[i, j] = 10^9$ ($\infty$) if Judge $i$ has adjudicated any team in Room $j$ in a prior round.
     - **Soft Cost (Assortative Bracket-Quality Matching)**: Assigns highest-rated conflict-free chairs to top-bracket rooms via Kuhn-Munkres optimization.
4. **Post-Round Operations & Dynamic Judge Score Updates**:
   - Motion & Info Slide management, Digital Ballot entry with automatic speaker & team standings recalculation, and Bayesian shrinkage judge score adjustment driven by team feedback evaluations.
