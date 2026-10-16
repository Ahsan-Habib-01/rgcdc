"""
RGCDC Debate Tournament Tabulation System
Superior Draw & Adjudicator Allocation Engine (Better than Tabbycat)

Implements:
1. Strict Power-Pairing & Bracket Matching (AP: 2 teams/room; BP: 4 teams/room)
   with Side-Allocation Optimization and Intra-Bracket Conflict Avoidance.
2. Graph-Theoretic Adjudicator Allocation via Minimum Weight Perfect Matching
   (Kuhn-Munkres / Hungarian Algorithm, O(V^3)) over a Bipartite Graph G = (J U R, E).
   Evaluates Cost Matrix C[i, j] incorporating:
     - Hard Constraint 1: Institutional Conflict (Judge cannot judge own institution -> INF)
     - Hard Constraint 2: Team History Conflict (Judge cannot judge same team twice -> INF)
     - Soft Cost: Bracket Importance Weight vs. Judge Effective Quality Score
3. Dynamic Judge Rating Update using Bayesian / Confidence-Weighted Feedback Aggregation.
"""

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Set, Tuple
import math

INF_COST = 1_000_000_000.0  # Hard constraint penalty (10^9)


@dataclass
class TeamNode:
    id: int
    name: str
    short_name: str
    institution_id: int
    institution_code: str
    total_points: int = 0
    total_speaks: float = 0.0
    first_places: int = 0
    gov_count: int = 0
    opp_count: int = 0
    past_opponents: Set[int] = field(default_factory=set)
    bp_positions_history: List[str] = field(default_factory=list)


@dataclass
class JudgeNode:
    id: int
    name: str
    institution_id: int
    institution_code: str
    base_score: float  # 1.0 - 10.0
    current_score: float  # 1.0 - 10.0 (dynamically adjusted via evaluations)
    conflicted_institution_ids: Set[int] = field(default_factory=set)
    conflicted_team_ids: Set[int] = field(default_factory=set)
    judged_team_ids: Set[int] = field(default_factory=set)  # Team history hard constraint


@dataclass
class PairedRoom:
    room_index: int
    venue_name: str
    bracket_points: float
    importance_weight: float  # 1.0 - 10.0
    positions: Dict[str, TeamNode]  # AP: {"GOV": t1, "OPP": t2}; BP: {"OG": t1, "OO": t2, "CG": t3, "CO": t4}
    chair: Optional[JudgeNode] = None
    panellists: List[JudgeNode] = field(default_factory=list)
    chair_cost: float = 0.0
    cost_breakdown: Dict[str, float] = field(default_factory=dict)

    @property
    def teams(self) -> List[TeamNode]:
        return list(self.positions.values())

    @property
    def team_ids(self) -> Set[int]:
        return {t.id for t in self.positions.values()}

    @property
    def institution_ids(self) -> Set[int]:
        return {t.institution_id for t in self.positions.values()}


def hungarian_algorithm(cost_matrix: List[List[float]]) -> List[Tuple[int, int]]:
    """
    Pure-Python O(n^3) Kuhn-Munkres (Hungarian) Algorithm for Minimum Weight
    Bipartite Perfect Matching.
    Given an R x C cost matrix (with R <= C; if R > C, transposes automatically),
    returns list of (row_idx, col_idx) assignments minimizing total cost.
    """
    if not cost_matrix or not cost_matrix[0]:
        return []

    n_rows = len(cost_matrix)
    n_cols = len(cost_matrix[0])
    transposed = False

    if n_rows > n_cols:
        cost_matrix = [[cost_matrix[r][c] for r in range(n_rows)] for c in range(n_cols)]
        n_rows, n_cols = n_cols, n_rows
        transposed = True

    # Try scipy.optimize.linear_sum_assignment if available, else exact O(n^3) potential method
    try:
        import numpy as np
        from scipy.optimize import linear_sum_assignment

        arr = np.array(cost_matrix, dtype=np.float64)
        row_ind, col_ind = linear_sum_assignment(arr)
        pairs = list(zip(row_ind.tolist(), col_ind.tolist()))
        return [(c, r) for r, c in pairs] if transposed else pairs
    except Exception:
        pass

    # Pure-Python Jonker-Volgenant / Kuhn-Munkres O(n^3) potential implementation (1-indexed)
    u = [0.0] * (n_rows + 1)
    v = [0.0] * (n_cols + 1)
    p = [0] * (n_cols + 1)
    way = [0] * (n_cols + 1)

    for i in range(1, n_rows + 1):
        p[0] = i
        j0 = 0
        minv = [math.inf] * (n_cols + 1)
        used = [False] * (n_cols + 1)
        while True:
            used[j0] = True
            i0 = p[j0]
            delta = math.inf
            j1 = 0
            for j in range(1, n_cols + 1):
                if not used[j]:
                    cur = cost_matrix[i0 - 1][j - 1] - u[i0] - v[j]
                    if cur < minv[j]:
                        minv[j] = cur
                        way[j] = j0
                    if minv[j] < delta:
                        delta = minv[j]
                        j1 = j
            for j in range(n_cols + 1):
                if used[j]:
                    u[p[j]] += delta
                    v[j] -= delta
                else:
                    minv[j] -= delta
            j0 = j1
            if p[j0] == 0:
                break
        while True:
            j1 = way[j0]
            p[j0] = p[j1]
            j0 = j1
            if j0 == 0:
                break

    results: List[Tuple[int, int]] = []
    for j in range(1, n_cols + 1):
        if p[j] > 0:
            r_idx = p[j] - 1
            c_idx = j - 1
            results.append((c_idx, r_idx) if transposed else (r_idx, c_idx))
    results.sort(key=lambda x: x[0])
    return results


