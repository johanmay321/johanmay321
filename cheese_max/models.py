from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from typing import Literal


def _new_id() -> str:
    return str(uuid.uuid4())


# ---------------------------------------------------------------------------
# Conditions
# ---------------------------------------------------------------------------

@dataclass
class Conditions:
    wind_direction: str | None = None        # cardinal, e.g. "NW"
    wind_speed_kph: float | None = None
    water_state: Literal["calm", "choppy", "rough"] | None = None
    temp_celsius: float | None = None

    def to_dict(self) -> dict:
        return {
            "wind_direction": self.wind_direction,
            "wind_speed_kph": self.wind_speed_kph,
            "water_state": self.water_state,
            "temp_celsius": self.temp_celsius,
        }

    @classmethod
    def from_dict(cls, d: dict) -> Conditions:
        return cls(
            wind_direction=d.get("wind_direction"),
            wind_speed_kph=d.get("wind_speed_kph"),
            water_state=d.get("water_state"),
            temp_celsius=d.get("temp_celsius"),
        )


# ---------------------------------------------------------------------------
# Team
# ---------------------------------------------------------------------------

@dataclass
class Team:
    name: str
    abbreviation: str
    conference: Literal["EARC", "IRA", "other"]
    id: str = field(default_factory=_new_id)
    website: str | None = None
    aliases: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "name": self.name,
            "abbreviation": self.abbreviation,
            "conference": self.conference,
            "website": self.website,
            "aliases": self.aliases,
        }

    @classmethod
    def from_dict(cls, d: dict) -> Team:
        return cls(
            id=d["id"],
            name=d["name"],
            abbreviation=d["abbreviation"],
            conference=d["conference"],
            website=d.get("website"),
            aliases=d.get("aliases", []),
        )


# ---------------------------------------------------------------------------
# Regatta
# ---------------------------------------------------------------------------

@dataclass
class Regatta:
    name: str
    date: str                        # ISO-8601 "YYYY-MM-DD"
    course: str
    season: int
    id: str = field(default_factory=_new_id)
    distance_m: int = 2000
    conditions: Conditions = field(default_factory=Conditions)
    notes: str = ""
    source_url: str | None = None
    source_label: str = "manual"     # "row2k" | "earc" | "ira" | "pdf" | "manual"
    staged: bool = True
    approved_at: str | None = None

    def to_dict(self) -> dict:
        return {
            "version": "1.0",
            "id": self.id,
            "name": self.name,
            "date": self.date,
            "course": self.course,
            "season": self.season,
            "distance_m": self.distance_m,
            "conditions": self.conditions.to_dict(),
            "notes": self.notes,
            "source_url": self.source_url,
            "source_label": self.source_label,
            "staged": self.staged,
            "approved_at": self.approved_at,
        }

    @classmethod
    def from_dict(cls, d: dict) -> Regatta:
        return cls(
            id=d["id"],
            name=d["name"],
            date=d["date"],
            course=d["course"],
            season=d["season"],
            distance_m=d.get("distance_m", 2000),
            conditions=Conditions.from_dict(d.get("conditions", {})),
            notes=d.get("notes", ""),
            source_url=d.get("source_url"),
            source_label=d.get("source_label", "manual"),
            staged=d.get("staged", True),
            approved_at=d.get("approved_at"),
        )


# ---------------------------------------------------------------------------
# RaceResult
# ---------------------------------------------------------------------------

UNRESOLVED_TEAM = "__UNRESOLVED__"

@dataclass
class RaceResult:
    team: str                              # canonical abbreviation, or UNRESOLVED_TEAM
    id: str = field(default_factory=_new_id)
    finish_time_seconds: float | None = None
    lane: int | None = None
    placement: int | None = None
    margin_to_winner_seconds: float | None = None
    verified: bool = False
    dnf: bool = False
    dns: bool = False
    notes: str = ""                        # raw_team_name stored here if unresolved

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "team": self.team,
            "finish_time_seconds": self.finish_time_seconds,
            "lane": self.lane,
            "placement": self.placement,
            "margin_to_winner_seconds": self.margin_to_winner_seconds,
            "verified": self.verified,
            "dnf": self.dnf,
            "dns": self.dns,
            "notes": self.notes,
        }

    @classmethod
    def from_dict(cls, d: dict) -> RaceResult:
        return cls(
            id=d["id"],
            team=d["team"],
            finish_time_seconds=d.get("finish_time_seconds"),
            lane=d.get("lane"),
            placement=d.get("placement"),
            margin_to_winner_seconds=d.get("margin_to_winner_seconds"),
            verified=d.get("verified", False),
            dnf=d.get("dnf", False),
            dns=d.get("dns", False),
            notes=d.get("notes", ""),
        )


# ---------------------------------------------------------------------------
# Race
# ---------------------------------------------------------------------------

BoatClass = Literal["V1", "V2", "V3", "LW1", "LW2", "JV", "N", "F"]
EventType = Literal["sprint", "head"]

