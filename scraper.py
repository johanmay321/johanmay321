"""
Glassdoor Vet Salary Scraper
Scrapes veterinarian salary data for Boston, MA and Raleigh, NC.
"""

import csv
import json
import random
import re
import time
from dataclasses import dataclass, fields
from datetime import datetime
from pathlib import Path

from bs4 import BeautifulSoup
from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeout


# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

LOCATIONS = {
    "Boston, MA": {
        "url": (
            "https://www.glassdoor.com/Salaries/"
            "boston-veterinarian-salary-SRCH_IL.0,6_IC1154532_KO7,20.htm"
        ),
    },
    "Raleigh, NC": {
        "url": (
            "https://www.glassdoor.com/Salaries/"
            "raleigh-veterinarian-salary-SRCH_IL.0,7_IC1138643_KO8,21.htm"
        ),
    },
}

OUTPUT_DIR = Path("output")
OUTPUT_DIR.mkdir(exist_ok=True)

HEADLESS = True          # Set False to watch the browser in action
PAGE_TIMEOUT = 30_000    # ms
NAV_DELAY = (4, 8)       # random sleep seconds between page loads


# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------

@dataclass
class SalaryRecord:
    location: str
    job_title: str
    base_pay: str
    pay_type: str          # "per year", "per hour", etc.
    low_estimate: str
    high_estimate: str
    salary_count: str      # number of salaries reported
    scraped_at: str


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _random_sleep(lo: float, hi: float) -> None:
    time.sleep(random.uniform(lo, hi))


def _clean(text: str) -> str:
    return " ".join(text.split()) if text else ""


def _parse_salary_page(html: str, location: str) -> list[SalaryRecord]:
    """Extract salary rows from a Glassdoor salary listing page."""
    soup = BeautifulSoup(html, "html.parser")
    records: list[SalaryRecord] = []
    now = datetime.utcnow().isoformat(timespec="seconds") + "Z"

    # ------------------------------------------------------------------
    # Strategy 1: structured salary rows (current Glassdoor layout)
    # ------------------------------------------------------------------
    rows = soup.select("[data-test='salary-list-item'], .salaryList__SalaryRow")
    for row in rows:
        title_el = row.select_one(
            "[data-test='salary-title'], .salaryList__JobTitle, "
            ".job-title, h3, h4"
        )
        pay_el = row.select_one(
            "[data-test='salary-median'], .salaryList__SalaryMedian, "
            ".median-salary"
        )
        range_el = row.select_one(
            "[data-test='salary-range'], .salaryList__SalaryRange, "
            ".salary-range"
        )
        count_el = row.select_one(
            "[data-test='salary-count'], .salaryList__SalaryCount, "
            ".salary-count"
        )

        job_title = _clean(title_el.get_text()) if title_el else "Veterinarian"
        base_pay_raw = _clean(pay_el.get_text()) if pay_el else ""
        range_raw = _clean(range_el.get_text()) if range_el else ""
        salary_count = _clean(count_el.get_text()) if count_el else ""

        # Parse pay type from median text e.g. "$95,000/yr"
        pay_type = ""
        base_pay = base_pay_raw
        for token, label in [("/yr", "per year"), ("/hr", "per hour"),
                              ("/mo", "per month")]:
            if token in base_pay_raw:
                pay_type = label
                base_pay = base_pay_raw.replace(token, "").strip()
                break

        # Parse low/high from range e.g. "$75K - $120K"
        low_est = high_est = ""
        range_match = re.search(r"(\$[\d,KkMm\.]+)\s*[-–]\s*(\$[\d,KkMm\.]+)",
                                range_raw)
        if range_match:
            low_est, high_est = range_match.group(1), range_match.group(2)

        if job_title or base_pay:
            records.append(SalaryRecord(
                location=location,
                job_title=job_title or "Veterinarian",
                base_pay=base_pay,
                pay_type=pay_type,
                low_estimate=low_est,
                high_estimate=high_est,
                salary_count=salary_count,
                scraped_at=now,
            ))

    # ------------------------------------------------------------------
    # Strategy 2: JSON-LD / embedded JSON fallback
    # ------------------------------------------------------------------
    if not records:
        records.extend(_parse_json_ld(soup, location, now))

    # ------------------------------------------------------------------
    # Strategy 3: generic salary number extraction fallback
    # ------------------------------------------------------------------
    if not records:
        records.extend(_parse_generic(soup, location, now))

    return records


def _parse_json_ld(soup: BeautifulSoup, location: str,
                   now: str) -> list[SalaryRecord]:
    records = []
    for tag in soup.find_all("script", type="application/ld+json"):
        try:
            data = json.loads(tag.string or "")
        except (json.JSONDecodeError, TypeError):
            continue

        items = data if isinstance(data, list) else [data]
        for item in items:
            if item.get("@type") not in ("OccupationAggregation", "Occupation",
                                         "JobPosting"):
                continue
            title = _clean(item.get("name", "Veterinarian"))
            median = item.get("estimatedSalary", {})
            if isinstance(median, list):
                median = median[0] if median else {}
            currency = median.get("currency", "USD")
            value = median.get("value", {})
            low = str(value.get("minValue", ""))
            high = str(value.get("maxValue", ""))
            med = str(value.get("value", ""))
            unit_text = value.get("unitText", "YEAR")
            pay_type = "per year" if "YEAR" in unit_text.upper() else "per hour"
            records.append(SalaryRecord(
                location=location,
                job_title=title,
                base_pay=f"${med}" if med else "",
                pay_type=pay_type,
                low_estimate=f"${low}" if low else "",
                high_estimate=f"${high}" if high else "",
                salary_count="",
                scraped_at=now,
            ))
    return records