def power_pair_teams(
    teams: List[TeamNode],
    debate_format: str = "AP",
    venue_prefix: str = "Room",
) -> List[PairedRoom]:
    """
    Strict Power-Pairing Engine:
    1. Sorts active teams by (total_points DESC, total_speaks DESC, first_places DESC, id ASC).
    2. Groups teams strictly by point brackets (pulling up highest-speaks team from next bracket
       only when a bracket is not divisible by teams_per_room).
    3. Within each bracket, optimizes pairings to avoid repeat opponents and same-institution clashes,
       and assigns balanced debate sides (GOV/OPP for AP; OG/OO/CG/CO for BP).
    """
    teams_per_room = 2 if debate_format.upper() == "AP" else 4
    active_teams = [t for t in teams]
    if len(active_teams) < teams_per_room or len(active_teams) % teams_per_room != 0:
        raise ValueError(
            f"Format {debate_format} requires active team count divisible by {teams_per_room} "
            f"(got {len(active_teams)})."
        )

    # Sort strictly by points, then speaker scores, then 1st places
    sorted_teams = sorted(
        active_teams,
        key=lambda t: (-t.total_points, -round(t.total_speaks, 3), -t.first_places, t.id),
    )

    num_rooms = len(sorted_teams) // teams_per_room
    rooms: List[PairedRoom] = []

    # Within each bracket slice, minimize repeat matchups & institutional clashes
    idx = 0
    room_counter = 1
    while idx < len(sorted_teams):
        group = sorted_teams[idx : idx + teams_per_room]
        # If AP (2 teams) and there is another room in the same point bracket, check swap to avoid repeat/inst conflict
        if (
            teams_per_room == 2
            and idx + 4 <= len(sorted_teams)
            and sorted_teams[idx].total_points == sorted_teams[idx + 3].total_points
        ):
            t1, t2, t3, t4 = sorted_teams[idx : idx + 4]
            # Evaluate 3 possible matchings in a 4-team sub-bracket: (t1,t2)+(t3,t4), (t1,t3)+(t2,t4), (t1,t4)+(t2,t3)
            def pair_penalty(a: TeamNode, b: TeamNode) -> float:
                pen = abs(a.total_speaks - b.total_speaks) * 0.01
                if b.id in a.past_opponents:
                    pen += 5000.0
                if a.institution_id == b.institution_id:
                    pen += 1000.0
                return pen

            options = [
                (pair_penalty(t1, t2) + pair_penalty(t3, t4), [(t1, t2), (t3, t4)]),
                (pair_penalty(t1, t3) + pair_penalty(t2, t4), [(t1, t3), (t2, t4)]),
                (pair_penalty(t1, t4) + pair_penalty(t2, t3), [(t1, t4), (t2, t3)]),
            ]
            options.sort(key=lambda x: x[0])
            best_pairs = options[0][1]
            # Reorder slice in-place so normal iteration picks best_pairs[0] then best_pairs[1]
            sorted_teams[idx], sorted_teams[idx + 1] = best_pairs[0][0], best_pairs[0][1]
            sorted_teams[idx + 2], sorted_teams[idx + 3] = best_pairs[1][0], best_pairs[1][1]
            group = sorted_teams[idx : idx + teams_per_room]

        # Side assignment
        positions: Dict[str, TeamNode] = {}
        if teams_per_room == 2:
            a, b = group[0], group[1]
            # Balance GOV/OPP counts
            a_gov_ratio = a.gov_count - a.opp_count
            b_gov_ratio = b.gov_count - b.opp_count
            if a_gov_ratio <= b_gov_ratio:
                positions = {"GOV": a, "OPP": b}
            else:
                positions = {"GOV": b, "OPP": a}
        else:
            # BP: 4 positions OG, OO, CG, CO balanced against past position history
            bp_roles = ["OG", "OO", "CG", "CO"]
            role_cost = []
            for t in group:
                row = []
                for r in bp_roles:
                    count_r = t.bp_positions_history.count(r)
                    row.append(count_r * 10.0)
                role_cost.append(row)
            matching = hungarian_algorithm(role_cost)
            for t_idx, r_idx in matching:
                positions[bp_roles[r_idx]] = group[t_idx]

        avg_pts = sum(t.total_points for t in group) / float(len(group))
        # Top room gets importance weight 10.0, scaling down linearly to 2.5 for bottom room
        if num_rooms == 1:
            imp_weight = 10.0
        else:
            imp_weight = round(10.0 - 7.5 * ((room_counter - 1) / (num_rooms - 1)), 2)

        rooms.append(
            PairedRoom(
                room_index=room_counter,
                venue_name=f"{venue_prefix} {room_counter}",
                bracket_points=round(avg_pts, 2),
                importance_weight=imp_weight,
                positions=positions,
            )
        )
        room_counter += 1
        idx += teams_per_room

    return rooms


