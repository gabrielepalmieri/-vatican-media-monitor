#!/usr/bin/env python3
"""Aggiorna il flusso rapido delle notizie da feed RSS pubblici."""
import hashlib
import html
import json
import re
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import urlparse
from urllib.request import Request, urlopen
from xml.etree import ElementTree as ET
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parent
OUT = ROOT / "breaking.json"
FEEDS = {
    "BBC News": "https://feeds.bbci.co.uk/news/world/rss.xml",
}
TGCOM_PAGE = "https://www.tgcom24.mediaset.it/ultimissima/oraxora.shtml"
MAX_AGE = timedelta(hours=36)
ROME = ZoneInfo("Europe/Rome")


class TGcomParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.in_list = False
        self.link = None
        self.field = None
        self.records = []

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if attrs.get("id") == "itemlistcontainer":
            self.in_list = True
        if not self.in_list:
            return
        if tag == "a" and self.link is None:
            self.link = {"url": attrs.get("href", ""), "time": "", "title": ""}
        if self.link and attrs.get("data-testid") == "breaking-news-item-time":
            self.field = "time"
        if self.link and attrs.get("data-testid") == "breaking-news-item-title":
            self.field = "title"

    def handle_data(self, data):
        if self.link and self.field:
            self.link[self.field] += data

    def handle_endtag(self, tag):
        if tag in ("span", "h5"):
            self.field = None
        if tag == "a" and self.link:
            if self.link["time"] and self.link["title"]:
                self.records.append(self.link)
            self.link = None


def collect_tgcom(now):
    request = Request(TGCOM_PAGE, headers={"User-Agent": "Mozilla/5.0"})
    with urlopen(request, timeout=20) as response:
        page = response.read(2_000_000).decode("utf-8", "replace")
    match = re.search(r"(\d{1,2})\s+(\w+)\s+(\d{4})\s*\|\s*Ora per ora", page, re.I)
    months = "gennaio febbraio marzo aprile maggio giugno luglio agosto settembre ottobre novembre dicembre".split()
    if not match or match.group(2).lower() not in months:
        raise ValueError("data della pagina non riconosciuta")
    day = datetime(int(match.group(3)), months.index(match.group(2).lower()) + 1, int(match.group(1)), tzinfo=ROME)
    parser = TGcomParser()
    parser.feed(page)
    found, previous_time = [], None
    for record in parser.records:
        if not re.fullmatch(r"\d{2}:\d{2}", record["time"].strip()):
            continue
        hour, minute = map(int, record["time"].strip().split(":"))
        if hour > 23 or minute > 59:
            continue
        clock = hour * 60 + minute
        if previous_time is not None and clock > previous_time:
            day -= timedelta(days=1)
        previous_time = clock
        date = day.replace(hour=hour, minute=minute).astimezone(timezone.utc)
        link = record["url"]
        if not now - MAX_AGE <= date <= now + timedelta(minutes=10) or urlparse(link).netloc != "www.tgcom24.mediaset.it":
            continue
        found.append({"id": hashlib.sha256(("TGcom24" + link + date.isoformat()).encode()).hexdigest()[:20], "source": "TGcom24", "title": html.unescape(record["title"].strip()), "url": link, "published": date.isoformat()})
    return found


def collect(source, url, now):
    request = Request(url, headers={"User-Agent": "VaticanMediaMonitor/1.0 (+https://github.com/gabrielepalmieri/-vatican-media-monitor)", "Accept": "application/rss+xml, application/xml, text/xml"})
    with urlopen(request, timeout=20) as response:
        root = ET.fromstring(response.read(2_000_000))
    found = []
    for entry in root.findall("./channel/item"):
        title = html.unescape(" ".join((entry.findtext("title") or "").split()))
        link = (entry.findtext("link") or "").strip()
        stamp = entry.findtext("pubDate")
        try:
            date = parsedate_to_datetime(stamp).astimezone(timezone.utc)
        except (TypeError, ValueError):
            continue
        if not title or urlparse(link).scheme not in ("http", "https") or not now - MAX_AGE <= date <= now + timedelta(minutes=10):
            continue
        found.append({"id": hashlib.sha256((source + link).encode()).hexdigest()[:20], "source": source, "title": title, "url": link, "published": date.isoformat()})
    return found


def main():
    now = datetime.now(timezone.utc)
    old = json.loads(OUT.read_text()) if OUT.exists() else {}
    previous = old.get("items", [])
    items, status = [], {}
    for source, url in {"TGcom24": TGCOM_PAGE, **FEEDS}.items():
        try:
            fresh = collect_tgcom(now) if source == "TGcom24" else collect(source, url, now)
            if not fresh:
                raise ValueError("feed vuoto o privo di notizie recenti")
            items.extend(fresh)
            status[source] = {"ok": True, "checked_at": now.isoformat()}
        except Exception as exc:
            print(f"{source}: {exc}")
            items.extend(x for x in previous if x.get("source") == source and x.get("published", "") >= (now - MAX_AGE).isoformat())
            status[source] = {"ok": False, "checked_at": now.isoformat()}
    if not any(x["ok"] for x in status.values()) and not previous:
        raise RuntimeError("Nessun feed disponibile; il file non viene sostituito")
    unique = {x["id"]: x for x in items}
    data = {"updated_at": now.isoformat(), "sources": status, "items": sorted(unique.values(), key=lambda x: x["published"], reverse=True)[:120]}
    OUT.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n")
    print(f"Breaking news: {len(data['items'])} titoli")


if __name__ == "__main__":
    main()
