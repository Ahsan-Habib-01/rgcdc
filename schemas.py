"""
RGCDC Debate Tournament Tabulation System
Pydantic v1 & v2 Compatible Schemas & Format-Aware Validation
"""

from typing import List, Optional
from pydantic import BaseModel, Field


class FormatUpdateRequest(BaseModel):
    name: str = Field(default="3rd RGCDC Dialogues 2026")
    host_institution: str = Field(default="Rangpur Government College Debating Club (RGCDC)")
    format: str = Field(default="AP")
    total_prelim_rounds: int = Field(default=5, ge=1, le=12)

    def __init__(self, **data):
        super().__init__(**data)
        if self.format not in ("AP", "BP"):
            raise ValueError("Format must be either 'AP' or 'BP'.")


class SpeakerInput(BaseModel):
    name: str = Field(..., min_length=1, max_length=150)
    email: Optional[str] = Field(default=None, max_length=150)
    novice: bool = False


class TeamCreateRequest(BaseModel):
    reference_name: str = Field(..., min_length=1, max_length=150)
    short_name: str = Field(..., min_length=1, max_length=64)
    institution_name: str = Field(..., min_length=1, max_length=200)
    institution_code: str = Field(..., min_length=1, max_length=32)
    format: str = Field(default="AP")
    speakers: List[SpeakerInput]

    def __init__(self, **data):
        super().__init__(**data)
        if self.format not in ("AP", "BP"):
            raise ValueError("Format must be 'AP' or 'BP'.")
        expected = 3 if self.format == "AP" else 2
        if len(self.speakers) != expected:
            raise ValueError(
                f"Format '{self.format}' strictly requires {expected} speakers per team (received {len(self.speakers)})."
            )


class AdjudicatorCreateRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=150)
    email: Optional[str] = Field(default=None, max_length=150)
    institution_name: str = Field(..., min_length=1, max_length=200)
    institution_code: str = Field(..., min_length=1, max_length=32)
    base_score: float = Field(default=6.5, ge=1.0, le=10.0)
    additional_conflict_institution_codes: List[str] = Field(default_factory=list)
    is_independent: bool = False


class MotionCreateRequest(BaseModel):
    round_number: int = Field(..., ge=1)
    reference: str = Field(default="R1", max_length=50)
    text: str = Field(..., min_length=5)
    info_slide: Optional[str] = None


class SpeakerMarkInput(BaseModel):
    speaker_id: int
    score: float = Field(..., ge=50.0, le=100.0)


class TeamBallotResultInput(BaseModel):
    team_id: int
    position: str
    rank: int = Field(..., ge=1, le=4)
    speaker_marks: List[SpeakerMarkInput]


class BallotSubmitRequest(BaseModel):
    room_id: int
    submitted_by: str = Field(default="Chair / Tab Room")
    notes: Optional[str] = None
    team_results: List[TeamBallotResultInput]


class JudgeEvaluationRequest(BaseModel):
    adjudicator_id: int
    round_number: int = Field(..., ge=1)
    evaluator_team_id: Optional[int] = None
    evaluator_name: str = Field(..., min_length=1)
    score: float = Field(..., ge=1.0, le=10.0)
    comments: Optional[str] = None