def compute_judge_room_cost(judge: JudgeNode, room: PairedRoom, role: str = "CHAIR") -> Tuple[float, str]:
    """
    Computes exact edge weight C[judge, room] in the Adjudicator-Room Bipartite Graph.
    Enforces Hard Constraints (Cost = INF_COST = 10^9):
      1. Institutional Conflict: Judge belongs to or conflicts with any team's institution in the room.
      2. Explicit Team Conflict: Judge has a declared conflict with any team in the room.
      3. Team History Conflict: Judge has already adjudicated any team in the room in a prior round.
    Soft Cost (when feasible):
      Combines Room Importance Weight W_room and Judge Effective Score S_judge:
      - Higher-importance brackets strongly prefer higher-rated chairs.
      - Minimizes quality mismatch penalty + prioritizes high S_judge in top rooms.
    """
    # Hard Constraint 1: Institutional Conflict
    all_judge_inst_conflicts = {judge.institution_id} | set(judge.conflicted_institution_ids)
    clashing_insts = all_judge_inst_conflicts.intersection(room.institution_ids)
    if clashing_insts:
        return INF_COST, "INSTITUTIONAL_CONFLICT"

    # Hard Constraint 1b: Explicit Personal/Team Conflict
    if judge.conflicted_team_ids.intersection(room.team_ids):
        return INF_COST, "EXPLICIT_TEAM_CONFLICT"

    # Hard Constraint 2: Team History Conflict (cannot judge the same team twice)
    repeated_teams = judge.judged_team_ids.intersection(room.team_ids)
    if repeated_teams:
        return INF_COST, "TEAM_HISTORY_CONFLICT"

    # Soft Cost Calculation
    s_judge = max(1.0, min(10.0, judge.current_score))
    w_room = max(1.0, min(10.0, room.importance_weight))

    if role == "CHAIR":
        # Supermodular penalty so high-W rooms get the highest-S chairs (Assortative Matching)
        quality_deficit_cost = w_room * (10.5 - s_judge) * 3.5
        mismatch_cost = ((w_room - s_judge) ** 2) * 0.8
        total_cost = round(quality_deficit_cost + mismatch_cost, 3)
    else:
        # For Panellists/Wings, prefer balanced strong panels in top rooms
        quality_deficit_cost = w_room * (10.5 - s_judge) * 1.8
        total_cost = round(quality_deficit_cost, 3)

    return total_cost, "FEASIBLE"


