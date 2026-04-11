"""
row2k.com scraper.

Row2k is the source of truth for race times.  This module fetches the
season results index, discovers regatta pages, and parses result tables
into StagedBundle objects.

Lightweight results may appear under cat=1 (Collegiate Men) or cat=6
(IRA Lightweight Men) depending on the regatta.  The scraper fetches
both and de-duplicates by UID.  Boat class and lightweight flag are
determined by parsing the race/event name within each result table.
"""
from __future__ import annotations

import logging
import re
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import NamedTuple
from urllib.parse import urlencode, urlparse, parse_qs

import requests
from bs4 import BeautifulSoup

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

logger = logging.getLogger(__name__)

BASE_URL = "https://www.row2k.com"
RESULTS_INDEX = f"{BASE_URL}/results/index.cfm"
RESULTS_PAGE = f"{BASE_URL}/results/resultspage.cfm"

# Category codes to scrape; lightweight may appear in either
CATEGORIES = [1, 6]

_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/123.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
}

# -----------------------------------------------------------------------
# Boat-class detection from raw race/event name strings
# -----------------------------------------------------------------------

_BOAT_CLASS_PATTERNS: list[tuple[re.Pattern, str]] = [
    # LW flag handled separately — not a class label
    (re.compile(r"\blight\s*weight\b|\bLW\b|\blt\b", re.I), "LW_FLAG"),
    # Most specific multi-word patterns first
    (re.compile(r"\bjunior\s*varsity\b|\bJV\b", re.I), "JV"),
    (re.compile(r"\b(freshman|novice|frosh)\b", re.I), "F"),
    (re.compile(r"\b(second|2nd|2v)\s*(varsity|eight|4\+)?\b", re.I), "V2"),
    (re.compile(r"\b(third|3rd|3v)\s*(varsity|eight|4\+)?\b", re.I), "V3"),
    (re.compile(r"\b(first|1st|1v)\s*(varsity|eight|4\+)?\b", re.I), "V1"),
    # Generic fallback — matches plain "Varsity Eight"
    (re.compile(r"\bvarsity\s*(eight|8\+|four|4\+)?\b", re.I), "V1"),
]


def _detect_boat_class(name: str) -> str:
    """Return boat class string from a raw race name. Defaults to 'V1'."""
    is_lw = bool(re.search(r"\blight\s*weight\b|\bLW\b", name, re.I))
    boat = "V1"
    # Patterns ordered most-specific first; stop at first match (skip LW_FLAG)
    for pattern, label in _BOAT_CLASS_PATTERNS:
        if label == "LW_FLAG":
            continue
        if pattern.search(name):
            boat = label
            break  # first specific match wins; generic "varsity" never overwrites
    if is_lw:
        return "LW1" if boat == "V1" else ("LW2" if boat == "V2" else boat)
    return boat


def _is_lightweight_race(name: str) -> bool:
    return bool(re.search(r"\blight\s*weight\b|\bLW\b|\blt\b", name, re.I))


# -----------------------------------------------------------------------
# Time parsing
# -----------------------------------------------------------------------

def _parse_time(raw: str) -> float | None:
    """
    Parse a race time string into total seconds.
    Handles formats like:  6:01.4  |  5:58  |  DNF  |  DNS  |  6:01:04
    Returns None for non-numeric entries.
    """
    s = raw.strip().upper()
    if not s or s in ("DNF", "DNS", "SCR", "DQ", "---", "NT", "N/T"):
        return None
    # mm:ss.t or mm:ss
    m = re.match(r"^(\d+):(\d+)(?:\.(\d+))?$", s)
    if m:
        minutes = int(m.group(1))
        seconds = int(m.group(2))
        tenths = m.group(3)
        frac = float(f"0.{tenths}") if tenths else 0.0
        return minutes * 60 + seconds + frac
    # Plain seconds
    try:
        return float(s)
    except ValueError:
        return None


def _is_dnf(raw: str) -> bool:
    return raw.strip().upper() in ("DNF", "DQ")


def _is_dns(raw: str) -> bool:
    return raw.strip().upper() in ("DNS", "SCR")


# -----------------------------------------------------------------------
# HTML fetch helpers
# -----------------------------------------------------------------------

class RegattaRef(NamedTuple):
    uid: str
    cat: int
    title: str
    url: str


