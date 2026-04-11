"""
Massey least-squares ranking for collegiate rowing.

Core idea
---------
For each race, generate all pairwise comparisons between crews.  Each pair
produces one equation:  rating_i - rating_j ≈ margin(i, j).

Margins are expressed as **percentage-back from the winner** by default so
that a 3-second gap in a 5:58 race and a 3-second gap in a 6:25 race are
treated proportionally rather than as identical absolute differences.  This
is the critical normalization step — absolute times vary hugely across races
due to conditions, but relative gaps are comparable.

The system  X r ≈ y  is solved in the weighted least-squares sense.
A sum-to-zero constraint is enforced so ratings are expressed relative to
the average team in the dataset (higher = faster = better).

Ratings are output in percentage points (e.g. 0.85 means "0.85% faster than
average").  For display purposes a reference time (default 5:35 = 335 s) can
convert ratings back to "seconds at reference pace".
"""
from __future__ import annotations

import logging
import math
from dataclasses import dataclass, field

import numpy as np
from scipy.linalg import lstsq

from cheese_max.models import Race, UNRESOLVED_TEAM

logger = logging.getLogger(__name__)

REFERENCE_TIME_SECONDS = 335.0  # 5:35 — cosmetic display conversion only


# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

@dataclass
class RankingConfig:
    normalize_margins: bool = True
    """Convert raw-second margins to percentage-back before solving."""

    discount_large_gaps: bool = False
    """Cap runaway blowout margins to limit their influence."""

    gap_threshold_pct: float = 5.0
    """Pct-back threshold above which discounting kicks in (normalize=True)."""

    gap_threshold_seconds: float = 30.0
    """Second threshold above which discounting kicks in (normalize=False)."""

    gap_discount_factor: float = 0.2
    """Fraction of the excess gap that is retained after the threshold."""

    discount_bad_conditions: bool = False
    """Whether bad-condition weights were applied (stored for output metadata)."""

    min_races_threshold: int = 3
    """Teams with fewer races are flagged low_sample in the output."""

    reference_time_seconds: float = REFERENCE_TIME_SECONDS
    """Used only for cosmetic seconds-at-reference-pace display."""


# ---------------------------------------------------------------------------
# Output
# ---------------------------------------------------------------------------

@dataclass
class TeamRanking:
    rank: int
    team: str
    rating: float          # in pct or seconds depending on config
    rating_at_ref: float   # rating expressed as seconds at reference_time
    races: int
    low_sample: bool
    note: str | None = None

    def to_dict(self) -> dict:
        return {
            "rank": self.rank,
            "team": self.team,
            "rating": round(self.rating, 4),
            "rating_at_ref_seconds": round(self.rating_at_ref, 2),
            "races": self.races,
            "low_sample": self.low_sample,
            "note": self.note,
        }


@dataclass
class RankingResult:
    rankings: list[TeamRanking]
    config: RankingConfig
    season: int
    boat_class: str
    num_races: int
    num_teams: int

    def to_dict(self) -> dict:
        return {
            "version": "1.0",
            "season": self.season,
            "boat_class": self.boat_class,
            "num_races": self.num_races,
            "num_teams": self.num_teams,
            "config": {
                "normalize_margins": self.config.normalize_margins,
                "discount_large_gaps": self.config.discount_large_gaps,
                "gap_threshold_pct": self.config.gap_threshold_pct,
                "gap_threshold_seconds": self.config.gap_threshold_seconds,
                "gap_discount_factor": self.config.gap_discount_factor,
                "discount_bad_conditions": self.config.discount_bad_conditions,
                "min_races_threshold": self.config.min_races_threshold,
                "reference_time_seconds": self.config.reference_time_seconds,
            },
            "rankings": [r.to_dict() for r in self.rankings],
        }


# ---------------------------------------------------------------------------
# Solver
# ---------------------------------------------------------------------------

def _apply_gap_discount(margin: float, threshold: float, factor: float) -> float:
    """Cap a margin that exceeds threshold, retaining only `factor` of the excess."""
    if abs(margin) <= threshold:
        return margin
    excess = abs(margin) - threshold
    discounted = threshold + excess * factor
    return math.copysign(discounted, margin)