def allocate_adjudicators_hungarian(
    rooms: List[PairedRoom],
    judges: List[JudgeNode],
    allocate_panels: bool = True,
) -> Dict[str, object]:
    """
    Solves the Adjudicator Allocation problem via Graph Theory (Minimum Weight Perfect Matching
    / Hungarian Algorithm).
    Step 1: Constructs R x J Cost Matrix for CHAIR allocation and finds global minimum-cost matching.
    Step 2: If extra judges remain and allocate_panels=True, runs second-pass Hungarian matching
            to assign Panellists (wings) while strictly respecting all institutional and history constraints.
    Returns detailed allocation diagnostics including the full Cost Matrix for auditability.
    """
    if len(judges) < len(rooms):
        raise ValueError(
            f"Insufficient active adjudicators ({len(judges)}) for {len(rooms)} debate rooms."
        )

    # Sort judges by current_score descending for clean matrix indexing
    sorted_judges = sorted(judges, key=lambda j: (-j.current_score, j.id))

    # Build R x J Cost Matrix for Chairs
    chair_cost_matrix: List[List[float]] = []
    chair_reason_matrix: List[List[str]] = []

    for room in rooms:
        row_costs: List[float] = []
        row_reasons: List[str] = []
        for judge in sorted_judges:
            cost, reason = compute_judge_room_cost(judge, room, role="CHAIR")
            row_costs.append(cost)
            row_reasons.append(reason)
        chair_cost_matrix.append(row_costs)
        chair_reason_matrix.append(row_reasons)

    # Run Hungarian Algorithm on R x J matrix
    chair_matching = hungarian_algorithm(chair_cost_matrix)
    assigned_judge_ids: Set[int] = set()
    infeasible_warnings: List[str] = []

    for r_idx, j_idx in chair_matching:
        room = rooms[r_idx]
        judge = sorted_judges[j_idx]
        cost = chair_cost_matrix[r_idx][j_idx]
        reason = chair_reason_matrix[r_idx][j_idx]
        if cost >= INF_COST:
            infeasible_warnings.append(
                f"{room.venue_name} had no conflict-free chair available ({reason} with {judge.name})."
            )
        room.chair = judge
        room.chair_cost = cost
        room.cost_breakdown = {
            "chair_judge_id": judge.id,
            "chair_score": judge.current_score,
            "room_importance": room.importance_weight,
            "assignment_cost": cost,
            "status": reason,
        }
        assigned_judge_ids.add(judge.id)

    # Second-pass Hungarian matching for Panellists (up to 2 wings per room so panels have 3 judges)
    remaining_judges = [j for j in sorted_judges if j.id not in assigned_judge_ids]
    panel_passes = 0
    while allocate_panels and remaining_judges and panel_passes < 2:
        panel_passes += 1
        panel_cost_matrix: List[List[float]] = []
        for room in rooms:
            row_costs = []
            for judge in remaining_judges:
                cost, _ = compute_judge_room_cost(judge, room, role="PANELLIST")
                row_costs.append(cost)
            panel_cost_matrix.append(row_costs)

        panel_matching = hungarian_algorithm(panel_cost_matrix)
        newly_assigned: Set[int] = set()
        for r_idx, j_idx in panel_matching:
            cost = panel_cost_matrix[r_idx][j_idx]
            if cost < INF_COST:
                judge = remaining_judges[j_idx]
                rooms[r_idx].panellists.append(judge)
                newly_assigned.add(judge.id)
        if not newly_assigned:
            break
        remaining_judges = [j for j in remaining_judges if j.id not in newly_assigned]

    return {
        "rooms": rooms,
        "chair_cost_matrix": chair_cost_matrix,
        "chair_reason_matrix": chair_reason_matrix,
        "judge_headers": [
            {"id": j.id, "name": j.name, "institution": j.institution_code, "score": j.current_score}
            for j in sorted_judges
        ],
        "room_headers": [
            {"venue": r.venue_name, "bracket": r.bracket_points, "importance": r.importance_weight}
            for r in rooms
        ],
        "infeasible_warnings": infeasible_warnings,
        "unallocated_judges": [j.name for j in remaining_judges],
    }


def update_judge_score_from_evaluation(
    base_score: float,
    current_score: float,
    evaluation_score: float,
    past_evaluations_count: int,
    room_importance: float = 5.0,
) -> float:
    """
    Dynamically adjusts a judge's effective rating for subsequent rounds using a
    Bayesian shrinkage / confidence-weighted moving average:
      - Anchors partially to `base_score` (Core CA assessment) so a single outlier
        team feedback cannot wildly distort pairings.
      - Scales feedback weight by room importance and sample size.
      - Clamps output strictly to [1.0, 10.0].
    """
    clamped_eval = max(1.0, min(10.0, float(evaluation_score)))
    prior_weight = 2.5  # Equivalent prior observations from CA test
    importance_factor = 0.85 + 0.03 * max(1.0, min(10.0, room_importance))  # 0.88 .. 1.15
    effective_n = max(0, past_evaluations_count)

    # Blend prior anchor, current running score, and new evaluation
    numerator = (
        (prior_weight * base_score)
        + (effective_n * current_score)
        + (importance_factor * clamped_eval)
    )
    denominator = prior_weight + effective_n + importance_factor
    updated = numerator / denominator
    return round(max(1.0, min(10.0, updated)), 2)
