"""
RGCDC Debate Tournament Tabulation System (Calico Tab / Tabbycat Clone)
Database Models (SQLAlchemy 2.0 ORM)
Supports Asian Parliamentary (AP: 3 speakers/team, 2 teams/room)
and British Parliamentary (BP: 2 speakers/team, 4 teams/room).
"""

from datetime import datetime
from typing import List, Optional
from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    Enum,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
    create_engine,
)
from sqlalchemy.orm import declarative_base, relationship, sessionmaker
import enum

Base = declarative_base()


class DebateFormat(str, enum.Enum):
    AP = "AP"  # Asian Parliamentary: 2 teams/room (Gov, Opp), 3 speakers/team
    BP = "BP"  # British Parliamentary: 4 teams/room (OG, OO, CG, CO), 2 speakers/team


class RoundStage(str, enum.Enum):
    PRELIMINARY = "PRELIMINARY"
    ELIMINATION = "ELIMINATION"


class RoundStatus(str, enum.Enum):
    DRAFT = "DRAFT"
    DRAW_CONFIRMED = "DRAW_CONFIRMED"
    RELEASED = "RELEASED"
    COMPLETED = "COMPLETED"


class Tournament(Base):
    __tablename__ = "tournaments"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(200), nullable=False, default="3rd RGCDC Dialogues 2026")
    short_name = Column(String(64), nullable=False, default="rgcdc2026")
    slug = Column(String(64), unique=True, nullable=False, default="rgcdc-dialogues-2026")
    host_institution = Column(
        String(200), nullable=False, default="Rangpur Government College Debating Club (RGCDC)"
    )
    format = Column(Enum(DebateFormat), nullable=False, default=DebateFormat.AP)
    current_round_number = Column(Integer, default=1)
    total_prelim_rounds = Column(Integer, default=5)
    created_at = Column(DateTime, default=datetime.utcnow)

    institutions = relationship("Institution", back_populates="tournament", cascade="all, delete-orphan")
    teams = relationship("Team", back_populates="tournament", cascade="all, delete-orphan")
    adjudicators = relationship("Adjudicator", back_populates="tournament", cascade="all, delete-orphan")
    rounds = relationship("Round", back_populates="tournament", cascade="all, delete-orphan")


class Institution(Base):
    __tablename__ = "institutions"

    id = Column(Integer, primary_key=True, index=True)
    tournament_id = Column(Integer, ForeignKey("tournaments.id"), nullable=False)
    name = Column(String(200), nullable=False)
    code = Column(String(32), nullable=False)
    region = Column(String(100), default="Bangladesh")

    tournament = relationship("Tournament", back_populates="institutions")
    teams = relationship("Team", back_populates="institution")
    adjudicators = relationship("Adjudicator", back_populates="institution")

    __table_args__ = (UniqueConstraint("tournament_id", "code", name="uq_tournament_inst_code"),)


class Team(Base):
    __tablename__ = "teams"

    id = Column(Integer, primary_key=True, index=True)
    tournament_id = Column(Integer, ForeignKey("tournaments.id"), nullable=False)
    institution_id = Column(Integer, ForeignKey("institutions.id"), nullable=False)
    reference_name = Column(String(150), nullable=False)
    short_name = Column(String(64), nullable=False)
    code_name = Column(String(64), nullable=True)
    seed_score = Column(Float, default=0.0)
    is_active = Column(Boolean, default=True)

    # Cached aggregate standings (recomputed on every ballot confirmation)
    total_points = Column(Integer, default=0)  # AP: Win=1, Loss=0; BP: 1st=3, 2nd=2, 3rd=1, 4th=0
    total_speaks = Column(Float, default=0.0)
    first_places = Column(Integer, default=0)
    second_places = Column(Integer, default=0)
    gov_count = Column(Integer, default=0)
    opp_count = Column(Integer, default=0)

    tournament = relationship("Tournament", back_populates="teams")
    institution = relationship("Institution", back_populates="teams")
    speakers = relationship("Speaker", back_populates="team", cascade="all, delete-orphan")
    room_assignments = relationship("DebateTeamAssignment", back_populates="team")


