#!/usr/bin/env python3
import json
import re
from datetime import date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[1]
CFG = json.loads((ROOT / "config.json").read_text(encoding="utf-8"))
TZ = ZoneInfo(CFG.get("timezone", "Europe/Amsterdam"))
OUT = ROOT / "site"
OUT.mkdir(exist_ok=True)

MAX_MATCHES_PER_PAGE = 5
PAGE_INTERVAL_SECONDS = 12

MONTHS = {
    "jan": 1, "feb": 2, "mrt": 3, "mar": 3,
    "apr": 4, "mei": 5, "jun": 6, "jul": 7,
    "aug": 8, "sep": 9, "okt": 10, "nov": 11, "dec": 12,
}


def parse_date(value, today):
    value = value.lower().strip()

    # Datum zoals 28-11-2026 of 28/11/2026
    m = re.search(r"(\d{1,2})[-/](\d{1,2})[-/](20\d{2})", value)
    if m:
        try:
            return date(int(m.group(3)), int(m.group(2)), int(m.group(1)))
        except ValueError:
            return None

    # Datum zoals 28 nov. of 28 november
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
        page = browser.new_page(
            locale="nl-NL",
            viewport={"width": 1920, "height": 1080}
        )

        page.goto(
            CFG["source_url"],
            wait_until="domcontentloaded",
            timeout=60000
        )

        # Geef de dynamische pagina tijd om het programma te laden.
        page.wait_for_timeout(10000)

        rows = page.evaluate("""() => {
            const all = [];
            const elements = [...document.querySelectorAll('tr, [role="row"]')];

            for (const row of elements) {
                const cells = [...row.querySelectorAll(
                    ':scope > td, :scope > th, ' +
                    ':scope > [role="cell"], ' +
                    ':scope > [role="gridcell"], ' +
                    ':scope > [role="columnheader"]'
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

    end_date = today + timedelta(
        days=int(CFG.get("lookahead_days", 7))
    )

    # Zoek de tabelkop.
    header = None

    for cells in rows:
        normalized = [c.strip().lower() for c in cells]

        if (
            any("datum" in c for c in normalized)
            and any("thuis" in c for c in normalized)
            and any(c == "uit" or c.endswith(" uit") for c in normalized)
        ):
            header = normalized
            break

    if not header:
        return [], "De kolomkop Datum / Thuis / Uit is niet gevonden."

    date_idx = next(
        (i for i, c in enumerate(header) if "datum" in c), None
    )
    time_idx = next(
    (i for i, c in enumerate(header)
     if "tijd" in c or "tjd" in c or "time" in c), None
)
    home_idx = next(
        (i for i, c in enumerate(header) if "thuis" in c), None
    )
    away_idx = next(
        (i for i, c in enumerate(header)
         if c == "uit" or c.endswith(" uit"), None)
    )

    if None in (date_idx, time_idx, home_idx, away_idx):
        return [], "De benodigde kolommen konden niet worden herkend."

    current_date = None

    for cells in rows:
        # Sla de tabelkop over.
        normalized = [c.strip().lower() for c in cells]
        if normalized == header:
            continue

        # Controleer of de rij voldoende kolommen heeft.
        if max(date_idx, time_idx, home_idx, away_idx) >= len(cells):
            continue

        date_text = cells[date_idx].strip()
        time_text = cells[time_idx].strip()
        home = cells[home_idx].strip()
        away = cells[away_idx].strip()

        # Datum kan bij sommige tabelregels leeg zijn.
        parsed = parse_date(date_text, today)
        if parsed:
            current_date = parsed

        if not current_date:
            continue

        # Sla lege regels en groepskoppen over.
        if not home or not away:
            continue

        if not re.search(r"\d", time_text):
            continue

        # Alleen toekomstige wedstrijden in het ingestelde tijdvak.
        if current_date < today or current_date > end_date:
            continue

        # Juliana moet de thuisploeg zijn.
        if "juliana" not in home.lower():
            continue

        # Tijd normaliseren naar HH:MM indien mogelijk.
        time_match = re.search(r"(\d{1,2}:\d{2})", time_text)
        if time_match:
            time_text = time_match.group(1)

        matches.append({
            "date": current_date.strftime("%d-%m-%Y"),
            "date_iso": current_date.isoformat(),
            "time": time_text,
            "home": home,
            "away": away,
        })

    # Sorteer op datum en tijd.
    matches.sort(key=lambda m: (m["date_iso"], m["time"]))

    # Voorkom dubbele wedstrijden.
    unique = []
    seen = set()

    for m in matches:
        key = (m["date_iso"], m["time"], m["home"], m["away"])
        if key not in seen:
            seen.add(key)
            unique.append(m)

    return unique, None


def split_pages(matches):
    return [
        matches[i:i + MAX_MATCHES_PER_PAGE]
        for i in range(0, len(matches), MAX_MATCHES_PER_PAGE)
    ]


def build_html(matches, error=None):
    pages = split_pages(matches)

    if not pages:
        pages = [[]]

    page_html = []

    for page_index, page_matches in enumerate(pages):
        cards = []

        for m in page_matches:
            cards.append(f"""
                <div class="match">
                    <div class="date">{m["date"]}</div>
                    <div class="time">{m["time"]}</div>
                    <div class="teams">
                        <span class="home">{m["home"]}</span>
                        <span class="dash">–</span>
                        <span class="away">{m["away"]}</span>
                    </div>
                </div>
            """)

        if error:
            content = f"""
                <div class="empty">
                    <h2>Programma kon niet worden geladen</h2>
                    <p>{error}</p>
                    <p>Controleer de bronpagina.</p>
                </div>
            """
        elif not page_matches:
            content = """
                <div class="empty">
                    <h2>Op dit moment zijn er geen wedstrijden gevonden.</h2>
                    <p>Het programma wordt automatisch vernieuwd.</p>
                </div>
            """
        else:
            content = "".join(cards)

        page_html.append(f"""
            <section class="screen">
                <div class="content">
                    {content}
                </div>
                <div class="page-number">
                    {page_index + 1} / {len(pages)}
                </div>
            </section>
        """)

    html = f"""<!DOCTYPE html>
<html lang="nl">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<meta http-equiv="refresh" content="900">
<title>KV Juliana - Thuisprogramma</title>

<style>
* {{
    box-sizing: border-box;
}}

body {{
    margin: 0;
    background: #f4f6fa;
    font-family: Arial, Helvetica, sans-serif;
    color: #17365d;
    overflow: hidden;
}}

.screen {{
    display: none;
    width: 100vw;
    height: 100vh;
    padding: 2.5vh 3.4vw 12vh;
}}

.screen.active {{
    display: block;
}}

.header {{
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 30px;
    border-bottom: 5px solid #f58200;
    padding-bottom: 1.5vh;
    margin-bottom: 2vh;
}}

.club {{
    font-weight: 900;
    font-size: 3vw;
    letter-spacing: 1px;
}}

.heading {{
    flex: 1;
}}

.heading h1 {{
    margin: 0;
    font-size: 3.8vw;
    font-weight: 900;
}}

.heading p {{
    margin: 0.3vh 0 0;
    color: #f58200;
    font-size: 2vw;
    font-weight: bold;
}}

.content {{
    height: 76vh;
    overflow: hidden;
}}

.match {{
    display: grid;
    grid-template-columns: 19% 12% 69%;
    align-items: center;
    background: #ffffff;
    margin-bottom: 1.2vh;
    min-height: 11vh;
    border-radius: 12px;
    border-left: 16px solid #f58200;
    box-shadow: 0 3px 8px rgba(0,0,0,0.06);
    padding: 1.5vh 2vw;
    gap: 1vw;
}}

.date {{
    font-size: 2.1vw;
    font-weight: 900;
    white-space: nowrap;
}}

.time {{
    color: #f58200;
    font-size: 2.1vw;
    font-weight: 900;
    white-space: nowrap;
}}

.teams {{
    display: flex;
    align-items: center;
    gap: 1.1vw;
    font-size: 2.05vw;
    font-weight: 800;
    white-space: nowrap;
    overflow: hidden;
}}

.home, .away {{
    overflow: hidden;
    text-overflow: ellipsis;
}}

.dash {{
    color: #f58200;
    font-weight: 900;
}}

.empty {{
    background: white;
    border-radius: 15px;
    padding: 5vh 3vw;
    text-align: center;
    margin-top: 2vh;
}}

.empty h2 {{
    font-size: 2.5vw;
    font-weight: normal;
}}

.empty p {{
    font-size: 1.5vw;
}}

.page-number {{
    position: absolute;
    right: 3vw;
    bottom: 12vh;
    color: #718096;
    font-size: 1vw;
}}

.footer {{
    position: fixed;
    bottom: 4vh;
    left: 3.4vw;
    right: 3.4vw;
    background: #17365d;
    color: white;
    border-radius: 12px;
    padding: 2vh 2vw;
    display: flex;
    justify-content: space-between;
    align-items: center;
    font-size: 1.8vw;
    font-weight: bold;
}}

@media (orientation: portrait) {{
    .match {{
        grid-template-columns: 30% 20% 50%;
    }}
}}
</style>
</head>

<body>

<div class="header" style="margin:2.5vh 3.4vw 2vh;">
    <div class="club">KV JULIANA</div>
    <div class="heading">
        <h1>THUIS IN 'T VEERHUIS</h1>
        <p>WEDSTRIJDPROGRAMMA</p>
    </div>
</div>

{"".join(page_html)}

<div class="footer">
    <span>Kom onze teams aanmoedigen!</span>
    <span>kvjuliana.nl</span>
</div>

<script>
const screens = document.querySelectorAll(".screen");
let current = 0;

function showScreen(index) {{
    screens.forEach(s => s.classList.remove("active"));
    screens[index].classList.add("active");
}}

showScreen(current);

if (screens.length > 1) {{
    setInterval(() => {{
        current = (current + 1) % screens.length;
        showScreen(current);
    }}, {PAGE_INTERVAL_SECONDS * 1000});
}}
</script>

</body>
</html>
"""

    return html


def main():
    today = datetime.now(TZ).date()

    try:
        rows, source_html = get_rows()
        matches, error = find_matches(rows, today)

        # Bewaar diagnostiek zodat het scrape-resultaat controleerbaar is.
        (OUT / "debug.json").write_text(
            json.dumps({
                "generated": datetime.now(TZ).isoformat(),
                "rows_found": len(rows),
                "matches_found": len(matches),
                "matches": matches,
                "error": error,
                "source_html_length": len(source_html),
            }, indent=2, ensure_ascii=False),
            encoding="utf-8"
        )

        html = build_html(matches, error)

    except Exception as exc:
        error = f"Fout tijdens ophalen/verwerken: {exc}"
        print(error)

        html = build_html([], error)

        (OUT / "debug.json").write_text(
            json.dumps({
                "generated": datetime.now(TZ).isoformat(),
                "error": error
            }, indent=2, ensure_ascii=False),
            encoding="utf-8"
        )

    (OUT / "index.html").write_text(html, encoding="utf-8")
    print("HTML gepubliceerd in site/index.html")


if __name__ == "__main__":
    main()
