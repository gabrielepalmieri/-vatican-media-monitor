"""Match selected journalists only against explicit article bylines."""
import html
import json
import re
import unicodedata
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import urlparse, urljoin
from urllib.request import Request, urlopen

ROSTER = json.loads(Path(__file__).with_name('vaticanists.json').read_text(encoding='utf-8'))
BYLINE_CACHE = Path(__file__).with_name('vaticanist_bylines.json')


def normalized(value):
    value = unicodedata.normalize('NFKD', html.unescape(str(value))).casefold()
    return ''.join(c for c in value if c.isalnum() and not unicodedata.combining(c))


ALIASES = {}
for person in ROSTER:
    for alias in person['aliases']:
        ALIASES.setdefault(normalized(alias), set()).add(person['id'])


def match_bylines(names):
    found = set()
    for name in names:
        # Match whole bylines, never occurrences in article text or descriptions.
        parts = [name] + re.split(r'\s+(?:and|e|y|et|und|&)\s+|[;,|]', name)
        for part in parts:
            part = re.sub(r'^\s*(?:by|di|por|par|von)\s+', '', part, flags=re.I)
            matches = ALIASES.get(normalized(part), set())
            if len(matches) == 1:
                found.update(matches)
    return [p for p in ROSTER if p['id'] in found]


def set_matches(item, names):
    people = match_bylines(names)
    if people:
        item['vaticanist_ids'] = [p['id'] for p in people]
        item['vaticanist_names'] = [p['name'] for p in people]
    return people