def compute_rankings(
    races: list[Race],
    weights: dict[str, float],
    config: RankingConfig,
    season: int,
    boat_class: str,
) -> RankingResult:
    """
    Build and solve the Massey system for the given set of races.

    Parameters
    ----------
    races    : confirmed Race objects for one season + boat_class
    weights  : dict[race_id, float] from conditions.compute_race_weights()
    config   : RankingConfig controlling normalization and discounting
    season   : for metadata output
    boat_class : for metadata output
    """
    # 1. Collect all teams that appear in at least one result
    teams_set: set[str] = set()
    for race in races:
        for result in race.results:
            if (
                result.team != UNRESOLVED_TEAM
                and not result.dnf
                and not result.dns
                and result.finish_time_seconds is not None
            ):
                teams_set.add(result.team)

    if len(teams_set) < 2:
        logger.warning("Not enough teams to compute rankings (%d found)", len(teams_set))
        return RankingResult(
            rankings=[], config=config, season=season,
            boat_class=boat_class, num_races=0, num_teams=len(teams_set),
        )

    teams = sorted(teams_set)
    n = len(teams)
    team_idx = {t: i for i, t in enumerate(teams)}

    # 2. Count race appearances per team
    race_counts: dict[str, int] = {t: 0 for t in teams}

    # 3. Build design matrix rows
    rows_X: list[np.ndarray] = []
    rows_y: list[float] = []

    threshold = (
        config.gap_threshold_pct / 100.0
        if config.normalize_margins
        else config.gap_threshold_seconds
    )

    for race in races:
        valid = [
            r for r in race.results
            if (
                r.team != UNRESOLVED_TEAM
                and not r.dnf
                and not r.dns
                and r.finish_time_seconds is not None
                and r.team in team_idx
            )
        ]
        if len(valid) < 2:
            continue

        w = weights.get(race.id, 1.0)
        sqrt_w = math.sqrt(w)

        for team_abbr in {r.team for r in valid}:
            race_counts[team_abbr] += 1

        # All pairs within this race
        for i in range(len(valid)):
            for j in range(i + 1, len(valid)):
                ri = valid[i]
                rj = valid[j]
                t_i = ri.finish_time_seconds
                t_j = rj.finish_time_seconds

                # Ensure i is the faster (lower time) crew
                if t_i > t_j:
                    ri, rj = rj, ri
                    t_i, t_j = t_j, t_i

                # Compute margin
                if config.normalize_margins:
                    # percentage-back: positive means rj is slower than ri
                    margin = (t_j - t_i) / t_i
                else:
                    margin = t_j - t_i  # seconds

                # Large-gap discounting
                if config.discount_large_gaps:
                    margin = _apply_gap_discount(margin, threshold, config.gap_discount_factor)

                row = np.zeros(n)
                row[team_idx[ri.team]] = 1.0
                row[team_idx[rj.team]] = -1.0

                rows_X.append(row * sqrt_w)
                rows_y.append(margin * sqrt_w)

    if not rows_X:
        logger.warning("No valid pairwise comparisons found for %s %s", season, boat_class)
        return RankingResult(
            rankings=[], config=config, season=season,
            boat_class=boat_class, num_races=len(races), num_teams=n,
        )

    X = np.array(rows_X)
    y = np.array(rows_y)

    # 4. Normal equations with sum-to-zero constraint
    M = X.T @ X
    rhs = X.T @ y

    # Replace last row to enforce sum(r) = 0
    M[-1, :] = 1.0
    rhs[-1] = 0.0

    # 5. Solve
    ratings_vec, _, _, _ = lstsq(M, rhs)

    # 6. Build output
    rankings: list[TeamRanking] = []
    for i, team in enumerate(teams):
        rating = float(ratings_vec[i])

        if config.normalize_margins:
            # rating is in fraction form — express as percent for readability
            rating_pct = rating * 100.0
            rating_at_ref = rating * config.reference_time_seconds
        else:
            rating_pct = rating
            rating_at_ref = rating

        count = race_counts[team]
        low = count < config.min_races_threshold
        note = f"Fewer than {config.min_races_threshold} races — rating unreliable" if low else None

        rankings.append(TeamRanking(
            rank=0,  # assigned below after sort
            team=team,
            rating=rating_pct if config.normalize_margins else rating,
            rating_at_ref=rating_at_ref,
            races=count,
            low_sample=low,
            note=note,
        ))

    # Sort descending by rating (higher = faster = better)
    rankings.sort(key=lambda r: r.rating, reverse=True)
    for pos, entry in enumerate(rankings, start=1):
        entry.rank = pos

    return RankingResult(
        rankings=rankings,
        config=config,
        season=season,
        boat_class=boat_class,
        num_races=len(races),
        num_teams=n,
    )