class Speaker(Base):
    __tablename__ = "speakers"

    id = Column(Integer, primary_key=True, index=True)
    team_id = Column(Integer, ForeignKey("teams.id"), nullable=False)
    name = Column(String(150), nullable=False)
    email = Column(String(150), nullable=True)  # Optional but preferred per specification
    speaker_Order = Column(Integer, nullable=False, default=1)  # 1..3 for AP, 1..2 for BP
    novice = Column(Boolean, default=False)

    # Cached aggregate speaker metrics
    total_speaks = Column(Float, default=0.0)
    rounds_spoken = Column(Integer, default=0)
    average_speaks = Column(Float, default=0.0)

    team = relationship("Team", back_populates="speakers")
    scores = relationship("SpeakerScore", back_populates="speaker", cascade="all, delete-orphan")


class Adjudicator(Base):
    __tablename__ = "adjudicators"

    id = Column(Integer, primary_key=True, index=True)
    tournament_id = Column(Integer, ForeignKey("tournaments.id"), nullable=False)
    institution_id = Column(Integer, ForeignKey("institutions.id"), nullable=False)
    name = Column(String(150), nullable=False)
    email = Column(String(150), nullable=True)
    base_score = Column(Float, nullable=False, default=5.0)  # Initial core score [1.0 - 10.0]
    current_score = Column(Float, nullable=False, default=5.0)  # Dynamically adjusted score
    is_independent = Column(Boolean, default=False)
    is_active = Column(Boolean, default=True)

    tournament = relationship("Tournament", back_populates="adjudicators")
    institution = relationship("Institution", back_populates="adjudicators")
    explicit_conflicts = relationship(
        "AdjudicatorConflict", back_populates="adjudicator", cascade="all, delete-orphan"
    )
    allocations = relationship("AdjudicatorAllocation", back_populates="adjudicator")
    evaluations = relationship("JudgeEvaluation", back_populates="adjudicator")


class AdjudicatorConflict(Base):
    """Stores additional institutional or personal team conflicts beyond primary institution."""
    __tablename__ = "adjudicator_conflicts"

    id = Column(Integer, primary_key=True, index=True)
    adjudicator_id = Column(Integer, ForeignKey("adjudicators.id"), nullable=False)
    conflicted_institution_id = Column(Integer, ForeignKey("institutions.id"), nullable=True)
    conflicted_team_id = Column(Integer, ForeignKey("teams.id"), nullable=True)
    reason = Column(String(200), default="Institutional / Personal Conflict")

    adjudicator = relationship("Adjudicator", back_populates="explicit_conflicts")


class Round(Base):
    __tablename__ = "rounds"

    id = Column(Integer, primary_key=True, index=True)
    tournament_id = Column(Integer, ForeignKey("tournaments.id"), nullable=False)
    round_number = Column(Integer, nullable=False)
    name = Column(String(100), nullable=False)
    abbreviation = Column(String(20), nullable=False)
    stage = Column(Enum(RoundStage), default=RoundStage.PRELIMINARY)
    status = Column(Enum(RoundStatus), default=RoundStatus.DRAFT)
    starts_at = Column(String(32), default="10:00")
    created_at = Column(DateTime, default=datetime.utcnow)

    tournament = relationship("Tournament", back_populates="rounds")
    motions = relationship("Motion", back_populates="round", cascade="all, delete-orphan")
    rooms = relationship("DebateRoom", back_populates="round", cascade="all, delete-orphan")


class Motion(Base):
    __tablename__ = "motions"

    id = Column(Integer, primary_key=True, index=True)
    round_id = Column(Integer, ForeignKey("rounds.id"), nullable=False)
    reference = Column(String(50), nullable=False, default="M1")
    text = Column(Text, nullable=False)
    info_slide = Column(Text, nullable=True)
    seq = Column(Integer, default=1)

    round = relationship("Round", back_populates="motions")


class DebateRoom(Base):
    __tablename__ = "debate_rooms"

    id = Column(Integer, primary_key=True, index=True)
    round_id = Column(Integer, ForeignKey("rounds.id"), nullable=False)
    venue_name = Column(String(100), nullable=False)
    bracket_points = Column(Float, default=0.0)
    importance_weight = Column(Float, default=5.0)  # 1.0 to 10.0 importance for Hungarian matching
    ballot_confirmed = Column(Boolean, default=False)

    round = relationship("Round", back_populates="rooms")
    team_assignments = relationship(
        "DebateTeamAssignment", back_populates="room", cascade="all, delete-orphan"
    )
    adjudicator_allocations = relationship(
        "AdjudicatorAllocation", back_populates="room", cascade="all, delete-orphan"
    )
    ballot = relationship("Ballot", back_populates="room", uselist=False, cascade="all, delete-orphan")


