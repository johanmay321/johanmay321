"""
EARC (Eastern Association of Rowing Colleges) results scraper.

Primary source: earc.qra.org
The EARC site structure is less consistent than row2k, so this scraper
is more exploratory.  Results are staged for mandatory human review.
"""
from __future__ import annotations

import logging
import re
import time
from datetime import datetime, timezone

import requests
from bs4 import BeautifulSoup

from cheese_max.models import (
    Race,
    RaceResult,
    Regatta,
    StagedBundle,
    StagedWarning,
    UNRESOLVED_TEAM,
)
from cheese_max.scrapers.team_resolver import TeamResolver
from cheese_max.scrapers.row2k import (
    _detect_boat_class,
    _parse_time,
    _is_dnf,
    _is_dns,
    _extract_date,
    _extract_course,
    _HEADERS,
)

logger = logging.getLogger(__name__)

EARC_BASE = "https://earc.qra.org"


def _get(url: str, retries: int = 3) -> BeautifulSoup | None:
    delay = 1.0
    for attempt in range(retries):
        try:
            resp = requests.get(url, headers=_HEADERS, timeout=20)
            resp.raise_for_status()
            return BeautifulSoup(resp.text, "lxml")
        except Exception as exc:
            logger.warning("EARC fetch failed (%s) attempt %d/%d: %s", url, attempt + 1, retries, exc)
            if attempt < retries - 1:
                time.sleep(delay)
                delay *= 2
    return None


def _parse_earc_table(
    table,
    race_name: str,
    regatta_id: str,
    resolver: TeamResolver,
    warnings: list[StagedWarning],
) -> Race | None:
    """Parse a single result table into a Race object."""
    rows = []
    for tr in table.find_all("tr"):
        cells = [td.get_text(separator=" ", strip=True) for td in tr.find_all(["td", "th"])]
        if cells:
            rows.append(cells)

    if not rows:
        return None

    race = Race(
        regatta_id=regatta_id,
        boat_class=_detect_boat_class(race_name),
        event_type="head" if re.search(r"\bhead\b", race_name, re.I) else "sprint",
        race_name=race_name,
        staged=True,
    )

    # Detect header row
    col_team, col_time, col_place = 1, 2, 0
    for i, row in enumerate(rows):
        lowered = [c.lower() for c in row]
        if any(h in lowered for h in ("school", "team", "crew", "name")):
            for j, h in enumerate(lowered):
                if h in ("school", "team", "crew", "name", "entry"):
                    col_team = j
                elif h in ("time", "finish", "elapsed", "adjusted"):
                    col_time = j
                elif h in ("place", "pl", "#", "rank"):
                    col_place = j
            rows = rows[i + 1:]
            break

    winner_time: float | None = None
    placement = 0

    for row in rows:
        if len(row) < 2:
            continue
        raw_team = row[col_team] if col_team < len(row) else ""
        raw_time = row[col_time] if col_time < len(row) else ""

        if not raw_team.strip():
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
        placement += 1
        if finish_time is not None and winner_time is None:
            winner_time = finish_time

        margin = (finish_time - winner_time) if (finish_time is not None and winner_time is not None) else None

        place_val: int | None = None
        if col_place < len(row):
            try:
                place_val = int(row[col_place].strip())
            except ValueError:
                place_val = placement

        notes = f"raw_team_name={raw_team!r}" if team_abbr == UNRESOLVED_TEAM else ""

        race.results.append(RaceResult(
            team=team_abbr,
            finish_time_seconds=finish_time,
            placement=place_val or placement,
            margin_to_winner_seconds=margin,
            verified=False,
            dnf=_is_dnf(raw_time),
            dns=_is_dns(raw_time),
            notes=notes,
        ))

    return race if race.results else None


def scrape_season(
    year: int,
    resolver: TeamResolver,
) -> StagedBundle:
    """
    Scrape EARC results for a given season year.
    Attempts to find result links from the EARC main results page.
    """
    now = datetime.now(timezone.utc).isoformat()
    bundle = StagedBundle(source="earc", season=year, scraped_at=now)

    index_url = f"{EARC_BASE}/"
    soup = _get(index_url)
    if soup is None:
        bundle.warnings.append(StagedWarning(
            type="fetch_error",
            raw_value=index_url,
            notes="Could not load EARC homepage",
        ))
        return bundle

    # Look for links that contain the year or "results"
    result_links: list[str] = []
    for a in soup.find_all("a", href=True):
        href: str = a["href"]
        text = a.get_text(strip=True).lower()
        if str(year) in href or str(year) in text or "result" in text or "result" in href.lower():
            full = href if href.startswith("http") else EARC_BASE + "/" + href.lstrip("/")
            if full not in result_links:
                result_links.append(full)

    if not result_links:
        bundle.warnings.append(StagedWarning(
            type="no_links_found",
            raw_value=index_url,
            notes=f"No result links found for year {year} on EARC homepage",
        ))
        return bundle

    logger.info("EARC: found %d potential result links for %d", len(result_links), year)

    for url in result_links[:20]:  # cap to avoid runaway scraping
        page_soup = _get(url)
        if page_soup is None:
            continue

        page_title = page_soup.find("title")
        regatta_name = page_title.get_text(strip=True) if page_title else url
        regatta_name = re.sub(r"\s*[-|]\s*EARC.*", "", regatta_name, flags=re.I).strip()

        date_str = _extract_date(page_soup) or f"{year}-01-01"
        course = _extract_course(page_soup) or ""

        regatta = Regatta(
            name=regatta_name,
            date=date_str,
            course=course,
            season=year,
            source_url=url,
            source_label="earc",
            staged=True,
        )

        page_warnings: list[StagedWarning] = []

        # Find tables
        for header in page_soup.find_all(["h2", "h3", "h4", "strong"]):
            header_text = header.get_text(strip=True)
            nxt = header.find_next_sibling()
            while nxt and nxt.name not in ("table", "h2", "h3", "h4"):
                nxt = nxt.find_next_sibling()
            if nxt and nxt.name == "table":
                race = _parse_earc_table(nxt, header_text, regatta.id, resolver, page_warnings)
                if race:
                    bundle.races.append(race)

        bundle.regattas.append(regatta)
        bundle.warnings.extend(page_warnings)
        time.sleep(0.75)

    return bundle
