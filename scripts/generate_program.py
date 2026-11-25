
#!/usr/bin/env python3
import json
import re
from datetime import datetime, date, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[1]
CFG = json.loads((ROOT / "config.json").read_text(encoding="utf-8"))
TZ = ZoneInfo(CFG.get("timezone", "Europe/Amsterdam"))
OUT = ROOT / "site"
OUT.mkdir(exist_ok=True)

MONTHS = {
    "jan": 1, "feb": 2, "mrt": 3, "mar": 3,
    "apr": 4, "mei": 5, "jun": 6, "jul": 7,
    "aug": 8, "sep": 9, "okt": 10, "nov": 11, "dec": 12,
}

MAX_MATCHES_PER_PAGE = 5
PAGE_INTERVAL_SECONDS = 8


def parse_date(value, today):
    value = value.lower().strip()

    m = re.search(r"(\d{1,2})[-/](\d{1,2})[-/](20\d{2})", value)
    if m:
        try:
            return date(int(m.group(3)), int(m.group(2)), int(m.group(1)))
        except ValueError:
            return None

    m = re.search(r"(\d{1,2})\s+([a-z]+)", value)
    if m:
        month = MONTHS.get(m.group(2)[:3])
        if month:
            year = today.year
            try:
                d = date(year, month, int(m.group(1)))
                if d < today - timedelta(days=180):
                    d = date(year + 1, month, int(m.group(1)))
                return d
            except ValueError:
                return None
    return None


def get_rows():
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page()
        page.goto(CFG["source_url"], wait_until="domcontentloaded", timeout=60000)
        page.wait_for_timeout(8000)

        rows = page.evaluate("""() => {
            const all = [];
            const elements = [...document.querySelectorAll('tr, [role="row"]')];

            for (const row of elements) {
                const cells = [...row.querySelectorAll(
                    ':scope > td, :scope > th, :scope > [role="cell"], :scope > [role="gridcell"], :scope > [role="columnheader"]'
                )];

                if (cells.length >= 2) {
                    all.push(cells.map(c => c.innerText.trim()));
                }
            }
            return all;
        }""")

        html = page.content()
        browser.close()

    return rows, html


def find_matches(rows, today):
    matches = []
    diagnostics = []
    end_date = today + timedelta(days=int(CFG.get("lookahead_days", 7)))

    header = None
    for cells in rows:
        normalized = [c.strip().lower() for c in cells]
        if any("thuis" in c for c in normalized) and any(
            "uit" == c or c.endswith(" uit") for c in normalized
        ):
            header = normalized
            break

    if not header:
        return [], [{"error": "Header met THUIS en UIT niet gevonden", "rows": rows}]

    date_idx = next((i for i, c in enumerate(header) if "datum" in c), None)
    time_idx = next((i for i, c in enumerate(header) if "tijd" in c), None)
    home_idx = next((i for i, c in enumerate(header) if "thuis" in c), None)
    away_idx = next((i for i, c in enumerate(header) if c == "uit" or c.endswith(" uit")), None)

    if None in (date_idx, time_idx, home_idx, away_idx):
        return [], [{"error": "Kolomindex niet gevonden", "header": header}]

    for cells in rows:
        if len(cells) <= max(date_idx, time_idx, home_idx, away_idx):
            continue

        datum = cells[date_idx].strip()
        tijd = cells[time_idx].strip()
        thuis = cells[home_idx].strip()
        uit = cells[away_idx].strip()

        parsed = parse_date(datum, today)

        record = {
            "cells": cells,
            "date": datum,
            "time": tijd,
            "home": thuis,
            "away": uit,
            "parsed_date": str(parsed) if parsed else None,
        }
        diagnostics.append(record)

        if not parsed or not re.fullmatch(r"\d{1,2}:\d{2}", tijd):
            continue

        if not (today <= parsed <= end_date):
            continue

        if "juliana" not in thuis.lower():
            continue

        if not thuis or not uit:
            continue

        matches.append({
            "date": parsed.strftime("%d-%m-%Y"),
            "time": tijd,
            "home": thuis,
            "away": uit,
        })

    matches.sort(key=lambda x: (x["date"], x["time"]))
    return matches, diagnostics


