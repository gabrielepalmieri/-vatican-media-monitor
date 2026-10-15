"""Read public author listings without downloading full article text."""
from datetime import datetime, timedelta, timezone
from hashlib import sha1
from html.parser import HTMLParser
import re
from urllib.parse import urljoin, urlparse

AUTHOR_SOURCES = [
    ("Francesco Capozza", "Il Tempo", "https://www.iltempo.it/autore/francesco-capozza/"),
    ("Nico Spuntoni", "Il Giornale", "https://www.ilgiornale.it/autore/nico-spuntoni/"),
]


class AuthorListing(HTMLParser):
    """Only dated result cards inside the named author's listing."""
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.depth = 0
        self.card = None
        self.cards = []
        self.heading = None
        self.title_depth = None
        self.author_depth = None
        self.page_author = ""
        self.void = {"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "param", "source", "track", "wbr"}

    def handle_starttag(self, tag, attrs):
        if tag in self.void:
            return
        self.depth += 1
        a = dict(attrs)
        if tag == "h1":
            self.heading = self.depth
        if "b-results-list" in a.get("class", "").split() and self.card is None:
            self.card = {"depth": self.depth, "title": "", "url": "", "published": "", "author": "", "context": ""}
        if self.card is None:
            return
        if tag == "h2":
            self.title_depth = self.depth
        if tag == "a" and self.title_depth:
            self.card["url"] = a.get("href", "")
        if tag == "a" and "/autore/" in a.get("href", ""):
            self.author_depth = self.depth
        if tag == "time":
            self.card["published"] = a.get("datetime", "")

    def handle_endtag(self, tag):
        if tag in self.void:
            return
        if self.card and self.depth == self.card["depth"]:
            self.cards.append(self.card)
            self.card = None
        if self.depth == self.title_depth:
            self.title_depth = None
        if self.depth == self.author_depth:
            self.author_depth = None
        if self.depth == self.heading:
            self.heading = None
        self.depth = max(0, self.depth - 1)

    def handle_data(self, value):
        if self.heading:
            self.page_author += value
        if self.card:
            self.card["context"] += " " + value
            if self.title_depth:
                self.card["title"] += value
            if self.author_depth:
                self.card["author"] += value


def parse_author_page(page, config, topic_for, valid_title, retention_days=7, now=None):
    author, source, listing_url = config
    parser = AuthorListing()
    parser.feed(page)
    if " ".join(parser.page_author.split()).casefold() != author.casefold() or not parser.cards:
        raise ValueError("Author listing unavailable or layout changed")
    now = now or datetime.now(timezone.utc)
    host = urlparse(listing_url).hostname
    output, seen = [], set()
    relevant = re.compile(r"\b(?:pap[ae]|pope|pontific\w*|vatican\w*|santa sede|holy see|chiesa|cattolic\w*|curia|cardinal\w*|vescov\w*|monsignor\w*|conclave|prevost|bergoglio|ratzinger|leone xiv|rupnik|safeguarding)\b", re.I)
    for card in parser.cards:
        title = " ".join(card["title"].split())
        url = urljoin(listing_url, card["url"])
        if not card["url"] or urlparse(url).hostname != host or not valid_title(title):
            continue
        # Where individual bylines are present they must confirm the listing.
        if card["author"].strip() and " ".join(card["author"].split()).casefold() != author.casefold():
            continue
        try:
            published = datetime.fromisoformat(card["published"].replace("Z", "+00:00"))
            if published.tzinfo is None or not now - timedelta(days=retention_days) <= published <= now:
                continue
        except ValueError:
            continue
        if url in seen or not relevant.search(card["context"]):
            continue
        seen.add(url)
        output.append({"id": sha1((title.lower()+source.lower()).encode()).hexdigest()[:16],
                       "title": title, "url": url, "source": source, "author": author,
                       "author_url": listing_url, "country": "Italia", "language": "Italiano",
                       "published": published.isoformat(), "topic": topic_for(title),
                       "kind": "news", "cluster_size": 1, "origin": "direct"})
    return output


def fetch_author_source(config, fetch, topic_for, valid_title, retention_days=7):
    try:
        page = fetch(config[2]).decode("utf-8")
        items = parse_author_page(page, config, topic_for, valid_title, retention_days)
        print(f"Author {config[0]}: {len(items)} recent relevant articles", flush=True)
        return items
    except Exception as error:
        print(f"Author {config[0]} unavailable: {error}", flush=True)
        return []
