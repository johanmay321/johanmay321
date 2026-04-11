"""
PDF result sheet parser.

Official regatta PDFs (EARC, IRA, etc.) typically contain tabular layouts
with a boat-class header followed by result rows.  This module uses
pdfplumber for table extraction and a state-machine approach to identify
race sections.
"""
from __future__ import annotations

import logging
import re
from datetime import datetime, timezone
from pathlib import Path

from cheese_max.models import (
    Conditions,
    Race,
    RaceResult,
    Regatta,
    StagedBundle,
    StagedWarning,
    UNRESOLVED_TEAM,
)
from cheese_max.scrapers.team_resolver import TeamResolver
from cheese_max.scrapers.row2k import _detect_boat_class, _parse_time, _is_dnf, _is_dns

logger = logging.getLogger(__name__)

# Patterns that signal the start of a new race section in the PDF
_RACE_HEADER_PATTERNS = [
    re.compile(r"\b(varsity|lightweight|JV|junior varsity|novice|freshman|frosh)\b", re.I),
    re.compile(r"\b(1st|2nd|3rd|first|second|third)\s*(varsity|eight|four)\b", re.I),
    re.compile(r"\beight\b|\b8\+\b|\bfour\b|\b4\+\b|\bpair\b|\bscull\b", re.I),
    re.compile(r"\b(V1|V2|V3|LW1|LW2|JV)\b"),
    re.compile(r"\bGrand\s+Final\b|\bFinal\s+[A-F]\b|\bHeat\s+\d+\b", re.I),
]

_TIME_PATTERN = re.compile(r"\d+:\d{2}(?:\.\d+)?")
_PLACEMENT_PATTERN = re.compile(r"^\d{1,2}$")


def _looks_like_race_header(text: str) -> bool:
    """Return True if this text row looks like a boat-class/event header."""
    if not text or len(text.strip()) < 3:
        return False
    return any(p.search(text) for p in _RACE_HEADER_PATTERNS)


def _looks_like_result_row(cells: list[str]) -> bool:
    """Return True if the row contains at least a team name and a time or placement."""
    has_time = any(_TIME_PATTERN.search(c) for c in cells)
    has_place = any(_PLACEMENT_PATTERN.match(c.strip()) for c in cells)
    has_text = any(len(c.strip()) > 2 for c in cells)
    return has_text and (has_time or has_place)


def _extract_season_from_text(text: str, default: int | None = None) -> int | None:
    m = re.search(r"\b(20\d{2})\b", text)
    if m:
        return int(m.group(1))
    return default


def _extract_date_from_text(text: str) -> str | None:
    patterns = [
        (re.compile(
            r"(January|February|March|April|May|June|July|August|September|October|November|December)"
            r"\s+\d{1,2},?\s+20\d{2}", re.I
        ), "%B %d %Y"),
        (re.compile(r"\d{1,2}/\d{1,2}/(20\d{2})"), None),
    ]
    for pat, fmt in patterns:
        m = pat.search(text)
        if m:
            if fmt:
                try:
                    dt = datetime.strptime(m.group().replace(",", ""), fmt)
                    return dt.strftime("%Y-%m-%d")
                except ValueError:
                    pass
    return None