def render(matches):
    # Wedstrijden groeperen per wedstrijddag
    grouped = {}
    for m in matches:
        grouped.setdefault(m["date"], []).append(m)

    day_html = ""

    for datum, day_matches in grouped.items():
        chunks = [
            day_matches[i:i + MAX_MATCHES_PER_PAGE]
            for i in range(0, len(day_matches), MAX_MATCHES_PER_PAGE)
        ]

        pages_html = ""

        for page_index, chunk in enumerate(chunks):
            match_rows = "".join(
                f"""<article class="match">
                    <div class="time">{m["time"]}</div>
                    <div class="teams">{m["home"]}
                    <span>–</span> {m["away"]}</div>
                </article>"""
                for m in chunk
            )

            pages_html += f"""
            <div class="page {'active' if page_index == 0 else ''}">
                {match_rows}
            </div>
            """

        page_label = (
            f'<div class="page-label">Pagina 1/{len(chunks)}</div>'
            if len(chunks) > 1 else ""
        )

        day_html += f"""
        <section class="day" data-pages="{len(chunks)}">
            <div class="day-header">
                <h2>{datum}</h2>
                {page_label}
            </div>
            <div class="pages">
                {pages_html}
            </div>
        </section>
        """

    if not matches:
        day_html = """
        <div class="empty">
        Op dit moment zijn er geen thuiswedstrijden gevonden.
        </div>
        """

    html = f"""<!DOCTYPE html>
<html lang="nl">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<meta http-equiv="refresh" content="900">
<title>KV Juliana thuisprogramma</title>
<style>
*{{box-sizing:border-box}}

body{{margin:0;background:#f6f8fc;color:#15345c;
font-family:Arial,Helvetica,sans-serif}}

main{{width:100vw;height:100vh;padding:3vw 4vw;
display:flex;flex-direction:column;gap:1.5vh;overflow:hidden}}

header{{display:flex;align-items:center;gap:2vw;
border-bottom:5px solid #f58200;padding-bottom:1.5vh}}

.brand{{font-size:clamp(20px,3vw,52px);font-weight:900;
letter-spacing:.04em}}

h1{{font-size:clamp(26px,4vw,64px);margin:0}}

.subtitle{{font-size:clamp(14px,2vw,32px);
font-weight:700;color:#f58200}}

.content{{flex:1;min-height:0;overflow:auto;
display:flex;flex-direction:column;gap:1.5vh}}

.day{{background:white;border-radius:12px;padding:1.5vh 1.5vw;
box-shadow:0 2px 10px #0001}}

.day-header{{display:flex;justify-content:space-between;
align-items:center;border-bottom:2px solid #f58200;
padding-bottom:1vh;margin-bottom:1vh}}

.day-header h2{{margin:0;font-size:clamp(20px,2.6vw,40px)}}

.page-label{{color:#f58200;font-size:clamp(14px,1.5vw,24px);
font-weight:700}}

.pages{{position:relative}}

.page{{display:none}}

.page.active{{display:block}}

.match{{display:flex;align-items:center;gap:2vw;
background:#f6f8fc;border-left:1vw solid #f58200;
padding:1.3vh 1.5vw;border-radius:8px;margin-bottom:1vh;
font-size:clamp(16px,2.2vw,34px)}}

.time{{font-weight:900;min-width:8vw;color:#f58200}}

.teams{{font-weight:700}}

.teams span{{color:#f58200;padding:0 .5em}}

.empty{{font-size:clamp(22px,3vw,44px);padding:5vh;
background:white;border-radius:12px;text-align:center}}

footer{{background:#15345c;color:white;
padding:1.8vh 2vw;border-radius:8px;display:flex;
justify-content:space-between;font-size:clamp(13px,1.8vw,28px);
font-weight:700;flex-shrink:0}}

</style>
</head>
<body>
<main>
<header>
<div class="brand">KV JULIANA</div>
<div>
<h1>THUIS IN 'T VEERHUIS</h1>
<div class="subtitle">WEDSTRIJDPROGRAMMA</div>
</div>
</header>

<section class="content">
{day_html}
</section>

<footer>
<span>Kom onze teams aanmoedigen!</span>
<span>kvjuliana.nl</span>
</footer>
</main>

<script>
document.querySelectorAll('.day[data-pages]').forEach(day => {{
    const pages = day.querySelectorAll('.page');
    const total = pages.length;

    if (total <= 1) return;

    let current = 0;
    const label = day.querySelector('.page-label');

    setInterval(() => {{
        pages[current].classList.remove('active');
        current = (current + 1) % total;
        pages[current].classList.add('active');

        if (label) {{
            label.textContent = `Pagina ${{current + 1}}/${{total}}`;
        }}
    }}, {PAGE_INTERVAL_SECONDS * 1000});
}});
</script>
</body>
</html>"""

    (OUT / "index.html").write_text(html, encoding="utf-8")
    (OUT / "matches.json").write_text(
        json.dumps(matches, ensure_ascii=False, indent=2),
        encoding="utf-8"
    )


def main():
    today = datetime.now(TZ).date()
    rows, html = get_rows()

    (OUT / "source.html").write_text(html, encoding="utf-8")

    matches, diagnostics = find_matches(rows, today)

    (OUT / "diagnostics.json").write_text(
        json.dumps(diagnostics, ensure_ascii=False, indent=2),
        encoding="utf-8"
    )

    render(matches)
    print(f"Rows collected: {len(rows)}")
    print(f"Matches found: {len(matches)}")


if __name__ == "__main__":
    main()