def _get(url: str, params: dict | None = None, retries: int = 3) -> BeautifulSoup | None:
    delay = 1.0
    for attempt in range(retries):
        try:
            resp = requests.get(url, params=params, headers=_HEADERS, timeout=20)
            resp.raise_for_status()
            return BeautifulSoup(resp.text, "lxml")
        except Exception as exc:
            logger.warning("Fetch failed (%s) attempt %d/%d: %s", url, attempt + 1, retries, exc)
            if attempt < retries - 1:
                time.sleep(delay)
                delay *= 2
    return None


# -----------------------------------------------------------------------
# Index scraping — discover all regatta UIDs for a year
# -----------------------------------------------------------------------

def _scrape_index(year: int, cat: int) -> list[RegattaRef]:
    """Return list of RegattaRef for all regattas listed in a category/year."""
    soup = _get(RESULTS_INDEX, params={"year": year, "cat": cat})
    if soup is None:
        return []

    refs: list[RegattaRef] = []
    seen_uids: set[str] = set()

    for a in soup.find_all("a", href=True):
        href: str = a["href"]
        if "resultspage.cfm" not in href:
            continue
        # Parse UID from query string
        if href.startswith("/"):
            href = BASE_URL + href
        parsed = urlparse(href)
        qs = parse_qs(parsed.query, keep_blank_values=False)
        uid = qs.get("UID", qs.get("uid", [None]))[0]
        if uid is None or uid in seen_uids:
            continue
        seen_uids.add(uid)
        title = a.get_text(strip=True) or f"UID {uid}"
        refs.append(RegattaRef(uid=uid, cat=cat, title=title, url=href))

    return refs


# -----------------------------------------------------------------------
# Result page scraping
# -----------------------------------------------------------------------

def _scrape_regatta_page(
    ref: RegattaRef,
    resolver: TeamResolver,
    season: int,
    category_filter: str | None = None,
) -> tuple[list[Regatta], list[Race], list[StagedWarning]]:
    """
    Scrape one regatta results page.  Returns (regattas, races, warnings).
    A single URL can contain multiple events/races.
    """
    soup = _get(ref.url)
    if soup is None:
        return [], [], [StagedWarning(
            type="fetch_error",
            raw_value=ref.url,
            notes=f"Failed to fetch {ref.url}",
        )]

    warnings: list[StagedWarning] = []
    races: list[Race] = []

    # Try to extract regatta metadata from the page title / header
    page_title = soup.find("title")
    regatta_name = page_title.get_text(strip=True) if page_title else ref.title
    regatta_name = re.sub(r"\s*[-|]\s*row2k.*", "", regatta_name, flags=re.I).strip()

    # Attempt to find a date in the page
    date_str = _extract_date(soup) or f"{season}-01-01"

    regatta = Regatta(
        name=regatta_name,
        date=date_str,
        course=_extract_course(soup) or "",
        season=season,
        source_url=ref.url,
        source_label="row2k",
        staged=True,
    )

    # Conditions: row2k does not consistently publish wind/water data,
    # so we leave them None and let the user fill them in during review.
    # If a conditions note is present, store it in regatta.notes.
    conditions_note = _extract_conditions_note(soup)
    if conditions_note:
        regatta.notes = conditions_note

    # Find all result tables.  Row2k typically uses <table> elements with
    # a header row naming the event.
    result_tables = _find_result_tables(soup)

    if not result_tables:
        warnings.append(StagedWarning(
            type="no_tables_found",
            raw_value=ref.url,
            notes="Could not find any result tables on page",
        ))
        return [regatta], [], warnings

    herenow_links = _find_herenow_links(soup)

    for table_info in result_tables:
        race_name = table_info["race_name"]

        # Apply category filter if supplied
        if category_filter:
            filter_lw = category_filter.lower() == "lightweight"
            is_lw = _is_lightweight_race(race_name)
            if filter_lw and not is_lw:
                continue
            if not filter_lw and is_lw:
                continue

        boat_class = _detect_boat_class(race_name)
        event_type = "head" if re.search(r"\bhead\b", race_name, re.I) else "sprint"

        race = Race(
            regatta_id=regatta.id,
            boat_class=boat_class,
            event_type=event_type,
            race_name=race_name,
            staged=True,
        )

        # Note any HereNow link for this race in the first result's notes
        herenow_note = ""
        if herenow_links:
            herenow_note = f"HereNow timing: {herenow_links[0]}"

        results, race_warnings = _parse_result_rows(
            table_info["rows"],
            race.id,
            resolver,
            herenow_note,
        )
        warnings.extend(race_warnings)
        race.results = results

        if results:
            races.append(race)

    return [regatta], races, warnings


