"""
RGCDC Debate Tournament Tabulation System
FastAPI Backend Server (REST API + SQLite/PostgreSQL Persistence + Hungarian Draw Engine)
Reviewed & Fixed:
- Uses absolute writable path for SQLite database (with /tmp fallback on read-only filesystems)
- Safe ORM conflict institution resolution
- Serves Calico Tab UI directly from root (/) or frontend/index.html
"""

import os
import tempfile
from pathlib import Path
from typing import List
from fastapi import FastAPI, Depends, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy.orm import Session

from .models import (
    init_db,
    Tournament,
    Institution,
    Team,
    Speaker,
    Adjudicator,
    AdjudicatorConflict,
    Round,
    Motion,
    DebateRoom,
    DebateTeamAssignment,
    AdjudicatorAllocation,
    Ballot,
    SpeakerScore,
    JudgeEvaluation,
    DebateFormat,
    RoundStatus,
)
from .schemas import (
    FormatUpdateRequest,
    TeamCreateRequest,
    AdjudicatorCreateRequest,
    MotionCreateRequest,
    BallotSubmitRequest,
    JudgeEvaluationRequest,
)
from .algorithm import (
    TeamNode,
    JudgeNode,
    power_pair_teams,
    allocate_adjudicators_hungarian,
    update_judge_score_from_evaluation,
)

BASE_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = BASE_DIR.parent


def _resolve_database_url() -> str:
    env_url = os.getenv("DATABASE_URL", "").strip()
    if env_url:
        if env_url.startswith("postgres://"):
            return env_url.replace("postgres://", "postgresql://", 1)
        return env_url
    # Try project root first, fallback to /tmp if read-only
    candidate = PROJECT_ROOT / "rgcdc_tab.db"
    try:
        with open(candidate, "a"):
            pass
        return f"sqlite:///{candidate}"
    except OSError:
        tmp_db = Path(tempfile.gettempdir()) / "rgcdc_tab.db"
        return f"sqlite:///{tmp_db}"


DATABASE_URL = _resolve_database_url()
engine, SessionLocal = init_db(DATABASE_URL)

