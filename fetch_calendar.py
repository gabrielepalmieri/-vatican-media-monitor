#!/usr/bin/env python3
"""Build the daily Rome calendar from Vatican News and the Italian UN calendar."""
from __future__ import annotations

import html
import json
import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import urljoin, urlparse
from urllib.request import Request, urlopen
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parent
OUT = ROOT / "calendar.json"
UN_URL = "https://unric.org/it/giornate-internazionali-onu/"
SAINT_BASE = "https://www.vaticannews.va/it/santo-del-giorno/"
ROME = ZoneInfo("Europe/Rome")


def clean(value: str) -> str:
    return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", value))).strip()


def fetch(url: str) -> str:
    request = Request(url, headers={"User-Agent": "Mozilla/5.0 VaticanMediaMonitor/1.0", "Accept": "text/html"})
    with urlopen(request, timeout=25) as response:
        return response.read().decode("utf-8")


def safe_url(value: str, base: str) -> str:
    result = urljoin(base, html.unescape(value))
    return result if urlparse(result).scheme == "https" else base


def parse_un(page: str) -> list[dict]:
    records = []
    for attrs, body in re.findall(r'<article\b([^>]*\bitd-card\b[^>]*)>(.*?)</article>', page, re.S):
        # The feature shows days, not week-long observances.
        if 'data-type="day"' not in attrs:
            continue
        month = re.search(r'data-month="(\d+)"', attrs)
        day = re.search(r'data-day="(\d+)"', attrs)
        title = re.search(r'<h3\b[^>]*>(.*?)</h3>', body, re.S)
        label = re.search(r'<p\b[^>]*class="itd-card-date"[^>]*>(.*?)</p>', body, re.S)
        link = re.search(r'<a\b[^>]*class="itd-source-link"[^>]*href="([^"]+)"', body)
        if not all((month, day, title, label)):
            continue
        label = clean(label[1])
        explicit_year = re.search(r'\b(20\d{2})\b', label)
        span = re.match(r'(\d+)\s*[–-]\s*(\d+)', label)
        first_day = int(day[1])
        last_day = int(span[2]) if span else first_day
        if not (1 <= int(month[1]) <= 12 and 1 <= first_day <= last_day <= 31):
            continue
        name = clean(title[1])
        url = safe_url(link[1], UN_URL) if link else UN_URL
        # UNRIC's habitat entry currently links to the teachers' day by mistake.
        if "habitat" in name.lower():
            url = "https://www.un.org/en/observances/habitat-day"
        records.append({"title": name, "month": int(month[1]), "day": first_day,
                        "end_day": last_day, "year": int(explicit_year[1]) if explicit_year else None,
                        "url": url})
    if len(records) < 150:
        raise ValueError("Incomplete UN calendar; preserving the previous verified copy")
    return records


def un_for_day(records: list[dict], day: date) -> list[dict]:
    return [{"title": x["title"], "url": x["url"]} for x in records
            if x["month"] == day.month and x["day"] <= day.day <= x.get("end_day", x["day"])
            and x.get("year") in (None, day.year)]


def parse_saints(page: str, day: date) -> list[dict]:
    records = []
    base = f"{SAINT_BASE}{day:%m/%d}.html"
    for section in re.findall(r'<section\b[^>]*section--isStatic[^>]*>(.*?)</section>', page, re.S):
        title = re.search(r'<h2\b[^>]*>(.*?)</h2>', section, re.S)
        link = re.search(r'<a\b[^>]*class="saintReadMore"[^>]*href="([^"]+)"', section)
        if title:
            records.append({"title": clean(title[1]), "url": safe_url(link[1], base) if link else base})
    if not records:
        raise ValueError(f"No saints parsed for {day}; preserving existing data")
    return records


