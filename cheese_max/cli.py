"""
Cheese Max 2K26 — Command-line interface.

Usage
-----
  python cheese_max.py scrape  --source {row2k,earc,pdf} --year INT [--url URL] [--category lightweight]
  python cheese_max.py import  --file PATH
  python cheese_max.py review  [--bundle ID]
  python cheese_max.py rank    --class {V1,V2,V3,LW1,LW2,...} --season INT [options]
  python cheese_max.py export  --format {csv,json} --season INT --class CLASS [--output PATH]
  python cheese_max.py teams   [--list]
"""
from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

from rich.console import Console
from rich.prompt import Prompt, Confirm
from rich.table import Table
from rich import print as rprint

from cheese_max.data_manager import DataManager
from cheese_max.models import UNRESOLVED_TEAM, Race, RaceResult, StagedBundle
from cheese_max.ranking.conditions import compute_race_weights
from cheese_max.ranking.massey import RankingConfig, compute_rankings
from cheese_max.scrapers.team_resolver import TeamResolver

console = Console()
logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _fmt_time(seconds: float | None) -> str:
    if seconds is None:
        return "—"
    m = int(seconds // 60)
    s = seconds - m * 60
    return f"{m}:{s:05.2f}"


def _fmt_margin(seconds: float | None) -> str:
    if seconds is None or seconds == 0.0:
        return "—"
    sign = "+" if seconds > 0 else ""
    return f"{sign}{seconds:.2f}s"


def _make_resolver(dm: DataManager) -> TeamResolver:
    return TeamResolver(dm.get_teams())


# ---------------------------------------------------------------------------
# scrape
# ---------------------------------------------------------------------------

def cmd_scrape(args: argparse.Namespace, dm: DataManager) -> None:
    resolver = _make_resolver(dm)

    if args.source == "row2k":
        from cheese_max.scrapers import row2k
        if args.url:
            console.print(f"[cyan]Scraping row2k URL:[/cyan] {args.url}")
            bundle = row2k.scrape_regatta_url(
                args.url, args.year, resolver, category_filter=args.category
            )
        else:
            console.print(f"[cyan]Scraping row2k for season {args.year}[/cyan]"
                          + (f" (filter: {args.category})" if args.category else ""))
            bundle = row2k.scrape_season(args.year, resolver, category_filter=args.category)

    elif args.source == "earc":
        from cheese_max.scrapers import earc
        console.print(f"[cyan]Scraping EARC for season {args.year}[/cyan]")
        bundle = earc.scrape_season(args.year, resolver)

    elif args.source == "team":
        console.print("[yellow]Team site scraping not yet implemented.[/yellow]")
        console.print("Use --source row2k or --source pdf for now.")
        return

    else:
        console.print(f"[red]Unknown source: {args.source}[/red]")
        return

    _summarise_and_stage(bundle, dm)


# ---------------------------------------------------------------------------
# import (PDF)
# ---------------------------------------------------------------------------

def cmd_import(args: argparse.Namespace, dm: DataManager) -> None:
    from cheese_max.scrapers.pdf_parser import parse_pdf

    path = Path(args.file)
    if not path.exists():
        console.print(f"[red]File not found: {path}[/red]")
        sys.exit(1)

    resolver = _make_resolver(dm)
    console.print(f"[cyan]Parsing PDF:[/cyan] {path}")
    bundle = parse_pdf(path, resolver, season=args.year)
    _summarise_and_stage(bundle, dm)


def _summarise_and_stage(bundle: StagedBundle, dm: DataManager) -> None:
    n_reg = len(bundle.regattas)
    n_race = len(bundle.races)
    n_res = sum(len(r.results) for r in bundle.races)
    n_warn = len(bundle.warnings)

    console.print(f"\n[bold]Bundle summary:[/bold]")
    console.print(f"  Regattas : {n_reg}")
    console.print(f"  Races    : {n_race}")
    console.print(f"  Results  : {n_res}")
    if n_warn:
        console.print(f"  [yellow]Warnings : {n_warn}[/yellow]")
    for w in bundle.warnings[:10]:
        console.print(f"    [yellow]• [{w.type}] {w.raw_value}"
                      + (f" → suggest: {w.suggestion}" if w.suggestion else "") + "[/yellow]")
    if n_warn > 10:
        console.print(f"    [yellow]... and {n_warn - 10} more[/yellow]")

    staged_path = dm.stage_bundle(bundle)
    console.print(f"\n[green]Staged:[/green] {staged_path.name}")
    console.print("Run [bold]python cheese_max.py review[/bold] to inspect and approve.")


# ---------------------------------------------------------------------------
# review
# ---------------------------------------------------------------------------

def cmd_review(args: argparse.Namespace, dm: DataManager) -> None:
    bundles = dm.get_staged_bundles()

    if not bundles:
        console.print("[green]No pending staged bundles.[/green]")
        return

    # Bundle selection
    if args.bundle:
        result = dm.get_staged_bundle_by_id(args.bundle)
        if result is None:
            console.print(f"[red]Bundle not found: {args.bundle}[/red]")
            return
        selected_path, selected_bundle = result
    elif len(bundles) == 1:
        selected_path, selected_bundle = bundles[0]
    else:
        console.print("\n[bold]=== STAGED BUNDLES ===[/bold]")
        for i, (p, b) in enumerate(bundles, start=1):
            n_warn = len(b.warnings)
            n_races = len(b.races)
            n_results = sum(len(r.results) for r in b.races)
            warn_txt = f" [yellow]{n_warn} warnings[/yellow]" if n_warn else ""
            console.print(
                f"  [{i}] {p.name}  "
                f"({len(b.regattas)} regattas, {n_races} races, {n_results} results){warn_txt}"
            )
        choice = Prompt.ask("\nSelect bundle", choices=[str(i) for i in range(1, len(bundles) + 1)] + ["q"])
        if choice == "q":
            return
        selected_path, selected_bundle = bundles[int(choice) - 1]

    _review_bundle(selected_bundle, selected_path, dm, boat_class_filter=getattr(args, "boat_class", None))


def _review_bundle(
    bundle: StagedBundle,
    bundle_path: Path,
    dm: DataManager,
    boat_class_filter: str | None = None,
) -> None:
    console.rule(f"[bold]Bundle: {bundle_path.name}")
    console.print(f"Source: [cyan]{bundle.source}[/cyan]  |  Season: [cyan]{bundle.season}[/cyan]  |  Scraped: {bundle.scraped_at}")

    if bundle.warnings:
        console.print(f"[yellow]{len(bundle.warnings)} warnings[/yellow] (unresolved teams, parse errors, etc.)")

    races = [r for r in bundle.races if not r.rejected]
    if boat_class_filter:
        races = [r for r in races if r.boat_class == boat_class_filter]

    if not races:
        console.print("[yellow]No races to review.[/yellow]")
        return

    regatta_map = {reg.id: reg for reg in bundle.regattas}
    approved_ids: set[str] = set()

    for idx, race in enumerate(races, start=1):
        regatta = regatta_map.get(race.regatta_id)
        reg_name = regatta.name if regatta else "Unknown Regatta"

        console.rule(f"Race {idx}/{len(races)}")
        console.print(f"  [bold]{reg_name}[/bold]  |  {race.boat_class} {race.event_type.upper()}"
                      + (f"  |  {race.race_name}" if race.race_name else ""))
        if regatta:
            console.print(f"  Date: {regatta.date}  |  Course: {regatta.course or '—'}")
            cond = regatta.conditions
            cond_parts = []
            if cond.water_state:
                cond_parts.append(cond.water_state)
            if cond.wind_direction or cond.wind_speed_kph:
                cond_parts.append(f"{cond.wind_direction or '?'} {cond.wind_speed_kph or '?'} kph")
            if cond_parts:
                console.print(f"  Conditions: {', '.join(cond_parts)}")

        _print_race_table(race)

        while True:
            action = Prompt.ask(
                "\n[bold][a][/bold]pprove  [bold][e][/bold]dit team  [bold][s][/bold]kip  "
                "[bold][r][/bold]eject  [bold][q][/bold]uit",
                choices=["a", "e", "s", "r", "q"],
            ).lower()

            if action == "a":
                approved_ids.add(race.id)
                break
            elif action == "e":
                _edit_result_in_race(race, bundle, bundle_path, dm)
                _print_race_table(race)  # reprint after edit
            elif action == "s":
                console.print("[dim]Skipped (stays staged for next session).[/dim]")
                break
            elif action == "r":
                dm.reject_race_in_bundle(bundle, bundle_path, race.id)
                console.print("[red]Race rejected.[/red]")
                break
            elif action == "q":
                console.print("[dim]Exiting review. Progress saved.[/dim]")
                return

    if not approved_ids:
        console.print("\n[yellow]No races approved.[/yellow]")
        return

    console.print(f"\n[bold]{len(approved_ids)} races approved.[/bold]")
    final = Prompt.ask(
        "[bold][A][/bold]pprove all approved races  [bold][R][/bold]eject bundle  [bold][q][/bold]uit",
        choices=["A", "R", "q"],
    )

    if final == "A":
        # Mark only approved races as non-rejected; reject everything else
        for race in bundle.races:
            if race.id not in approved_ids and race.id not in {r.id for r in bundle.races if r.rejected}:
                race.rejected = True
        summary = dm.approve_staged_bundle(bundle, bundle_path)
        console.print(f"\n[green]Done![/green] "
                      f"{summary['approved_regattas']} regattas, "
                      f"{summary['approved_races']} races promoted to confirmed.")
        if summary["skipped_existing"] > 0:
            console.print(f"[dim]{summary['skipped_existing']} items skipped (already confirmed).[/dim]")
    elif final == "R":
        dm.reject_staged_bundle(bundle, bundle_path)
        console.print("[red]Bundle rejected.[/red]")
    else:
        console.print("[dim]Exiting. No changes committed.[/dim]")


def _print_race_table(race: Race) -> None:
    t = Table(show_header=True, header_style="bold")
    t.add_column("Place", width=5)
    t.add_column("Lane", width=5)
    t.add_column("Team", min_width=12)
    t.add_column("Time", width=9)
    t.add_column("Margin", width=9)
    t.add_column("Notes", min_width=8)

    for result in sorted(race.results, key=lambda r: (r.placement or 99)):
        style = "red" if result.team == UNRESOLVED_TEAM else ""
        team_display = result.team if result.team != UNRESOLVED_TEAM else f"[red]??? ({result.notes})[/red]"
        t.add_row(
            str(result.placement or ""),
            str(result.lane or ""),
            team_display,
            _fmt_time(result.finish_time_seconds),
            _fmt_margin(result.margin_to_winner_seconds),
            ("DNF" if result.dnf else "DNS" if result.dns else ""),
            style=style,
        )
    console.print(t)


def _edit_result_in_race(
    race: Race,
    bundle: StagedBundle,
    bundle_path: Path,
    dm: DataManager,
) -> None:
    console.print("\n[bold]Edit a result:[/bold]")
    for i, result in enumerate(race.results, start=1):
        console.print(f"  [{i}] {result.team} — {_fmt_time(result.finish_time_seconds)}")

    idx_str = Prompt.ask("Result number to edit (or [dim]Enter[/dim] to cancel)", default="")
    if not idx_str:
        return
    try:
        idx = int(idx_str) - 1
        result = race.results[idx]
    except (ValueError, IndexError):
        console.print("[red]Invalid selection.[/red]")
        return

    field = Prompt.ask("Edit [bold]team[/bold] or [bold]time[/bold]?", choices=["team", "time", "cancel"])
    if field == "cancel":
        return
    elif field == "team":
        new_team = Prompt.ask(f"New team abbreviation for {result.team!r}").strip().upper()
        result.team = new_team
        result.notes = result.notes.replace(f"raw_team_name={result.team!r}", "").strip("; ")
        console.print(f"[green]Team updated to {new_team}.[/green]")
    elif field == "time":
        new_time_str = Prompt.ask(f"New time for {result.team} (format m:ss.t, e.g. 6:01.4)").strip()
        from cheese_max.scrapers.row2k import _parse_time
        new_time = _parse_time(new_time_str)
        if new_time is None:
            console.print("[red]Could not parse time.[/red]")
            return
        result.finish_time_seconds = new_time
        # Recalculate margins
        valid_times = [r.finish_time_seconds for r in race.results if r.finish_time_seconds is not None]
        if valid_times:
            winner = min(valid_times)
            for r in race.results:
                if r.finish_time_seconds is not None:
                    r.margin_to_winner_seconds = r.finish_time_seconds - winner
        console.print(f"[green]Time updated to {_fmt_time(new_time)}.[/green]")

    dm.update_bundle(bundle, bundle_path)


# ---------------------------------------------------------------------------
# rank
# ---------------------------------------------------------------------------

def cmd_rank(args: argparse.Namespace, dm: DataManager) -> None:
    boat_class = args.boat_class
    season = args.season

    races = dm.get_confirmed_races(season=season, boat_class=boat_class)
    if not races:
        console.print(f"[yellow]No confirmed races found for season={season}, class={boat_class}.[/yellow]")
        console.print("Run [bold]scrape[/bold] + [bold]review[/bold] first to confirm data.")
        return

    regattas_list = dm.get_confirmed_regattas(season=season)
    regattas_map = {r.id: r for r in regattas_list}

    config = RankingConfig(
        normalize_margins=not args.no_normalize,
        discount_large_gaps=args.discount_gaps,
        gap_threshold_pct=args.gap_threshold,
        gap_threshold_seconds=args.gap_threshold,
        gap_discount_factor=args.gap_discount,
        discount_bad_conditions=args.discount_conditions,
        min_races_threshold=args.min_races,
    )

    # Compute weights
    weights = compute_race_weights(
        races=races,
        regattas=regattas_map,
        discount_conditions=args.discount_conditions,
        headwind_threshold_kph=args.headwind_threshold,
    )

    result = compute_rankings(
        races=races,
        weights=weights,
        config=config,
        season=season,
        boat_class=boat_class,
    )

    if not result.rankings:
        console.print("[yellow]No rankings computed — check that confirmed data has sufficient races.[/yellow]")
        return

    # Display
    console.rule(f"[bold]Rankings: {season} {boat_class}")
    norm_label = "% back (normalized)" if config.normalize_margins else "seconds (raw)"
    console.print(f"Metric: [cyan]{norm_label}[/cyan]  |  "
                  f"Races in dataset: {result.num_races}  |  Teams: {result.num_teams}")
    if config.normalize_margins:
        console.print(f"Reference display: {config.reference_time_seconds}s "
                      f"({_fmt_time(config.reference_time_seconds)} pace)\n")

    t = Table(show_header=True, header_style="bold")
    t.add_column("#", width=4)
    t.add_column("Team", min_width=12)
    t.add_column("Rating (%)", width=10)
    t.add_column(f"At {_fmt_time(config.reference_time_seconds)}", width=10)
    t.add_column("Races", width=6)
    t.add_column("", width=4)  # low-sample flag

    for entry in result.rankings:
        flag = "[yellow]*[/yellow]" if entry.low_sample else ""
        t.add_row(
            str(entry.rank),
            entry.team,
            f"{entry.rating:+.3f}",
            f"{entry.rating_at_ref:+.2f}s",
            str(entry.races),
            flag,
        )

    console.print(t)
    if any(e.low_sample for e in result.rankings):
        console.print("[yellow]* Low sample — fewer than "
                      f"{config.min_races_threshold} races, rating unreliable.[/yellow]")

    # Persist
    output_path = dm.save_ranking_output(season, boat_class, result.to_dict())
    console.print(f"\n[dim]Saved: {output_path}[/dim]")


# ---------------------------------------------------------------------------
# export
# ---------------------------------------------------------------------------

def cmd_export(args: argparse.Namespace, dm: DataManager) -> None:
    output = Path(args.output) if args.output else None

    if args.format == "csv":
        path = dm.export_races_csv(
            season=args.season,
            boat_class=args.boat_class,
            output_path=output,
        )
        console.print(f"[green]Exported CSV:[/green] {path}")
    elif args.format == "json":
        import json
        races = dm.get_confirmed_races(season=args.season, boat_class=args.boat_class)
        regattas = {r.id: r for r in dm.get_confirmed_regattas(season=args.season)}
        data = {
            "season": args.season,
            "boat_class": args.boat_class,
            "regattas": {rid: reg.to_dict() for rid, reg in regattas.items()},
            "races": [race.to_dict() for race in races],
        }
        out = output or Path(f"export_{args.season}_{args.boat_class}.json")
        out.write_text(json.dumps(data, indent=2))
        console.print(f"[green]Exported JSON:[/green] {out}")
    else:
        console.print(f"[red]Unknown format: {args.format}[/red]")


# ---------------------------------------------------------------------------
# teams
# ---------------------------------------------------------------------------

def cmd_teams(args: argparse.Namespace, dm: DataManager) -> None:
    teams = dm.get_teams()
    t = Table(show_header=True, header_style="bold", title="Registered Teams")
    t.add_column("Abbr", width=10)
    t.add_column("Name", min_width=30)
    t.add_column("Conference", width=8)
    t.add_column("Aliases", min_width=20)
    for abbr, team in sorted(teams.items()):
        t.add_row(abbr, team.name, team.conference, ", ".join(team.aliases[:3]))
    console.print(t)


# ---------------------------------------------------------------------------
# Argument parser
# ---------------------------------------------------------------------------

def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="cheese_max",
        description="Cheese Max 2K26 — Collegiate rowing race analysis & rankings",
    )
    parser.add_argument("--data-root", type=Path, default=None, help="Override data directory")
    parser.add_argument("--verbose", "-v", action="store_true", help="Enable debug logging")

    sub = parser.add_subparsers(dest="command", required=True)

    # --- scrape ---
    p_scrape = sub.add_parser("scrape", help="Scrape race results from an online source")
    p_scrape.add_argument("--source", choices=["row2k", "earc", "team"], default="row2k")
    p_scrape.add_argument("--year", type=int, required=True, help="Season year (e.g. 2026)")
    p_scrape.add_argument("--url", default=None, help="Scrape a specific URL (row2k regatta page)")
    p_scrape.add_argument("--category", default=None, help="Filter to 'lightweight' or leave blank for all")
    p_scrape.add_argument("--team", default=None, help="For --source team: team abbreviation (e.g. HVD-LW)")

    # --- import ---
    p_import = sub.add_parser("import", help="Parse a PDF result sheet and stage it")
    p_import.add_argument("--file", required=True, help="Path to the PDF file")
    p_import.add_argument("--year", type=int, default=None, help="Season year (auto-detected if omitted)")

    # --- review ---
    p_review = sub.add_parser("review", help="Interactively review and approve staged data")
    p_review.add_argument("--bundle", default=None, help="Bundle ID (or prefix) to review directly")
    p_review.add_argument("--class", dest="boat_class", default=None, help="Filter to a specific boat class")

    # --- rank ---
    p_rank = sub.add_parser("rank", help="Compute Massey least-squares rankings")
    p_rank.add_argument("--class", dest="boat_class", required=True, help="Boat class (V1, V2, LW1, ...)")
    p_rank.add_argument("--season", type=int, required=True)
    p_rank.add_argument("--no-normalize", action="store_true",
                        help="Use raw seconds instead of percentage-back margins")
    p_rank.add_argument("--discount-gaps", action="store_true", help="Cap large margin blowouts")
    p_rank.add_argument("--gap-threshold", type=float, default=5.0,
                        help="Gap threshold in %% (normalize) or seconds (raw) [default: 5.0%%]")
    p_rank.add_argument("--gap-discount", type=float, default=0.2,
                        help="Fraction of excess gap to retain [default: 0.2]")
    p_rank.add_argument("--discount-conditions", action="store_true",
                        help="Down-weight races with bad conditions")
    p_rank.add_argument("--headwind-threshold", type=float, default=20.0,
                        help="Wind speed kph above which headwind discount applies [default: 20]")
    p_rank.add_argument("--min-races", type=int, default=3,
                        help="Flag teams with fewer than N races as low-sample [default: 3]")

    # --- export ---
    p_export = sub.add_parser("export", help="Export confirmed data to CSV or JSON")
    p_export.add_argument("--format", choices=["csv", "json"], default="csv")
    p_export.add_argument("--season", type=int, required=True)
    p_export.add_argument("--class", dest="boat_class", required=True)
    p_export.add_argument("--output", default=None, help="Output file path")

    # --- teams ---
    sub.add_parser("teams", help="List all registered teams")

    return parser


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main() -> None:
    parser = _build_parser()
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.WARNING,
        format="%(levelname)s %(name)s: %(message)s",
    )

    dm = DataManager(data_root=args.data_root)

    dispatch = {
        "scrape": cmd_scrape,
        "import": cmd_import,
        "review": cmd_review,
        "rank": cmd_rank,
        "export": cmd_export,
        "teams": cmd_teams,
    }

    fn = dispatch.get(args.command)
    if fn is None:
        parser.print_help()
        sys.exit(1)

    fn(args, dm)


if __name__ == "__main__":
    main()