def _find_result_tables(soup: BeautifulSoup) -> list[dict]:
    """
    Extract result tables from the page.  Row2k pages vary in structure;
    this attempts several heuristics.
    """
    tables = []

    # Strategy 1: look for <h2>/<h3> followed by a <table>
    for header in soup.find_all(["h2", "h3", "h4", "strong", "b"]):
        header_text = header.get_text(strip=True)
        if not header_text or len(header_text) < 4:
            continue
        # Look for next sibling table
        nxt = header.find_next_sibling()
        while nxt and nxt.name not in ("table", "h2", "h3", "h4"):
            nxt = nxt.find_next_sibling()
        if nxt and nxt.name == "table":
            rows = _extract_table_rows(nxt)
            if rows:
                tables.append({"race_name": header_text, "rows": rows})

    if tables:
        return tables

    # Strategy 2: each <table> that has a time-like column
    for table in soup.find_all("table"):
        rows = _extract_table_rows(table)
        if not rows:
            continue
        # Guess race name from nearest preceding heading or caption
        caption = table.find("caption")
        name = caption.get_text(strip=True) if caption else "Unknown Event"
        tables.append({"race_name": name, "rows": rows})

    return tables


def _extract_table_rows(table) -> list[list[str]]:
    rows = []
    for tr in table.find_all("tr"):
        cells = [td.get_text(separator=" ", strip=True) for td in tr.find_all(["td", "th"])]
        if cells:
            rows.append(cells)
    return rows