def easter(year: int) -> date:
    a, b, c = year % 19, year // 100, year % 100
    d, e, f = b // 4, b % 4, (b + 8) // 25
    g = (b - f + 1) // 3
    h = (19 * a + b - d - g + 15) % 30
    i, k = c // 4, c % 4
    l = (32 + 2 * e + 2 * i - h - k) % 7
    m = (a + 11 * h + 22 * l) // 451
    return date(year, (h + l - 7 * m + 114) // 31, (h + l - 7 * m + 114) % 31 + 1)


def sunday(year: int, month: int, ordinal: int) -> date:
    first = date(year, month, 1)
    return first + timedelta(days=(6 - first.weekday()) % 7 + 7 * (ordinal - 1))


def holy_see_days(year: int) -> dict[str, list[dict]]:
    """Core recurring worldwide observances; annual exceptions belong in overrides."""
    result: dict[str, list[dict]] = {}
    def add(day: date, title: str, url: str):
        result.setdefault(day.isoformat(), []).append({"title": title, "url": url})
    messages = "https://www.vatican.va/content/leo-xiv/it/messages/"
    fixed = [
        (1, 1, "Giornata mondiale della pace", messages + "peace.html"),
        (2, 2, "Giornata mondiale della vita consacrata", "https://www.vatican.va/content/leo-xiv/it/homilies/2026.html"),
        (2, 8, "Giornata mondiale di preghiera e riflessione contro la tratta di persone", "https://www.vatican.va/content/leo-xiv/it/angelus/2026/documents/20260208-angelus.html"),
        (2, 11, "Giornata mondiale del malato", messages + "sick.html"),
        (9, 1, "Giornata mondiale di preghiera per la cura del creato", messages + "creation.html"),
        (11, 21, "Giornata Pro Orantibus", "https://www.vaticannews.va/it/festivita-liturgiche/presentazione-della-beata-vergine-maria-.html"),
    ]
    for month, day, title, url in fixed:
        add(date(year, month, day), title, url)
    pascha = easter(year)
    add(pascha + timedelta(days=21), "Giornata mondiale di preghiera per le vocazioni", messages + "vocations.html")
    add(pascha + timedelta(days=42), "Giornata mondiale delle comunicazioni sociali", messages + "communications.html")
    add(pascha + timedelta(days=68), "Giornata mondiale di santificazione sacerdotale", "https://www.clerus.va/it/ministri-ordinati/giornate-mondiali-di-preghiera-per-le-vocazioni.html")
    add(sunday(year, 7, 2), "Domenica del Mare", "https://press.vatican.va/content/salastampa/it/bollettino/pubblico/2026/06/24/0548/01035.html")
    add(sunday(year, 7, 4), "Giornata mondiale dei nonni e degli anziani", messages + "grandparents.html")
    last_september = date(year, 9, 30)
    migrant_day = last_september - timedelta(days=(last_september.weekday() - 6) % 7)
    if year == 2025:  # The Jubilee edition was moved to 4–5 October.
        migrant_day = date(2025, 10, 5)
    add(migrant_day, "Giornata mondiale del migrante e del rifugiato", messages + "migration.html")
    # Mission Sunday is the penultimate Sunday of October, not always the third.
    last_october = date(year, 10, 31)
    mission_day = last_october - timedelta(days=(last_october.weekday() - 6) % 7 + 7)
    add(mission_day, "Giornata missionaria mondiale", messages + "mission.html")
    christmas = date(year, 12, 25)
    advent = christmas - timedelta(days=(christmas.weekday() - 6) % 7 or 7) - timedelta(days=21)
    christ_king = advent - timedelta(days=7)
    add(christ_king - timedelta(days=7), "Giornata mondiale dei poveri", messages + "poor.html")
    add(christ_king, "Giornata mondiale della gioventù (celebrazione diocesana)", messages + "youth.html")
    return result


def main():
    today = datetime.now(ROME).date()
    now = datetime.now(timezone.utc).isoformat()
    try:
        old = json.loads(OUT.read_text())
    except (OSError, ValueError):
        old = {}
    un = old.get("un_observances", [])
    verified = old.get("un_verified_at")
    try:
        un = parse_un(fetch(UN_URL))
        verified = now
    except Exception as error:
        print(f"UN calendar: {error}")
    days = [today + timedelta(days=i) for i in range(-1, 36)]
    old_days = old.get("days", {})
    saints = {d.isoformat(): old_days.get(d.isoformat(), {}).get("saints", []) for d in days}
    missing = [d for d in days if not saints[d.isoformat()] or d == today]
    def load(day):
        return parse_saints(fetch(f"{SAINT_BASE}{day:%m/%d}.html"), day)
    with ThreadPoolExecutor(max_workers=4) as pool:
        futures = {pool.submit(load, d): d for d in missing}
        for future in as_completed(futures):
            day = futures[future]
            try:
                saints[day.isoformat()] = future.result()
            except Exception as error:
                print(f"Saints {day}: {error}")
    holy = {}
    for year in {d.year for d in days}:
        holy.update(holy_see_days(year))
    data = {"updated_at": now, "timezone": "Europe/Rome", "un_source": UN_URL,
            "un_verified_at": verified, "un_observances": un, "days": {}}
    for day in days:
        key = day.isoformat()
        data["days"][key] = {"saints": saints[key], "un": un_for_day(un, day),
                             "un_available": bool(un), "holy_see": holy.get(key, [])}
    OUT.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n")
    print(f"Saved {len(days)} dates, {sum(bool(x) for x in saints.values())} saint entries, {len(un)} UN observances")


if __name__ == "__main__":
    main()
