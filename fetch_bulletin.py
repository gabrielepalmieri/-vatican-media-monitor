#!/usr/bin/env python3
"""Cache official Italian Holy See Bulletin monthly indexes for date lookup."""
from __future__ import annotations

import argparse
import html
import json
import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date, datetime, timezone
from pathlib import Path
from urllib.parse import urljoin, urlparse
from urllib.request import Request, urlopen
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parent
OUT = ROOT / "bulletins"
HOST = "https://press.vatican.va"
BASE = HOST + "/content/salastampa/it/bollettino/pubblico/"
ROME = ZoneInfo("Europe/Rome")


def clean(value):
    return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", value))).strip()


def fetch(url):
    request = Request(url, headers={"User-Agent": "Mozilla/5.0 VaticanMediaMonitor/1.0"})
    with urlopen(request, timeout=25) as response:
        return response.read().decode("utf-8")


def parse_month(page, year, month):
    days = {}
    seen = set()
    for href, markup in re.findall(r'<a\b[^>]*href="([^"]+)"[^>]*>(.*?)</a>', page, re.S):
        url = urljoin(HOST, html.unescape(href))
        if urlparse(url).hostname != "press.vatican.va":
            continue
        match = re.search(r'/it/bollettino/pubblico/(\d{4})/(\d{2})/(\d{2})/(\d{4})/(\d+)\.html$', url)
        if not match or int(match[1]) != year or int(match[2]) != month or url in seen:
            continue
        try:
            key = date(year, month, int(match[3])).isoformat()
        except ValueError:
            continue
        title = re.sub(r'\s*\[B\d+\]\s*$', '', clean(markup)).strip()
        if not title or title.startswith("[B"):
            continue
        seen.add(url)
        days.setdefault(key, []).append({"title": title, "number": "B" + match[4], "url": url})
    if "jcr_content-parsys-list" not in page:
        raise ValueError("Official monthly listing not found; preserving previous data")
    for items in days.values():
        items.sort(key=lambda x: int(x["number"][1:]), reverse=True)
    return days


def collect_month(year, month, today):
    key = f"{year:04d}-{month:02d}"
    page = fetch(f"{BASE}{year:04d}/{month:02d}.html")
    days = parse_month(page, year, month)
    payload = {"month": key, "checked_at": datetime.now(timezone.utc).isoformat(),
               "checked_through": today.isoformat(), "source": f"{BASE}{year:04d}/{month:02d}.html",
               "days": days}
    (OUT / f"{key}.json").write_text(json.dumps(payload, ensure_ascii=False, separators=(",", ":")) + "\n")
    return key, sum(len(items) for items in days.values())


def archive_years(page):
    years = sorted({int(x) for x in re.findall(r'<option\b[^>]*value="(\d{4})"', page)})
    if not years:
        raise ValueError("Archive years unavailable")
    return years


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--seed", action="store_true", help="Collect recent months only for the initial preview")
    args = parser.parse_args()
    OUT.mkdir(exist_ok=True)
    today = datetime.now(ROME).date()
    try:
        years = archive_years(fetch(HOST + "/content/salastampa/it/bollettino.html"))
    except Exception as error:
        print(f"Archive index: {error}")
        try:
            years = json.loads((OUT / "index.json").read_text())["years"]
        except (OSError, ValueError, KeyError):
            years = list(range(2000, today.year + 1))
    months = [(y, m) for y in years for m in range(1, 13) if (y, m) <= (today.year, today.month)]
    if args.seed:
        months = [(today.year, today.month), (today.year, max(1, today.month - 1)), (today.year - 1, today.month)]
    jobs = [(y, m) for y, m in months if not (OUT / f"{y:04d}-{m:02d}.json").exists()
            or (y, m) == (today.year, today.month)
            or today.day <= 3 and (y, m) == (today.year if today.month > 1 else today.year - 1,
                                           today.month - 1 if today.month > 1 else 12)]
    jobs.sort(reverse=True)
    failures = []
    with ThreadPoolExecutor(max_workers=4) as pool:
        futures = {pool.submit(collect_month, y, m, today): (y, m) for y, m in jobs}
        for future in as_completed(futures):
            y, m = futures[future]
            try:
                key, count = future.result()
                print(f"{key}: {count} publications", flush=True)
            except Exception as error:
                failures.append(f"{y:04d}-{m:02d}")
                print(f"Bulletin {y}-{m:02d}: {error}", flush=True)
    available = sorted(p.stem for p in OUT.glob("????-??.json"))
    metadata = {"updated_at": datetime.now(timezone.utc).isoformat(), "years": years,
                "first_date": f"{min(years)}-01-01", "months": available, "failed_months": failures}
    (OUT / "index.json").write_text(json.dumps(metadata, ensure_ascii=False, separators=(",", ":")) + "\n")
    current = OUT / f"{today:%Y-%m}.json"
    if not current.exists():
        raise RuntimeError("Today's bulletin could not be collected")
    print(f"Saved {len(available)} monthly indexes; {len(failures)} failures", flush=True)


if __name__ == "__main__":
    main()