def _parse_generic(soup: BeautifulSoup, location: str,
                   now: str) -> list[SalaryRecord]:
    """Last-resort: grab any dollar figures near the word 'veterinarian'."""
    text = soup.get_text(" ", strip=True)
    amounts = re.findall(r"\$[\d,]+(?:\.\d+)?[KkMm]?", text)
    if not amounts:
        return []
    return [SalaryRecord(
        location=location,
        job_title="Veterinarian (generic extract)",
        base_pay=amounts[0] if amounts else "",
        pay_type="",
        low_estimate=amounts[0] if len(amounts) > 0 else "",
        high_estimate=amounts[-1] if len(amounts) > 1 else "",
        salary_count=f"{len(amounts)} figures found",
        scraped_at=now,
    )]


# ---------------------------------------------------------------------------
# Browser / scraping
# ---------------------------------------------------------------------------

def _human_scroll(page) -> None:
    """Scroll the page gradually to trigger lazy-loaded content."""
    page.evaluate("""
        () => new Promise(resolve => {
            let total = 0;
            const step = () => {
                window.scrollBy(0, 300);
                total += 300;
                if (total < document.body.scrollHeight) {
                    setTimeout(step, 200 + Math.random() * 200);
                } else {
                    resolve();
                }
            };
            step();
        })
    """)
    time.sleep(1.5)


def scrape_location(page, location: str, cfg: dict) -> list[SalaryRecord]:
    url = cfg["url"]
    print(f"\n[→] Scraping {location} ...")
    print(f"    URL: {url}")

    try:
        page.goto(url, timeout=PAGE_TIMEOUT, wait_until="domcontentloaded")
    except PlaywrightTimeout:
        print("    [!] Page load timed out — using whatever loaded so far.")

    _random_sleep(2, 4)

    # Dismiss cookie / sign-in modals if present
    for selector in [
        "button[data-test='accept-cookies']",
        "#onetrust-accept-btn-handler",
        "button.modal_closeIcon",
        "[data-test='modal-close-btn']",
        ".modal_closeButton",
    ]:
        try:
            page.locator(selector).first.click(timeout=3_000)
            _random_sleep(0.5, 1)
        except Exception:
            pass

    _human_scroll(page)
    _random_sleep(1, 2)

    html = page.content()
    records = _parse_salary_page(html, location)
    print(f"    [✓] Extracted {len(records)} record(s).")
    return records


def run_scraper() -> list[SalaryRecord]:
    all_records: list[SalaryRecord] = []

    with sync_playwright() as pw:
        browser = pw.chromium.launch(
            headless=HEADLESS,
            args=[
                "--disable-blink-features=AutomationControlled",
                "--no-sandbox",
            ],
        )
        context = browser.new_context(
            viewport={"width": 1280, "height": 800},
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/122.0.0.0 Safari/537.36"
            ),
            locale="en-US",
            timezone_id="America/New_York",
        )

        # Hide webdriver flag
        context.add_init_script(
            "Object.defineProperty(navigator, 'webdriver', {get: () => undefined})"
        )

        page = context.new_page()

        for i, (location, cfg) in enumerate(LOCATIONS.items()):
            records = scrape_location(page, location, cfg)
            all_records.extend(records)
            if i < len(LOCATIONS) - 1:
                delay = random.uniform(*NAV_DELAY)
                print(f"    [~] Waiting {delay:.1f}s before next location ...")
                time.sleep(delay)

        context.close()
        browser.close()

    return all_records


# ---------------------------------------------------------------------------
# Output
# ---------------------------------------------------------------------------

def save_csv(records: list[SalaryRecord]) -> Path:
    ts = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
    out_path = OUTPUT_DIR / f"vet_salaries_{ts}.csv"
    col_names = [f.name for f in fields(SalaryRecord)]
    with open(out_path, "w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=col_names)
        writer.writeheader()
        for rec in records:
            writer.writerow({f.name: getattr(rec, f.name) for f in fields(rec)})
    return out_path


def print_summary(records: list[SalaryRecord]) -> None:
    print("\n" + "=" * 60)
    print("SALARY SUMMARY")
    print("=" * 60)
    by_location: dict[str, list[SalaryRecord]] = {}
    for r in records:
        by_location.setdefault(r.location, []).append(r)

    for loc, recs in by_location.items():
        print(f"\n{loc}:")
        for r in recs:
            parts = [f"  • {r.job_title}"]
            if r.base_pay:
                parts.append(f"median {r.base_pay} {r.pay_type}".strip())
            if r.low_estimate and r.high_estimate:
                parts.append(f"range {r.low_estimate}–{r.high_estimate}")
            if r.salary_count:
                parts.append(f"({r.salary_count})")
            print("  ".join(parts))

    if not records:
        print("  No salary data extracted.")
        print(
            "\n  NOTE: Glassdoor aggressively blocks scrapers and may require\n"
            "  a logged-in session. Try setting HEADLESS=False to debug,\n"
            "  or use the Glassdoor API / a data provider instead."
        )


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    print("Glassdoor Vet Salary Scraper")
    print(f"Locations: {', '.join(LOCATIONS)}")
    print("-" * 60)

    records = run_scraper()

    if records:
        out = save_csv(records)
        print(f"\n[✓] Saved {len(records)} record(s) → {out}")
    else:
        print("\n[!] No records saved (nothing extracted).")

    print_summary(records)