app = FastAPI(
    title="RGCDC Calico Tab / Tabbycat API",
    description="Scalable Debate Tournament Tabulation System with Hungarian Adjudicator Allocation",
    version="2.7.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

FRONTEND_DIR = PROJECT_ROOT / "frontend"
if FRONTEND_DIR.exists():
    app.mount("/static", StaticFiles(directory=str(FRONTEND_DIR)), name="static")


@app.get("/", response_class=HTMLResponse)
def serve_frontend_ui():
    """Serves the pixel-perfect Calico Tab / Tabbycat UI directly from root or frontend/index.html."""
    root_index = PROJECT_ROOT / "index.html"
    if root_index.exists():
        return FileResponse(str(root_index))
    fe_index = FRONTEND_DIR / "index.html"
    if fe_index.exists():
        return FileResponse(str(fe_index))
    return HTMLResponse("<h1>RGCDC CalicoTab API Running. Visit /docs for OpenAPI UI.</h1>")


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def get_or_create_tournament(db: Session) -> Tournament:
    t = db.query(Tournament).first()
    if not t:
        t = Tournament(
            name="3rd RGCDC Dialogues 2026",
            short_name="rgcdc2026",
            slug="rgcdc-dialogues-2026",
            host_institution="Rangpur Government College Debating Club (RGCDC)",
            format=DebateFormat.AP,
            current_round_number=1,
            total_prelim_rounds=5,
        )
        db.add(t)
        db.commit()
        db.refresh(t)
    return t


def get_or_create_institution(db: Session, tournament_id: int, name: str, code: str) -> Institution:
    clean_code = code.strip().upper()
    inst = (
        db.query(Institution)
        .filter(Institution.tournament_id == tournament_id, Institution.code == clean_code)
        .first()
    )
    if not inst:
        inst = Institution(tournament_id=tournament_id, name=name.strip(), code=clean_code)
        db.add(inst)
        db.commit()
        db.refresh(inst)
    return inst


@app.get("/api/health")
def health_check():
    return {"status": "ok", "service": "RGCDC CalicoTab Engine", "version": "2.7.0", "db": DATABASE_URL}


@app.get("/api/tournament")
def get_tournament_overview(db: Session = Depends(get_db)):
    t = get_or_create_tournament(db)
    return {
        "id": t.id,
        "name": t.name,
        "short_name": t.short_name,
        "slug": t.slug,
        "host_institution": t.host_institution,
        "format": t.format.value,
        "speakers_per_team": 3 if t.format == DebateFormat.AP else 2,
        "teams_per_room": 2 if t.format == DebateFormat.AP else 4,
        "current_round_number": t.current_round_number,
        "total_prelim_rounds": t.total_prelim_rounds,
        "counts": {
            "institutions": db.query(Institution).filter_by(tournament_id=t.id).count(),
            "teams": db.query(Team).filter_by(tournament_id=t.id, is_active=True).count(),
            "speakers": db.query(Speaker).join(Team).filter(Team.tournament_id == t.id).count(),
            "adjudicators": db.query(Adjudicator).filter_by(tournament_id=t.id, is_active=True).count(),
            "rounds": db.query(Round).filter_by(tournament_id=t.id).count(),
        },
    }


@app.put("/api/tournament/format")
def update_tournament_format(req: FormatUpdateRequest, db: Session = Depends(get_db)):
    t = get_or_create_tournament(db)
    t.name = req.name
    t.host_institution = req.host_institution
    t.format = DebateFormat(req.format)
    t.total_prelim_rounds = req.total_prelim_rounds
    db.commit()
    db.refresh(t)
    return {
        "message": f"Tournament updated to {t.format.value} format.",
        "format": t.format.value,
        "speakers_per_team": 3 if t.format == DebateFormat.AP else 2,
        "teams_per_room": 2 if t.format == DebateFormat.AP else 4,
    }


@app.post("/api/teams")
def create_team(req: TeamCreateRequest, db: Session = Depends(get_db)):
    t = get_or_create_tournament(db)
    if req.format != t.format.value:
        raise HTTPException(
            status_code=400,
            detail=f"Tournament is currently configured for {t.format.value}, but team payload specified {req.format}.",
        )
    inst = get_or_create_institution(db, t.id, req.institution_name, req.institution_code)
    team = Team(
        tournament_id=t.id,
        institution_id=inst.id,
        reference_name=req.reference_name.strip(),
        short_name=req.short_name.strip(),
    )
    db.add(team)
    db.flush()

    for idx, sp in enumerate(req.speakers, start=1):
        speaker = Speaker(
            team_id=team.id,
            name=sp.name.strip(),
            email=sp.email.strip() if sp.email else None,
            speaker_Order=idx,
            novice=sp.novice,
        )
        db.add(speaker)

    db.commit()
    db.refresh(team)
    return {
        "id": team.id,
        "reference_name": team.reference_name,
        "short_name": team.short_name,
        "institution_code": inst.code,
        "speakers": [{"id": s.id, "name": s.name, "email": s.email} for s in team.speakers],
    }


@app.get("/api/teams")
def list_teams(db: Session = Depends(get_db)):
    t = get_or_create_tournament(db)
    teams = (
        db.query(Team)
        .filter_by(tournament_id=t.id)
        .order_by(Team.total_points.desc(), Team.total_speaks.desc(), Team.id.asc())
        .all()
    )
    return [
        {
            "id": tm.id,
            "reference_name": tm.reference_name,
            "short_name": tm.short_name,
            "institution_name": tm.institution.name,
            "institution_code": tm.institution.code,
            "total_points": tm.total_points,
            "total_speaks": round(tm.total_speaks, 2),
            "first_places": tm.first_places,
            "gov_count": tm.gov_count,
            "opp_count": tm.opp_count,
            "speakers": [
                {
                    "id": s.id,
                    "name": s.name,
                    "email": s.email,
                    "order": s.speaker_Order,
                    "total_speaks": round(s.total_speaks, 2),
                    "average_speaks": round(s.average_speaks, 2),
                }
                for s in tm.speakers
            ],
        }
        for tm in teams
    ]


@app.post("/api/adjudicators")
def create_adjudicator(req: AdjudicatorCreateRequest, db: Session = Depends(get_db)):
    t = get_or_create_tournament(db)
    inst = get_or_create_institution(db, t.id, req.institution_name, req.institution_code)
    adj = Adjudicator(
        tournament_id=t.id,
        institution_id=inst.id,
        name=req.name.strip(),
        email=req.email.strip() if req.email else None,
        base_score=req.base_score,
        current_score=req.base_score,
        is_independent=req.is_independent,
    )
    db.add(adj)
    db.flush()

    for code in req.additional_conflict_institution_codes:
        c_inst = get_or_create_institution(db, t.id, code, code)
        if c_inst.id != inst.id:
            db.add(
                AdjudicatorConflict(
                    adjudicator_id=adj.id,
                    conflicted_institution_id=c_inst.id,
                    reason=f"Declared conflict with {c_inst.code}",
                )
            )

    db.commit()
    db.refresh(adj)
    return {
        "id": adj.id,
        "name": adj.name,
        "email": adj.email,
        "institution_code": inst.code,
        "base_score": adj.base_score,
        "current_score": adj.current_score,
    }


@app.get("/api/adjudicators")
def list_adjudicators(db: Session = Depends(get_db)):
    t = get_or_create_tournament(db)
    adjs = (
        db.query(Adjudicator)
        .filter_by(tournament_id=t.id)
        .order_by(Adjudicator.current_score.desc(), Adjudicator.id.asc())
        .all()
    )
    results = []
    for a in adjs:
        extra_codes = []
        for c in a.explicit_conflicts:
            if c.conflicted_institution_id:
                inst_obj = db.query(Institution).filter_by(id=c.conflicted_institution_id).first()
                if inst_obj:
                    extra_codes.append(inst_obj.code)
        results.append(
            {
                "id": a.id,
                "name": a.name,
                "email": a.email,
                "institution_name": a.institution.name,
                "institution_code": a.institution.code,
                "base_score": round(a.base_score, 2),
                "current_score": round(a.current_score, 2),
                "evaluations_count": len(a.evaluations),
                "conflicts": [a.institution.code] + extra_codes,
            }
        )
    return results


@app.post("/api/rounds/draw")
def generate_round_draw(round_number: int = 1, db: Session = Depends(get_db)):
    t = get_or_create_tournament(db)
    teams_orm = db.query(Team).filter_by(tournament_id=t.id, is_active=True).all()
    adjs_orm = db.query(Adjudicator).filter_by(tournament_id=t.id, is_active=True).all()

    team_nodes: List[TeamNode] = []
    for tm in teams_orm:
        past_opps = set()
        bp_hist = []
        for assign in tm.room_assignments:
            bp_hist.append(assign.position)
            for other in assign.room.team_assignments:
                if other.team_id != tm.id:
                    past_opps.add(other.team_id)
        team_nodes.append(
            TeamNode(
                id=tm.id,
                name=tm.reference_name,
                short_name=tm.short_name,
                institution_id=tm.institution_id,
                institution_code=tm.institution.code,
                total_points=tm.total_points,
                total_speaks=tm.total_speaks,
                first_places=tm.first_places,
                gov_count=tm.gov_count,
                opp_count=tm.opp_count,
                past_opponents=past_opps,
                bp_positions_history=bp_hist,
            )
        )

    judge_nodes: List[JudgeNode] = []
    for adj in adjs_orm:
        conflict_insts = {
            c.conflicted_institution_id
            for c in adj.explicit_conflicts
            if c.conflicted_institution_id is not None
        }
        conflict_teams = {
            c.conflicted_team_id
            for c in adj.explicit_conflicts
            if c.conflicted_team_id is not None
        }
        judged_teams = set()
        for alloc in adj.allocations:
            for ta in alloc.room.team_assignments:
                judged_teams.add(ta.team_id)

        judge_nodes.append(
            JudgeNode(
                id=adj.id,
                name=adj.name,
                institution_id=adj.institution_id,
                institution_code=adj.institution.code,
                base_score=adj.base_score,
                current_score=adj.current_score,
                conflicted_institution_ids=conflict_insts,
                conflicted_team_ids=conflict_teams,
                judged_team_ids=judged_teams,
            )
        )

    try:
        paired_rooms = power_pair_teams(team_nodes, debate_format=t.format.value, venue_prefix="Hall")
        allocation_result = allocate_adjudicators_hungarian(paired_rooms, judge_nodes, allocate_panels=True)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    rnd = Round(
        tournament_id=t.id,
        round_number=round_number,
        name=f"Round {round_number}",
        abbreviation=f"R{round_number}",
        status=RoundStatus.RELEASED,
    )
    db.add(rnd)
    db.flush()

    response_rooms = []
    for pr in paired_rooms:
        room_orm = DebateRoom(
            round_id=rnd.id,
            venue_name=pr.venue_name,
            bracket_points=pr.bracket_points,
            importance_weight=pr.importance_weight,
        )
        db.add(room_orm)
        db.flush()

        for pos, tnode in pr.positions.items():
            db.add(
                DebateTeamAssignment(
                    room_id=room_orm.id,
                    team_id=tnode.id,
                    position=pos,
                )
            )

        if pr.chair:
            db.add(
                AdjudicatorAllocation(
                    room_id=room_orm.id,
                    adjudicator_id=pr.chair.id,
                    role="CHAIR",
                    assignment_cost=pr.chair_cost,
                )
            )
        for wing in pr.panellists:
            db.add(
                AdjudicatorAllocation(
                    room_id=room_orm.id,
                    adjudicator_id=wing.id,
                    role="PANELLIST",
                    assignment_cost=0.0,
                )
            )

        response_rooms.append(
            {
                "room_id": room_orm.id,
                "venue": pr.venue_name,
                "bracket_points": pr.bracket_points,
                "importance_weight": pr.importance_weight,
                "teams": {
                    pos: {"id": tn.id, "short_name": tn.short_name, "institution": tn.institution_code, "points": tn.total_points}
                    for pos, tn in pr.positions.items()
                },
                "chair": {
                    "id": pr.chair.id,
                    "name": pr.chair.name,
                    "institution": pr.chair.institution_code,
                    "score": pr.chair.current_score,
                    "cost": pr.chair_cost,
                }
                if pr.chair
                else None,
                "panellists": [
                    {"id": w.id, "name": w.name, "institution": w.institution_code, "score": w.current_score}
                    for w in pr.panellists
                ],
            }
        )

    t.current_round_number = round_number
    db.commit()

    return {
        "round_id": rnd.id,
        "round_number": rnd.round_number,
        "format": t.format.value,
        "rooms": response_rooms,
        "diagnostics": {
            "chair_cost_matrix": allocation_result["chair_cost_matrix"],
            "chair_reason_matrix": allocation_result["chair_reason_matrix"],
            "judge_headers": allocation_result["judge_headers"],
            "room_headers": allocation_result["room_headers"],
            "infeasible_warnings": allocation_result["infeasible_warnings"],
        },
    }


@app.post("/api/motions")
def add_round_motion(req: MotionCreateRequest, db: Session = Depends(get_db)):
    t = get_or_create_tournament(db)
    rnd = db.query(Round).filter_by(tournament_id=t.id, round_number=req.round_number).first()
    if not rnd:
        rnd = Round(
            tournament_id=t.id,
            round_number=req.round_number,
            name=f"Round {req.round_number}",
            abbreviation=f"R{req.round_number}",
            status=RoundStatus.DRAFT,
        )
        db.add(rnd)
        db.flush()

    motion = Motion(
        round_id=rnd.id,
        reference=req.reference,
        text=req.text,
        info_slide=req.info_slide,
    )
    db.add(motion)
    db.commit()
    db.refresh(motion)
    return {
        "id": motion.id,
        "round_number": req.round_number,
        "reference": motion.reference,
        "text": motion.text,
        "info_slide": motion.info_slide,
    }


@app.post("/api/ballots")
def submit_ballot(req: BallotSubmitRequest, db: Session = Depends(get_db)):
    t = get_or_create_tournament(db)
    room = db.query(DebateRoom).filter_by(id=req.room_id).first()
    if not room:
        raise HTTPException(status_code=404, detail="Debate room not found.")
    if room.ballot_confirmed:
        raise HTTPException(status_code=400, detail="Ballot already confirmed for this room.")

    ballot = Ballot(room_id=room.id, submitted_by=req.submitted_by, notes=req.notes)
    db.add(ballot)
    db.flush()

    is_ap = t.format == DebateFormat.AP
    rank_to_pts = {1: 1, 2: 0} if is_ap else {1: 3, 2: 2, 3: 1, 4: 0}

    for tr in req.team_results:
        assignment = (
            db.query(DebateTeamAssignment)
            .filter_by(room_id=room.id, team_id=tr.team_id)
            .first()
        )
        if not assignment:
            raise HTTPException(status_code=400, detail=f"Team {tr.team_id} is not assigned to room {room.id}.")

        pts = rank_to_pts.get(tr.rank, 0)
        team_speaks_sum = 0.0

        for idx, sm in enumerate(tr.speaker_marks, start=1):
            sp = db.query(Speaker).filter_by(id=sm.speaker_id, team_id=tr.team_id).first()
            if not sp:
                raise HTTPException(status_code=400, detail=f"Speaker {sm.speaker_id} not in team {tr.team_id}.")
            db.add(
                SpeakerScore(
                    ballot_id=ballot.id,
                    speaker_id=sp.id,
                    team_id=tr.team_id,
                    speech_position=idx,
                    score=sm.score,
                )
            )
            sp.total_speaks += sm.score
            sp.rounds_spoken += 1
            sp.average_speaks = round(sp.total_speaks / sp.rounds_spoken, 2)
            team_speaks_sum += sm.score

        assignment.rank = tr.rank
        assignment.points_earned = pts
        assignment.total_team_speaks = round(team_speaks_sum, 2)

        team_orm = db.query(Team).filter_by(id=tr.team_id).first()
        team_orm.total_points += pts
        team_orm.total_speaks = round(team_orm.total_speaks + team_speaks_sum, 2)
        if tr.rank == 1:
            team_orm.first_places += 1
        elif tr.rank == 2:
            team_orm.second_places += 1
        if tr.position in ("GOV", "OG", "CG"):
            team_orm.gov_count += 1
        else:
            team_orm.opp_count += 1

    room.ballot_confirmed = True
    db.commit()
    return {"status": "confirmed", "ballot_id": ballot.id, "room_id": room.id}


@app.post("/api/evaluations")
def submit_judge_evaluation(req: JudgeEvaluationRequest, db: Session = Depends(get_db)):
    t = get_or_create_tournament(db)
    adj = db.query(Adjudicator).filter_by(id=req.adjudicator_id, tournament_id=t.id).first()
    if not adj:
        raise HTTPException(status_code=404, detail="Adjudicator not found.")

    past_count = len(adj.evaluations)
    prior_score = adj.current_score
    new_score = update_judge_score_from_evaluation(
        base_score=adj.base_score,
        current_score=adj.current_score,
        evaluation_score=req.score,
        past_evaluations_count=past_count,
        room_importance=6.5,
    )
    adj.current_score = new_score

    rnd = db.query(Round).filter_by(tournament_id=t.id, round_number=req.round_number).first()
    rnd_id = rnd.id if rnd else 1

    ev = JudgeEvaluation(
        adjudicator_id=adj.id,
        round_id=rnd_id,
        evaluator_team_id=req.evaluator_team_id,
        evaluator_name=req.evaluator_name,
        score=req.score,
        comments=req.comments,
        prior_adj_score=prior_score,
        updated_adj_score=new_score,
    )
    db.add(ev)
    db.commit()
    return {
        "adjudicator_id": adj.id,
        "adjudicator_name": adj.name,
        "prior_score": round(prior_score, 2),
        "evaluation_submitted": req.score,
        "updated_score": round(new_score, 2),
    }


@app.get("/api/standings/teams")
def get_team_standings(db: Session = Depends(get_db)):
    return list_teams(db)


@app.get("/api/standings/speakers")
def get_speaker_standings(db: Session = Depends(get_db)):
    t = get_or_create_tournament(db)
    speakers = (
        db.query(Speaker)
        .join(Team)
        .filter(Team.tournament_id == t.id)
        .order_by(Speaker.total_speaks.desc(), Speaker.average_speaks.desc(), Speaker.id.asc())
        .all()
    )
    return [
        {
            "rank": idx,
            "id": sp.id,
            "name": sp.name,
            "team_short_name": sp.team.short_name,
            "institution_code": sp.team.institution.code,
            "total_speaks": round(sp.total_speaks, 2),
            "average_speaks": round(sp.average_speaks, 2),
            "rounds_spoken": sp.rounds_spoken,
        }
        for idx, sp in enumerate(speakers, start=1)
    ]
