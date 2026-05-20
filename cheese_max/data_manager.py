"""
DataManager — the single gatekeeper for all reads and writes.

Nothing outside this module should touch the data/ directory directly.
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterator

from cheese_max.models import (
    Athlete,
    Boat,
    Race,
    Regatta,
    StagedBundle,
    Team,
)

logger = logging.getLogger(__name__)

_DATA_ROOT_DEFAULT = Path(__file__).parent.parent / "data"


class DataManager:
    def __init__(self, data_root: Path | None = None) -> None:
        self.root = data_root or _DATA_ROOT_DEFAULT
        self._ensure_dirs()

    # ------------------------------------------------------------------
    # Directory helpers
    # ------------------------------------------------------------------

    def _ensure_dirs(self) -> None:
        for sub in (
            "staged",
            "confirmed/regattas",
            "confirmed/races",
            "confirmed/athletes",
            "confirmed/boats",
            "confirmed/rankings",
        ):
            (self.root / sub).mkdir(parents=True, exist_ok=True)

    @property
    def staged_dir(self) -> Path:
        return self.root / "staged"

    @property
    def regattas_dir(self) -> Path:
        return self.root / "confirmed" / "regattas"

    @property
    def races_dir(self) -> Path:
        return self.root / "confirmed" / "races"

    @property
    def rankings_dir(self) -> Path:
        return self.root / "confirmed" / "rankings"

    # ------------------------------------------------------------------
    # Teams (read-only from teams.json)
    # ------------------------------------------------------------------

    def get_teams(self) -> dict[str, Team]:
        """Return dict keyed by abbreviation."""
        path = self.root / "teams.json"
        if not path.exists():
            return {}
        raw = json.loads(path.read_text())
        return {t["abbreviation"]: Team.from_dict(t) for t in raw.get("teams", [])}

    def get_team_by_id(self, team_id: str) -> Team | None:
        for team in self.get_teams().values():
            if team.id == team_id:
                return team
        return None

    # ------------------------------------------------------------------
    # Staging writes (scrapers call these)
    # ------------------------------------------------------------------

    def stage_bundle(self, bundle: StagedBundle) -> Path:
        """Write a staged bundle to data/staged/. Returns the file path."""
        ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        filename = f"{ts}_{bundle.source}_{bundle.season}_{bundle.id[:8]}.staged.json"
        path = self.staged_dir / filename
        path.write_text(json.dumps(bundle.to_dict(), indent=2))
        logger.info("Staged bundle written: %s", path)
        return path

    # ------------------------------------------------------------------
    # Staged reads
    # ------------------------------------------------------------------

    def get_staged_bundles(self) -> list[tuple[Path, StagedBundle]]:
        """Return list of (path, bundle) for all pending staged bundles."""
        results = []
        for p in sorted(self.staged_dir.glob("*.staged.json")):
            try:
                raw = json.loads(p.read_text())
                bundle = StagedBundle.from_dict(raw)
                if bundle.status == "pending":
                    results.append((p, bundle))
            except Exception as exc:
                logger.warning("Could not load staged bundle %s: %s", p, exc)
        return results

    def get_staged_bundle_by_id(self, bundle_id: str) -> tuple[Path, StagedBundle] | None:
        for p, b in self.get_staged_bundles():
            if b.id == bundle_id or b.id.startswith(bundle_id):
                return p, b
        return None

    # ------------------------------------------------------------------
    # Promotion: approve
    # ------------------------------------------------------------------

    def approve_staged_bundle(self, bundle: StagedBundle, bundle_path: Path) -> dict:
        """
        Promote all non-rejected races from the bundle to confirmed/.
        Returns a summary dict.
        """
        approved_regattas = 0
        approved_races = 0
        skipped_existing = 0
        now = datetime.now(timezone.utc).isoformat()

        # Build regatta lookup from bundle
        regatta_map = {r.id: r for r in bundle.regattas}

        for regatta in bundle.regattas:
            dest = self.regattas_dir / f"{regatta.id}.json"
            if dest.exists():
                skipped_existing += 1
                logger.debug("Regatta %s already exists, skipping", regatta.id)
            else:
                regatta.staged = False
                regatta.approved_at = now
                dest.write_text(json.dumps(regatta.to_dict(), indent=2))
                approved_regattas += 1

        for race in bundle.races:
            if race.rejected:
                continue
            dest = self.races_dir / f"{race.id}.json"
            if dest.exists():
                skipped_existing += 1
                logger.debug("Race %s already exists, skipping", race.id)
            else:
                race.staged = False
                for result in race.results:
                    result.verified = True
                dest.write_text(json.dumps(race.to_dict(), indent=2))
                approved_races += 1

        # Mark bundle as approved
        bundle.status = "approved"
        bundle_path.write_text(json.dumps(bundle.to_dict(), indent=2))

        return {
            "approved_regattas": approved_regattas,
            "approved_races": approved_races,
            "skipped_existing": skipped_existing,
        }

    # ------------------------------------------------------------------
    # Promotion: reject
    # ------------------------------------------------------------------

    def reject_staged_bundle(self, bundle: StagedBundle, bundle_path: Path) -> None:
        """Mark entire bundle as rejected (does not delete the file)."""
        bundle.status = "rejected"
        bundle_path.write_text(json.dumps(bundle.to_dict(), indent=2))

    def reject_race_in_bundle(
        self, bundle: StagedBundle, bundle_path: Path, race_id: str
    ) -> bool:
        """Mark a single race as rejected within a bundle. Returns True if found."""
        for race in bundle.races:
            if race.id == race_id:
                race.rejected = True
                bundle_path.write_text(json.dumps(bundle.to_dict(), indent=2))
                return True
        return False

    def update_bundle(self, bundle: StagedBundle, bundle_path: Path) -> None:
        """Persist any in-memory changes to the bundle file."""
        bundle_path.write_text(json.dumps(bundle.to_dict(), indent=2))

    # ------------------------------------------------------------------
    # Confirmed reads
    # ------------------------------------------------------------------

    def get_confirmed_regattas(self, season: int | None = None) -> list[Regatta]:
        regattas = []
        for p in self.regattas_dir.glob("*.json"):
            try:
                raw = json.loads(p.read_text())
                r = Regatta.from_dict(raw)
                if season is None or r.season == season:
                    regattas.append(r)
            except Exception as exc:
                logger.warning("Could not load regatta %s: %s", p, exc)
        return regattas

    def get_confirmed_races(
        self,
        season: int | None = None,
        boat_class: str | None = None,
    ) -> list[Race]:
        """Load confirmed races, optionally filtered by season and/or boat class."""
        regatta_ids: set[str] | None = None
        if season is not None:
            regatta_ids = {r.id for r in self.get_confirmed_regattas(season=season)}

        races = []
        for p in self.races_dir.glob("*.json"):
            try:
                raw = json.loads(p.read_text())
                race = Race.from_dict(raw)
                if regatta_ids is not None and race.regatta_id not in regatta_ids:
                    continue
                if boat_class is not None and race.boat_class != boat_class:
                    continue
                races.append(race)
            except Exception as exc:
                logger.warning("Could not load race %s: %s", p, exc)
        return races

    def get_regatta_for_race(self, race: Race) -> Regatta | None:
        path = self.regattas_dir / f"{race.regatta_id}.json"
        if not path.exists():
            return None
        try:
            return Regatta.from_dict(json.loads(path.read_text()))
        except Exception:
            return None

    # ------------------------------------------------------------------
    # Export
    # ------------------------------------------------------------------

    def export_races_csv(
        self,
        season: int,
        boat_class: str,
        output_path: Path | None = None,
    ) -> Path:
        import csv

        races = self.get_confirmed_races(season=season, boat_class=boat_class)
        regattas = {r.id: r for r in self.get_confirmed_regattas(season=season)}

        if output_path is None:
            ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
            output_path = self.root / f"export_{season}_{boat_class}_{ts}.csv"

        rows = []
        for race in races:
            reg = regattas.get(race.regatta_id)
            reg_name = reg.name if reg else ""
            reg_date = reg.date if reg else ""
            for result in race.results:
                rows.append({
                    "season": season,
                    "regatta": reg_name,
                    "date": reg_date,
                    "boat_class": race.boat_class,
                    "event_type": race.event_type,
                    "race_name": race.race_name or "",
                    "team": result.team,
                    "placement": result.placement,
                    "finish_time_seconds": result.finish_time_seconds,
                    "margin_to_winner_seconds": result.margin_to_winner_seconds,
                    "lane": result.lane,
                    "dnf": result.dnf,
                    "dns": result.dns,
                    "verified": result.verified,
                })

        if not rows:
            logger.warning("No data found for season=%s boat_class=%s", season, boat_class)

        fieldnames = [
            "season", "regatta", "date", "boat_class", "event_type", "race_name",
            "team", "placement", "finish_time_seconds", "margin_to_winner_seconds",
            "lane", "dnf", "dns", "verified",
        ]
        with output_path.open("w", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(rows)

        return output_path

    def save_ranking_output(self, season: int, boat_class: str, data: dict) -> Path:
        path = self.rankings_dir / f"{season}_{boat_class}.json"
        path.write_text(json.dumps(data, indent=2))
        return path