class _RaceAccumulator:
    """Mutable state for one race being built as the parser reads rows."""
    def __init__(self, regatta_id: str, race_name: str) -> None:
        self.regatta_id = regatta_id
        self.race_name = race_name
        self.boat_class = _detect_boat_class(race_name)
        self.event_type = "head" if re.search(r"\bhead\b", race_name, re.I) else "sprint"
        self.raw_rows: list[list[str]] = []

    def build_race(
        self,
        resolver: TeamResolver,
        warnings: list[StagedWarning],
    ) -> Race | None:
        race = Race(
            regatta_id=self.regatta_id,
            boat_class=self.boat_class,
            event_type=self.event_type,
            race_name=self.race_name,
            staged=True,
        )

        # Guess column positions from the first row that has a time
        col_team, col_time, col_place, col_lane = 1, 2, 0, None

        for row in self.raw_rows:
            lowered = [c.strip().lower() for c in row]
            if any(h in lowered for h in ("school", "team", "crew", "name", "entry")):
                for i, h in enumerate(lowered):
                    if h in ("school", "team", "crew", "name", "entry"):
                        col_team = i
                    elif h in ("time", "finish", "elapsed"):
                        col_time = i
                    elif h in ("place", "pl", "#", "rank"):
                        col_place = i
                    elif h == "lane":
                        col_lane = i
                break  # header found

        winner_time: float | None = None
        placement = 0

        for row in self.raw_rows:
            if len(row) < 2:
                continue
            raw_team = row[col_team] if col_team < len(row) else ""
            raw_time = row[col_time] if col_time < len(row) else ""

            if not raw_team or not raw_team.strip():
                continue

            # Skip obvious header rows
            if any(h in raw_team.lower() for h in ("school", "team", "crew", "entry", "place", "time")):
                continue

            team_abbr = resolver.resolve(raw_team)
            if team_abbr is None:
                team_abbr = UNRESOLVED_TEAM
                warnings.append(StagedWarning(
                    type="unresolved_team",
                    raw_value=raw_team,
                    race_id=race.id,
                    suggestion=resolver.suggest(raw_team),
                ))

            finish_time = _parse_time(raw_time)
            dnf = _is_dnf(raw_time)
            dns = _is_dns(raw_time)

            placement += 1
            if finish_time is not None and winner_time is None:
                winner_time = finish_time

            margin = None
            if finish_time is not None and winner_time is not None:
                margin = finish_time - winner_time

            place_val: int | None = None
            if col_place < len(row):
                try:
                    place_val = int(row[col_place].strip())
                except ValueError:
                    place_val = placement

            lane_val: int | None = None
            if col_lane is not None and col_lane < len(row):
                try:
                    lane_val = int(row[col_lane].strip())
                except ValueError:
                    pass

            notes = ""
            if team_abbr == UNRESOLVED_TEAM:
                notes = f"raw_team_name={raw_team!r}"

            race.results.append(RaceResult(
                team=team_abbr,
                finish_time_seconds=finish_time,
                lane=lane_val,
                placement=place_val or placement,
                margin_to_winner_seconds=margin,
                verified=False,
                dnf=dnf,
                dns=dns,
                notes=notes,
            ))

        return race if race.results else None


def parse_pdf(
    path: Path,
    resolver: TeamResolver,
    season: int | None = None,
) -> StagedBundle:
    """
    Parse a PDF race results sheet and return a StagedBundle.

    Parameters
    ----------
    path     : path to the PDF file
    resolver : TeamResolver for normalising team names
    season   : override season year; if None, attempt to extract from PDF text
    """
    try:
        import pdfplumber
    except ImportError:
        raise ImportError(
            "pdfplumber is required for PDF parsing. "
            "Install it with:  pip install pdfplumber"
        )

    now = datetime.now(timezone.utc).isoformat()
    bundle = StagedBundle(source="pdf", season=season or 0, scraped_at=now)
    warnings: list[StagedWarning] = []

    with pdfplumber.open(path) as pdf:
        full_text = "\n".join(
            page.extract_text() or "" for page in pdf.pages
        )

        # Extract season / date from text if not provided
        if season is None:
            season = _extract_season_from_text(full_text) or datetime.now().year
            bundle.season = season

        date_str = _extract_date_from_text(full_text) or f"{season}-01-01"

        # Build a Regatta from the PDF filename / title
        pdf_title = re.sub(r"[_\-]+", " ", path.stem).title()
        regatta = Regatta(
            name=pdf_title,
            date=date_str,
            course="",
            season=season,
            source_url=str(path.resolve()),
            source_label="pdf",
            staged=True,
        )

        races: list[Race] = []
        current: _RaceAccumulator | None = None

        def _flush(acc: _RaceAccumulator | None) -> None:
            if acc is not None:
                r = acc.build_race(resolver, warnings)
                if r:
                    races.append(r)

        for page in pdf.pages:
            # Try structured table extraction first
            tables = page.extract_tables()
            if tables:
                for table in tables:
                    for row in table:
                        if row is None:
                            continue
                        cells = [str(c).strip() if c is not None else "" for c in row]
                        row_text = " ".join(cells)

                        if _looks_like_race_header(row_text):
                            _flush(current)
                            current = _RaceAccumulator(regatta.id, row_text)
                        elif current is not None and _looks_like_result_row(cells):
                            current.raw_rows.append(cells)
            else:
                # Fallback: line-by-line text parsing
                text = page.extract_text() or ""
                for line in text.splitlines():
                    line = line.strip()
                    if _looks_like_race_header(line):
                        _flush(current)
                        current = _RaceAccumulator(regatta.id, line)
                    elif current is not None and line:
                        # Split on 2+ spaces as columns
                        cells = re.split(r"\s{2,}", line)
                        if _looks_like_result_row(cells):
                            current.raw_rows.append(cells)

        _flush(current)

    bundle.regattas.append(regatta)
    bundle.races.extend(races)
    bundle.warnings.extend(warnings)

    return bundle
