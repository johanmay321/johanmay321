"""
Team name resolver.

Converts raw team name strings (as they appear in scraped results) to
canonical abbreviations from data/teams.json.  Uses a simple
case-insensitive substring/alias match with a fuzzy fallback.
"""
from __future__ import annotations

import difflib
import logging
import re

from cheese_max.models import Team

logger = logging.getLogger(__name__)


class TeamResolver:
    def __init__(self, teams: dict[str, Team]) -> None:
        # Build a flat lookup: (lower_alias, abbreviation) for all aliases + name
        self._lookup: list[tuple[str, str]] = []
        for abbr, team in teams.items():
            self._lookup.append((team.name.lower(), abbr))
            self._lookup.append((abbr.lower(), abbr))
            for alias in team.aliases:
                self._lookup.append((alias.lower(), abbr))
        self._abbrs = list(teams.keys())
        self._all_keys = [k for k, _ in self._lookup]

    def resolve(self, raw: str, threshold: float = 0.72) -> str | None:
        """
        Return the canonical abbreviation for `raw`, or None if unresolvable.

        First tries exact substring matches, then falls back to difflib
        sequence-match ratio.
        """
        if not raw:
            return None
        normalized = raw.strip().lower()
        normalized = re.sub(r"\s+", " ", normalized)

        # 1. Exact match
        for key, abbr in self._lookup:
            if key == normalized:
                return abbr

        # 2. Substring match (raw contains a known alias, or alias contains raw)
        for key, abbr in self._lookup:
            if key in normalized or normalized in key:
                return abbr

        # 3. Fuzzy match
        matches = difflib.get_close_matches(normalized, self._all_keys, n=1, cutoff=threshold)
        if matches:
            matched_key = matches[0]
            for key, abbr in self._lookup:
                if key == matched_key:
                    return abbr

        return None

    def suggest(self, raw: str) -> str | None:
        """Return the best-guess abbreviation even below threshold, for the review UI."""
        if not raw:
            return None
        normalized = raw.strip().lower()
        matches = difflib.get_close_matches(normalized, self._all_keys, n=1, cutoff=0.4)
        if matches:
            matched_key = matches[0]
            for key, abbr in self._lookup:
                if key == matched_key:
                    return abbr
        return None