class DebateTeamAssignment(Base):
    __tablename__ = "debate_team_assignments"

    id = Column(Integer, primary_key=True, index=True)
    room_id = Column(Integer, ForeignKey("debate_rooms.id"), nullable=False)
    team_id = Column(Integer, ForeignKey("teams.id"), nullable=False)
    position = Column(String(16), nullable=False)  # AP: "GOV", "OPP" | BP: "OG", "OO", "CG", "CO"
    points_earned = Column(Integer, nullable=True)  # AP: 1 or 0 | BP: 3, 2, 1, 0
    rank = Column(Integer, nullable=True)  # AP: 1 or 2 | BP: 1, 2, 3, 4
    total_team_speaks = Column(Float, default=0.0)

    room = relationship("DebateRoom", back_populates="team_assignments")
    team = relationship("Team", back_populates="room_assignments")


class AdjudicatorAllocation(Base):
    __tablename__ = "adjudicator_allocations"

    id = Column(Integer, primary_key=True, index=True)
    room_id = Column(Integer, ForeignKey("debate_rooms.id"), nullable=False)
    adjudicator_id = Column(Integer, ForeignKey("adjudicators.id"), nullable=False)
    role = Column(String(20), default="CHAIR")  # CHAIR, PANELLIST, TRAINEE
    assignment_cost = Column(Float, default=0.0)  # Diagnostic Hungarian cost

    room = relationship("DebateRoom", back_populates="adjudicator_allocations")
    adjudicator = relationship("Adjudicator", back_populates="allocations")


class Ballot(Base):
    __tablename__ = "ballots"

    id = Column(Integer, primary_key=True, index=True)
    room_id = Column(Integer, ForeignKey("debate_rooms.id"), unique=True, nullable=False)
    motion_id = Column(Integer, ForeignKey("motions.id"), nullable=True)
    submitted_by = Column(String(150), default="Tab Room Admin")
    notes = Column(Text, nullable=True)
    confirmed_at = Column(DateTime, default=datetime.utcnow)

    room = relationship("DebateRoom", back_populates="ballot")
    speaker_scores = relationship("SpeakerScore", back_populates="ballot", cascade="all, delete-orphan")


class SpeakerScore(Base):
    __tablename__ = "speaker_scores"

    id = Column(Integer, primary_key=True, index=True)
    ballot_id = Column(Integer, ForeignKey("ballots.id"), nullable=False)
    speaker_id = Column(Integer, ForeignKey("speakers.id"), nullable=False)
    team_id = Column(Integer, ForeignKey("teams.id"), nullable=False)
    speech_position = Column(Integer, nullable=False)  # 1, 2, 3 (and 4 for reply in AP)
    score = Column(Float, nullable=False)  # Standard WUDC/AP scale: 68.0 - 82.0
    is_reply = Column(Boolean, default=False)

    ballot = relationship("Ballot", back_populates="speaker_scores")
    speaker = relationship("Speaker", back_populates="scores")


class JudgeEvaluation(Base):
    __tablename__ = "judge_evaluations"

    id = Column(Integer, primary_key=True, index=True)
    adjudicator_id = Column(Integer, ForeignKey("adjudicators.id"), nullable=False)
    round_id = Column(Integer, ForeignKey("rounds.id"), nullable=False)
    evaluator_team_id = Column(Integer, ForeignKey("teams.id"), nullable=True)
    evaluator_name = Column(String(150), nullable=False)
    score = Column(Float, nullable=False)  # 1.0 - 10.0 rating
    comments = Column(Text, nullable=True)
    prior_adj_score = Column(Float, nullable=False)
    updated_adj_score = Column(Float, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)

    adjudicator = relationship("Adjudicator", back_populates="evaluations")


def init_db(database_url: str = "sqlite:///./rgcdc_tab.db"):
    connect_args = {"check_same_thread": False} if database_url.startswith("sqlite") else {}
    engine = create_engine(database_url, connect_args=connect_args)
    Base.metadata.create_all(bind=engine)
    SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    return engine, SessionLocal