class ArticleMetadata(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.names, self.blocks, self.canonical = [], [], []
        self.script = None

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if tag == 'meta' and (a.get('name') or a.get('property') or '').casefold() in {
            'author', 'parsely-author', 'sailthru.author', 'article:author_name', 'dc.creator', 'dcterms.creator'
        }:
            name = a.get('content', '').strip()
            if name and not name.startswith(('http:', 'https:')):
                self.names.append(name)
        if tag == 'link' and 'canonical' in a.get('rel', '').split():
            self.canonical.append(a.get('href', ''))
        if tag == 'script' and a.get('type', '').casefold() == 'application/ld+json':
            self.script = ''

    def handle_data(self, value):
        if self.script is not None:
            self.script += value

    def handle_endtag(self, tag):
        if tag == 'script' and self.script is not None:
            try:
                self.blocks.append(json.loads(self.script))
            except (ValueError, TypeError):
                pass
            self.script = None


def article_bylines(page, url):
    parser = ArticleMetadata()
    parser.feed(page)
    articles = []

    def walk(node):
        if isinstance(node, list):
            for value in node:
                walk(value)
        elif isinstance(node, dict):
            types = node.get('@type', [])
            if isinstance(types, str):
                types = [types]
            if any(str(t).split('/')[-1] in {'Article', 'NewsArticle', 'ReportageNewsArticle', 'AnalysisNewsArticle', 'BlogPosting'} for t in types):
                articles.append(node)
            for key, value in node.items():
                if key not in {'author', 'publisher'}:
                    walk(value)

    for block in parser.blocks:
        walk(block)

    def location(value):
        p = urlparse(urljoin(url, value))
        return ((p.hostname or '').removeprefix('www.'), p.path.rstrip('/'))

    accepted = {location(url)} | {location(u) for u in parser.canonical if u}
    names = parser.names[:]
    for article in articles:
        link = article.get('url') or article.get('mainEntityOfPage')
        if isinstance(link, dict):
            link = link.get('@id') or link.get('url')
        # Do not attribute recommended articles' authors to the current page.
        if link and (not isinstance(link, str) or location(link) not in accepted):
            continue
        if not link and len(articles) != 1:
            continue
        authors = article.get('author', [])
        if not isinstance(authors, list):
            authors = [authors]
        for author in authors:
            name = author.get('name', '') if isinstance(author, dict) else author
            if isinstance(name, str) and name:
                names.append(name)
    return list(dict.fromkeys(names))


def fetch_article(url):
    request = Request(url, headers={'User-Agent': 'VaticanMediaMonitor/1.0', 'Accept': 'text/html'})
    with urlopen(request, timeout=8) as response:
        return response.read(2_000_000).decode('utf-8', errors='replace'), response.geturl()


def resolve_byline(item):
    try:
        url = item.get('article_url') or item['url']
        if urlparse(url).hostname == 'news.google.com':
            from googlenewsdecoder import gnewsdecoder
            result = gnewsdecoder(url, timeout=6)
            if not result.get('success'):
                return {}
            url = result.get('decoded_url', '')
        parsed = urlparse(url)
        if parsed.scheme not in {'http', 'https'} or not parsed.hostname or parsed.hostname == 'news.google.com':
            return {}
        page, resolved = fetch_article(url)
        names = article_bylines(page, resolved)
        return {'author': ', '.join(names), 'article_url': resolved, 'author_verified': True} if names else {}
    except Exception:
        return {}


def enrich_vaticanists(items, limit=48, now=None):
    now = now or datetime.now(timezone.utc)
    # Reuse confirmed metadata and failed checks across duplicate search results.
    try:
        known = json.loads(BYLINE_CACHE.read_text(encoding='utf-8'))
    except (OSError, ValueError):
        known = {}
    fields = ('author', 'article_url', 'author_verified', 'byline_checked_at')
    for item in items:
        if item.get('kind') == 'news' and item.get('author_verified'):
            known[item['url']] = {k: item[k] for k in fields if k in item}
    candidates, seen = [], set()
    for item in items:
        if item.get('kind') != 'news':
            continue
        if item['url'] in known:
            item.update(known[item['url']])
        item.pop('vaticanist_ids', None)
        item.pop('vaticanist_names', None)
        if item.get('author'):
            set_matches(item, [item['author']])
            continue
        checked = item.get('byline_checked_at')
        if checked:
            try:
                if now - datetime.fromisoformat(checked) < timedelta(days=2):
                    continue
            except ValueError:
                pass
        if item['url'] not in seen:
            candidates.append(item)
            seen.add(item['url'])
    # Dedicated author searches and direct publisher URLs are checked first.
    candidates.sort(key=lambda x: (not x.get('author_search', False), urlparse(x['url']).hostname == 'news.google.com', x.get('byline_checked_at', ''), -datetime.fromisoformat(x['published']).timestamp()))
    batch = candidates[:limit]
    with ThreadPoolExecutor(max_workers=6) as pool:
        for item, result in zip(batch, pool.map(resolve_byline, batch)):
            result['byline_checked_at'] = now.isoformat()
            known[item['url']] = result
    for item in items:
        if item.get('kind') == 'news' and item['url'] in known:
            item.update(known[item['url']])
            if item.get('author'):
                set_matches(item, [item['author']])
    active_urls = {item['url'] for item in items if item.get('kind') == 'news'}
    BYLINE_CACHE.write_text(json.dumps({url: value for url, value in known.items() if url in active_urls}, ensure_ascii=False, indent=2)+'\n', encoding='utf-8')
    print(f"Vaticanisti: {len(batch)} bylines checked; {sum(bool(x.get('vaticanist_ids')) for x in items)} articles matched", flush=True)


def author_searches(now=None):
    """Rotate compact author searches; never treat a search match as a byline."""
    now = now or datetime.now(timezone.utc)
    groups = [ROSTER[i:i+5] for i in range(0, len(ROSTER), 5)]
    slot = int(now.timestamp() // 600)
    selected = [groups[(slot*8+i) % len(groups)] for i in range(8)]
    subjects = '(Pope OR Papa OR Vatican OR Vaticano OR "Holy See" OR "Santa Sede" OR Rupnik)'
    for group in selected:
        names = ' OR '.join('"'+p['aliases'][-1]+'"' for p in group)
        for edition in [('Stati Uniti', 'English', 'en', 'US', 'US:en'), ('Italia', 'Italiano', 'it', 'IT', 'IT:it')]:
            yield f'({names}) {subjects} when:7d', edition