@dataclass
class Race:
    regatta_id: str
    boat_class: BoatClass
    event_type: EventType
    id: str = field(default_factory=_new_id)
    race_name: str | None = None
    results: list[RaceResult] = field(default_factory=list)
    staged: bool = True
    rejected: bool = False

    def to_dict(self) -> dict:
        return {
            "version": "1.0",
            "id": self.id,
            "regatta_id": self.regatta_id,
            "boat_class": self.boat_class,
            "event_type": self.event_type,
            "race_name": self.race_name,
            "staged": self.staged,
            "rejected": self.rejected,
            "results": [r.to_dict() for r in self.results],
        }

    @classmethod
    def from_dict(cls, d: dict) -> Race:
        return cls(
            id=d["id"],
            regatta_id=d["regatta_id"],
            boat_class=d["boat_class"],
            event_type=d["event_type"],
            race_name=d.get("race_name"),
            staged=d.get("staged", True),
            rejected=d.get("rejected", False),
            results=[RaceResult.from_dict(r) for r in d.get("results", [])],
        )


# ---------------------------------------------------------------------------
# Staged bundle warning
# ---------------------------------------------------------------------------

@dataclass
class StagedWarning:
    type: str                   # "unresolved_team" | "time_parse_error" | "duplicate_uid"
    raw_value: str
    race_id: str | None = None
    suggestion: str | None = None
    notes: str = ""

    def to_dict(self) -> dict:
        return {
            "type": self.type,
            "raw_value": self.raw_value,
            "race_id": self.race_id,
            "suggestion": self.suggestion,
            "notes": self.notes,
        }

    @classmethod
    def from_dict(cls, d: dict) -> StagedWarning:
        return cls(
            type=d["type"],
            raw_value=d["raw_value"],
            race_id=d.get("race_id"),
            suggestion=d.get("suggestion"),
            notes=d.get("notes", ""),
        )


# ---------------------------------------------------------------------------
# Staged bundle (the unit of review)
# ---------------------------------------------------------------------------

@dataclass
class StagedBundle:
    source: str               # "row2k" | "earc" | "pdf" | "manual" | "team"
    season: int
    scraped_at: str           # ISO-8601 datetime string
    id: str = field(default_factory=_new_id)
    status: Literal["pending", "approved", "rejected"] = "pending"
    regattas: list[Regatta] = field(default_factory=list)
    races: list[Race] = field(default_factory=list)
    warnings: list[StagedWarning] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "version": "1.0",
            "bundle_id": self.id,
            "source": self.source,
            "scraped_at": self.scraped_at,
            "season": self.season,
            "status": self.status,
            "warnings": [w.to_dict() for w in self.warnings],
            "regattas": [r.to_dict() for r in self.regattas],
            "races": [r.to_dict() for r in self.races],
        }

    @classmethod
    def from_dict(cls, d: dict) -> StagedBundle:
        return cls(
            id=d["bundle_id"],
            source=d["source"],
            season=d["season"],
            scraped_at=d["scraped_at"],
            status=d.get("status", "pending"),
            warnings=[StagedWarning.from_dict(w) for w in d.get("warnings", [])],
            regattas=[Regatta.from_dict(r) for r in d.get("regattas", [])],
            races=[Race.from_dict(r) for r in d.get("races", [])],
        )


# ---------------------------------------------------------------------------
# Athlete + Boat (future use — defined now for stable JSON schema)
# ---------------------------------------------------------------------------

@dataclass
class Athlete:
    name: str
    team_id: str
    id: str = field(default_factory=_new_id)
    years_active: list[int] = field(default_factory=list)
    notes: str = ""

    def to_dict(self) -> dict:
        return {
            "version": "1.0",
            "id": self.id,
            "name": self.name,
            "team_id": self.team_id,
            "years_active": self.years_active,
            "notes": self.notes,
        }

    @classmethod
    def from_dict(cls, d: dict) -> Athlete:
        return cls(
            id=d["id"],
            name=d["name"],
            team_id=d["team_id"],
            years_active=d.get("years_active", []),
            notes=d.get("notes", ""),
        )


@dataclass
class Boat:
    team_id: str
    boat_class: BoatClass
    season: int
    id: str = field(default_factory=_new_id)
    athlete_ids: list[str] = field(default_factory=list)
    notes: str = ""

    def to_dict(self) -> dict:
        return {
            "version": "1.0",
            "id": self.id,
            "team_id": self.team_id,
            "boat_class": self.boat_class,
            "season": self.season,
            "athlete_ids": self.athlete_ids,
            "notes": self.notes,
        }

    @classmethod
    def from_dict(cls, d: dict) -> Boat:
        return cls(
            id=d["id"],
            team_id=d["team_id"],
            boat_class=d["boat_class"],
            season=d["season"],
            athlete_ids=d.get("athlete_ids", []),
            notes=d.get("notes", ""),
        )