def _parse_result_rows(
    rows: list[list[str]],
    race_id: str,
    resolver: TeamResolver,
    herenow_note: str,
) -> tuple[list[RaceResult], list[StagedWarning]]:
    """
    Parse raw table rows into RaceResult objects.
    Handles variable column ordering by sniffing the header row.
    """
    if not rows:
        return [], []

    warnings: list[StagedWarning] = []
    results: list[RaceResult] = []

    # Detect header row
    header_idx = None
    col_place = col_team = col_time = col_lane = col_margin = None

    for i, row in enumerate(rows):
        lowered = [c.lower() for c in row]
        if any(kw in lowered for kw in ("place", "finish", "pl", "#")):
            header_idx = i
            for j, h in enumerate(lowered):
                if h in ("place", "pl", "finish", "#", "rank"):
                    col_place = j
                elif h in ("school", "team", "crew", "name", "entry"):
                    col_team = j
                elif h in ("time", "finish time", "elapsed", "adj. time", "adjusted"):
                    col_time = j
                elif h in ("lane",):
                    col_lane = j
                elif h in ("margin", "diff", "gap", "behind"):
                    col_margin = j
            break

    start = (header_idx + 1) if header_idx is not None else 0

    # Fallback column guesses if no header found
    if col_team is None:
        col_team = 1
    if col_time is None:
        col_time = 2
    if col_place is None:
        col_place = 0

    winner_time: float | None = None
    placement = 0

    for row in rows[start:]:
        if not row or len(row) < 2:
            continue
        # Skip separator/total rows
        if any(kw in " ".join(row).lower() for kw in ("total", "points", "---")):
            continue

        raw_team = row[col_team] if col_team < len(row) else ""
        raw_time = row[col_time] if col_time is not None and col_time < len(row) else ""

        if not raw_team:
            continue

        team_abbr = resolver.resolve(raw_team)
        if team_abbr is None:
            team_abbr = UNRESOLVED_TEAM
            warnings.append(StagedWarning(
                type="unresolved_team",
                raw_value=raw_team,
                race_id=race_id,
                suggestion=resolver.suggest(raw_team),
            ))

        finish_time = _parse_time(raw_time)
        dnf = _is_dnf(raw_time)
        dns = _is_dns(raw_time)

        placement += 1

        if finish_time is not None and winner_time is None and placement == 1:
            winner_time = finish_time

        margin = None
        if finish_time is not None and winner_time is not None:
            margin = finish_time - winner_time
        elif col_margin is not None and col_margin < len(row):
            margin = _parse_time(row[col_margin])

        place_val = None
        if col_place < len(row):
            try:
                place_val = int(row[col_place])
            except ValueError:
                place_val = placement

        lane_val = None
        if col_lane is not None and col_lane < len(row):
            try:
                lane_val = int(row[col_lane])
            except ValueError:
                pass

        notes = herenow_note
        if team_abbr == UNRESOLVED_TEAM:
            notes = f"raw_team_name={raw_team!r}" + (f"; {notes}" if notes else "")

        results.append(RaceResult(
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

    return results, warnings


# -----------------------------------------------------------------------
# Page metadata helpers
# -----------------------------------------------------------------------

_DATE_PATTERN = re.compile(
    r"(January|February|March|April|May|June|July|August|September|October|November|December)"
    r"\s+\d{1,2},?\s+\d{4}",
    re.I,
)
_DATE_FORMAT = "%B %d, %Y"


def _extract_date(soup: BeautifulSoup) -> str | None:
    text = soup.get_text(" ")
    m = _DATE_PATTERN.search(text)
    if m:
        try:
            dt = datetime.strptime(m.group().replace(",", ""), _DATE_FORMAT.replace(",", ""))
            return dt.strftime("%Y-%m-%d")
        except ValueError:
            pass
    return None


def _extract_course(soup: BeautifulSoup) -> str | None:
    text = soup.get_text(" ")
    # Look for common course name patterns
    for pattern in [
        r"(?:on|at|course[:\s]+)([\w\s]+(?:Lake|River|Canal|Basin|Reservoir|Cove|Bay)[^\n,]+)",
        r"(Lake\s+\w+|[\w\s]+River)",
    ]:
        m = re.search(pattern, text, re.I)
        if m:
            return m.group(1).strip()
    return None


def _extract_conditions_note(soup: BeautifulSoup) -> str:
    text = soup.get_text(" ")
    for pattern in [
        r"(condition[s]?[:\s]+[^\n.]+)",
        r"(wind[:\s]+[^\n.]+)",
        r"(water[:\s]+[^\n.]+)",
    ]:
        m = re.search(pattern, text, re.I)
        if m:
            return m.group(1).strip()[:200]
    return ""


def _find_herenow_links(soup: BeautifulSoup) -> list[str]:
    links = []
    for a in soup.find_all("a", href=True):
        if "herenow" in a["href"].lower():
            links.append(a["href"])
    return links


# -----------------------------------------------------------------------
# Public API
# -----------------------------------------------------------------------

def scrape_season(
    year: int,
    resolver: TeamResolver,
    category_filter: str | None = None,
) -> StagedBundle:
    """
    Scrape all row2k collegiate rowing results for a given year.

    Parameters
    ----------
    year            : season year (e.g. 2025)
    resolver        : TeamResolver instance for name normalisation
    category_filter : "lightweight" to restrict to lightweight events only,
                      None for all events
    """
    now = datetime.now(timezone.utc).isoformat()
    bundle = StagedBundle(source="row2k", season=year, scraped_at=now)

    seen_uids: set[str] = set()
    all_refs: list[RegattaRef] = []

    for cat in CATEGORIES:
        refs = _scrape_index(year, cat)
        for ref in refs:
            if ref.uid not in seen_uids:
                seen_uids.add(ref.uid)
                all_refs.append(ref)
        time.sleep(0.5)  # polite delay between index requests

    logger.info("Found %d unique regatta UIDs for %d", len(all_refs), year)

    for ref in all_refs:
        regattas, races, warnings = _scrape_regatta_page(
            ref, resolver, year, category_filter=category_filter
        )
        bundle.regattas.extend(regattas)
        bundle.races.extend(races)
        bundle.warnings.extend(warnings)
        time.sleep(0.75)  # polite delay between result pages

    return bundle


def scrape_regatta_url(
    url: str,
    season: int,
    resolver: TeamResolver,
    category_filter: str | None = None,
) -> StagedBundle:
    """Scrape a specific row2k regatta result page by URL."""
    now = datetime.now(timezone.utc).isoformat()
    bundle = StagedBundle(source="row2k", season=season, scraped_at=now)

    parsed = urlparse(url)
    qs = parse_qs(parsed.query)
    uid = qs.get("UID", qs.get("uid", ["unknown"]))[0]
    cat_val = int(qs.get("cat", [1])[0])

    ref = RegattaRef(uid=uid, cat=cat_val, title="", url=url)
    regattas, races, warnings = _scrape_regatta_page(
        ref, resolver, season, category_filter=category_filter
    )
    bundle.regattas.extend(regattas)
    bundle.races.extend(races)
    bundle.warnings.extend(warnings)
    return bundle
