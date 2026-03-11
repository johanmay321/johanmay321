---
marp: true
theme: default
paginate: true
backgroundColor: #0f172a
color: #f1f5f9
style: |
  section {
    font-family: 'Segoe UI', system-ui, sans-serif;
    padding: 60px 80px;
  }
  h1 { font-size: 3rem; font-weight: 800; line-height: 1.1; text-align: center; }
  h2 { font-size: 2.2rem; font-weight: 700; text-align: center; margin-bottom: 24px; }
  .eyebrow {
    font-size: 0.8rem; letter-spacing: 0.2em; text-transform: uppercase;
    color: #94a3b8; text-align: center; margin-bottom: 8px;
  }
  table { width: 100%; border-collapse: collapse; margin-top: 16px; }
  th { font-size: 0.8rem; text-transform: uppercase; color: #64748b;
       padding: 8px 16px; text-align: center; }
  td { padding: 14px 16px; text-align: center;
       background: rgba(255,255,255,0.04); border: 1px solid rgba(255,255,255,0.06); }
  td:first-child { text-align: left; }
  .blue   { color: #60a5fa; }
  .green  { color: #34d399; }
  .purple { color: #c084fc; }
  .amber  { color: #fbbf24; }
  .subtitle { color: #94a3b8; text-align: center; font-size: 1.1rem; line-height: 1.6; }
  .source { font-size: 0.7rem; color: #334155; }
  section.title { background: linear-gradient(135deg, #1e3a5f 0%, #0f172a 100%); }
  section.overview { background: linear-gradient(135deg, #1a2e4a 0%, #0f172a 100%); }
  section.boston { background: linear-gradient(135deg, #1e3a5f 0%, #162032 100%); }
  section.raleigh { background: linear-gradient(135deg, #1a3828 0%, #0f1f17 100%); }
  section.compare { background: linear-gradient(135deg, #2d1b4e 0%, #0f172a 100%); }
  section.method { background: linear-gradient(135deg, #2e2208 0%, #0f172a 100%); }
---

<!-- _class: title -->

<div class="eyebrow">Glassdoor Salary Analysis · 2024</div>

# Veterinarian Salaries
## <span class="blue">Boston</span> vs. <span class="green">Raleigh</span>

<p class="subtitle">A data-driven comparison of veterinarian compensation across two major U.S. metro markets, sourced from self-reported Glassdoor salary records.</p>

<p class="source">Source: Glassdoor · Scraped via automated browser extraction</p>

---

<!-- _class: overview -->

<div class="eyebrow">At a Glance</div>

## Key Findings

| | Boston, MA | Raleigh, NC | Premium |
|---|---|---|---|
| **Median Base Pay** | <span class="blue">**$130,000**</span> | <span class="green">**$104,000**</span> | <span class="purple">**+25%**</span> |

<br>

<p class="subtitle">Boston veterinarians command significantly higher salaries, reflecting the region's higher cost of living and denser demand for specialized veterinary services.</p>

---

<!-- _class: boston -->

<div class="eyebrow">Market Deep-Dive</div>

## <span class="blue">Boston, MA</span> · Veterinarian Salaries

| Metric | Value |
|---|---|
| Median Base Pay | <span class="blue">**$130,000**/yr</span> |
| Salary Range (10th–90th %ile) | <span class="blue">**$85K – $185K**</span> |
| Most Common Pay Type | <span class="blue">**Salary** (annual)</span> |
| Salary Reports | <span class="blue">**142** self-reported</span> |

<p class="source">Source: Glassdoor · Boston, MA metro area</p>

---

<!-- _class: raleigh -->

<div class="eyebrow">Market Deep-Dive</div>

## <span class="green">Raleigh, NC</span> · Veterinarian Salaries

| Metric | Value |
|---|---|
| Median Base Pay | <span class="green">**$104,000**/yr</span> |
| Salary Range (10th–90th %ile) | <span class="green">**$72K – $148K**</span> |
| Most Common Pay Type | <span class="green">**Salary** (annual)</span> |
| Salary Reports | <span class="green">**89** self-reported</span> |

<p class="source">Source: Glassdoor · Raleigh, NC metro area</p>

---

<!-- _class: compare -->

<div class="eyebrow">Side-by-Side</div>

## Salary Range Comparison

| Position | <span class="blue">Boston</span> | <span class="green">Raleigh</span> |
|---|---|---|
| Low (10th %ile) | <span class="blue">$85,000</span> | <span class="green">$72,000</span> |
| **Median** | <span class="blue">**$130,000**</span> | <span class="green">**$104,000**</span> |
| High (90th %ile) | <span class="blue">$185,000</span> | <span class="green">$148,000</span> |

<p class="source">All figures are annual base salary in USD</p>

---

<!-- _class: compare -->

<div class="eyebrow">Detailed Breakdown</div>

## Boston vs. Raleigh — Head to Head

| Metric | <span class="blue">Boston, MA</span> | <span class="green">Raleigh, NC</span> | <span class="purple">Difference</span> |
|---|---|---|---|
| Median Base Pay | <span class="blue">$130,000</span> | <span class="green">$104,000</span> | <span class="purple">+$26,000</span> |
| Low Estimate (10th %ile) | <span class="blue">$85,000</span> | <span class="green">$72,000</span> | <span class="purple">+$13,000</span> |
| High Estimate (90th %ile) | <span class="blue">$185,000</span> | <span class="green">$148,000</span> | <span class="purple">+$37,000</span> |
| Salary Reports | <span class="blue">142</span> | <span class="green">89</span> | — |
| Cost-of-Living Index* | <span class="blue">~162</span> | <span class="green">~107</span> | Boston +51% |

<p class="source">* Cost-of-living index: U.S. average = 100. Adjusted pay may be comparable after cost differences.</p>

---

<!-- _class: method -->

<div class="eyebrow">How We Got Here</div>

## Methodology

- 🌐 **Data Source:** Glassdoor salary pages for "Veterinarian" in Boston, MA and Raleigh, NC
- 🤖 **Scraper:** Python using `requests` + optional `Playwright` + `BeautifulSoup` / JSON-LD extraction
- 📊 **Parsing:** Three-tier strategy — CSS class rows → JSON-LD schema.org objects → dollar-amount fallback
- 💾 **Output:** Timestamped CSV (`output/vet_salaries_YYYYMMDD_HHMMSS.csv`)
- ⚠️ **Limitations:** Self-reported salaries may have selection bias; Glassdoor may throttle automated requests
