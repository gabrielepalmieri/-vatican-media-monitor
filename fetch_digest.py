#!/usr/bin/env python3
"""Prepare a short daily edition before 07:00 Europe/Rome, using public feeds."""
import hashlib
import html
import json
import re
import unicodedata
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, time, timedelta, timezone
from email.utils import parsedate_to_datetime
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import urlparse
from urllib.request import Request, urlopen
from xml.etree import ElementTree as ET
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parent
ROME = ZoneInfo('Europe/Rome')
OUT = ROOT / 'digest.json'
SECTIONS = ('Attualità', 'Vaticano', 'Società')
FEEDS = (
    ('ANSA', 'Italiano', 'https://www.ansa.it/sito/notizie/topnews/topnews_rss.xml'),
    ('la Repubblica', 'Italiano', 'https://www.repubblica.it/rss/homepage/rss2.0.xml'),
    ('Vatican News', 'Italiano', 'https://www.vaticannews.va/it.rss.xml'),
    ('BBC News', 'English', 'https://feeds.bbci.co.uk/news/world/rss.xml'),
)


def clean(value):
    return re.sub(r'\s+', ' ', html.unescape(re.sub(r'<[^>]*>', ' ', value or ''))).strip()


def normalized(value):
    value = re.sub(r'\bpap[àá]\b', 'genitore', value.casefold())
    return ''.join(c for c in unicodedata.normalize('NFKD', value) if not unicodedata.combining(c))


def parse_date(value):
    if not value:
        return None
    try:
        date = datetime.fromisoformat(value.replace('Z', '+00:00'))
    except ValueError:
        try:
            date = parsedate_to_datetime(value)
        except (ValueError, TypeError):
            return None
    return date.astimezone(timezone.utc) if date and date.tzinfo else None


def section_for(item):
    title = normalized(item.get('title', ''))
    if item.get('kind') == 'social':
        return None
    if re.search(r'\b(?:vatican\w*|vatikan\w*|holy see|santa sede|pontific\w*|pope|papst|pape|prevost|leone xiv|leo xiv|leon xiv|(?:il|del|al|el|do) papa|papa (?:leone|leon|francesco)|cardinal\w*|conclave|angelus|rupnik)\b', title):
        return 'Vaticano'
    if re.search(r'\b(?:calcio|serie a|champions|europa league|formula 1|motogp|tennis|juventus|inter milan|sinner|belen|gossip|oroscopo|lotto|superenalotto|black friday|sconti|pagell\w*|highlights|football|premier league)\b', title):
        return None
    if re.search(r'\b(?:scuol\w*|student\w*|istruzione|universit\w*|sanita|salute|ospedal\w*|medic\w*|pover\w*|migrant\w*|immigra\w*|rifugiat\w*|diritt\w*|clima\w*|ambien\w*|famigli\w*|giovan\w*|bambin\w*|disabili\w*|volontar\w*|solidar\w*|lavor\w*|pension\w*|violenza sulle donne|femminicid\w*|health|school\w*|education|poverty|refugee\w*|climate|children|rights|homeless\w*)\b', title):
        return 'Società'
    if re.search(r'\b(?:governo|parlament\w*|ministr\w*|premier|president\w*|elezion\w*|voto|manovra|econom\w*|pil|inflazione|guerra|pace|tregua|attacc\w*|ucrain\w*|russia|putin|zelensk\w*|trump|gaza|israel\w*|hamas|libano|iran|cina|vertice|diplom\w*|europa|unione europea|onu|nato|ceasefire|war|election\w*|government|minister|politic\w*|ukraine|china|summit)\b', title):
        return 'Attualità'
    return None


def read_feed(config):
    source, language, url = config
    try:
        req = Request(url, headers={'User-Agent': 'VaticanMediaMonitor/1.0', 'Accept': 'application/rss+xml,application/xml'})
        with urlopen(req, timeout=12) as response:
            root = ET.fromstring(response.read(3_000_000))
        items = []
        for entry in root.findall('.//item')[:80]:
            title, link = clean(entry.findtext('title')), clean(entry.findtext('link'))
            published = parse_date(entry.findtext('pubDate'))
            if not title or urlparse(link).scheme not in {'http', 'https'} or not published:
                continue
            description = clean(entry.findtext('description'))
            if normalized(description) == normalized(title) or 'cookie' in description.casefold():
                description = ''
            if len(description) > 240:
                description = description[:237].rsplit(' ', 1)[0] + '…'
            items.append({'id': hashlib.sha1(link.encode()).hexdigest()[:16], 'title': title, 'url': link, 'source': source,
                          'language': language, 'published': published.isoformat(), 'kind': 'news', 'summary': description,
                          'summary_origin': 'feed' if description else ''})
        return items, {'source': source, 'ok': bool(items)}
    except Exception as error:
        print(f'Digest feed {source}: {error}', flush=True)
        return [], {'source': source, 'ok': False}


STOP = set('the and for with from that this pope papa leone leo xiv vaticano vatican della delle degli dello nel nella nelle sul sulla sulle per con una uno che del dei gli il lo la le di da a e i in un al'.split())


def words(title):
    return {w for w in re.findall(r'[a-z0-9]+', normalized(title)) if len(w) > 3 and w not in STOP}


class Description(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.value = ''

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if tag == 'meta' and (a.get('property') or a.get('name') or '').lower() in {'og:description', 'description'} and not self.value:
            self.value = clean(a.get('content', ''))


def add_excerpt(item):
    if item.get('summary') or urlparse(item['url']).hostname == 'news.google.com':
        return
    try:
        req = Request(item['url'], headers={'User-Agent': 'VaticanMediaMonitor/1.0'})
        with urlopen(req, timeout=8) as response:
            page = response.read(1_000_000).decode('utf-8', errors='replace')
        parser = Description()
        parser.feed(page)
        value = parser.value
        if len(value) < 45 or normalized(value) == normalized(item['title']) or re.search(r'abbonati|cookie|subscribe|javascript', value, re.I):
            return
        item['summary'] = value if len(value) <= 240 else value[:237].rsplit(' ', 1)[0]+'…'
        item['summary_origin'] = 'publisher_metadata'
    except Exception:
        pass


def select_sections(items, cutoff):
    groups = {name: [] for name in SECTIONS}
    seen_urls, candidates = set(), []
    for item in items:
        date = parse_date(item.get('published'))
        section = section_for(item)
        if not section or not date or not cutoff-timedelta(hours=24) <= date <= cutoff:
            continue
        if not item.get('url') or not item.get('source'):
            continue
        link = item.get('article_url') or item['url']
        if urlparse(link).scheme not in {'http', 'https'}:
            continue
        candidates.append({**item, 'url': link, 'section': section, 'topic': section, '_date': date})

    def score(item):
        age = (cutoff-item['_date']).total_seconds()/3600
        italian = item.get('language') == 'Italiano' or item.get('source') == 'TGcom24'
        preferred = bool(re.search(r'ansa|reuters|associated press|bbc|avvenire|corriere della sera|repubblica|vatican news|adnkronos|messaggero|tgcom', item['source'], re.I))
        repeated = min(int(item.get('cluster_size', 1)), 6)
        regional = (urlparse(item['url']).hostname or '').endswith('.repubblica.it') and (urlparse(item['url']).hostname or '') != 'www.repubblica.it'
        return (-3 if regional else 0) + (8 if italian else 0) + (4 if preferred else 0) + (1 if item.get('summary') else 0) + repeated - age/4

    source_counts = {name: {} for name in SECTIONS}
    candidates.sort(key=score, reverse=True)
    for source_cap in (1, 2, 3):
        for item in candidates:
            section = item['section']
            bucket = groups[section]
            if len(bucket) >= 3 or item['url'] in seen_urls:
                continue
            if source_counts[section].get(item['source'], 0) >= source_cap:
                continue
            current_words = words(item['title'])
            duplicate = False
            for old in [x for group in groups.values() for x in group]:
                old_words = words(old['title'])
                overlap = len(current_words & old_words)
                same_leader = any(name in current_words and name in old_words for name in {'mattarella','meloni','trump','putin','zelensky','netanyahu'})
                if normalized(item['title']) == normalized(old['title']) or (item.get('cluster_id') and item.get('cluster_id') == old.get('cluster_id')) or (overlap >= 3 and overlap/max(1, min(len(current_words), len(old_words))) >= .55) or same_leader:
                    duplicate = True
                    break
            if duplicate:
                continue
            bucket.append({k: item[k] for k in ('id','title','url','source','published','language','author','summary','summary_origin','section','topic','cluster_id') if k in item})
            seen_urls.add(item['url'])
            source_counts[section][item['source']] = source_counts[section].get(item['source'], 0)+1
    return [{'title': name, 'items': groups[name]} for name in SECTIONS]


def edition_date(now):
    local = now.astimezone(ROME)
    return local.date() if local.time() >= time(6,40) else local.date()-timedelta(days=1)


def main(now=None):
    now = now or datetime.now(timezone.utc)
    target = edition_date(now)
    try:
        data = json.loads(OUT.read_text(encoding='utf-8'))
    except (OSError, ValueError):
        data = {'editions': []}
    if any(e.get('date') == target.isoformat() for e in data['editions']):
        print(f'Digest {target}: edition already prepared', flush=True)
        return
    available = datetime.combine(target, time(7), tzinfo=ROME)
    cutoff = min(now, available.astimezone(timezone.utc))
    items, feed_status = [], []
    for filename in ('news.json', 'breaking.json'):
        try:
            document = json.loads((ROOT/filename).read_text(encoding='utf-8'))
            items.extend(document.get('items', []))
        except (OSError, ValueError):
            pass
    with ThreadPoolExecutor(max_workers=4) as pool:
        for fresh, status in pool.map(read_feed, FEEDS):
            items = fresh + items
            feed_status.append(status)
    sections = select_sections(items, cutoff)
    if not any(section['items'] for section in sections):
        raise RuntimeError('No recent articles: previous editions retained')
    with ThreadPoolExecutor(max_workers=4) as pool:
        list(pool.map(add_excerpt, [item for section in sections for item in section['items']]))
    edition = {'date': target.isoformat(), 'available_at': available.isoformat(), 'prepared_at': now.isoformat(),
               'coverage_from': (cutoff-timedelta(hours=24)).isoformat(), 'coverage_to': cutoff.isoformat(),
               'sections': sections, 'feeds': feed_status}
    data['editions'] = sorted([e for e in data['editions'] if e['date'] != target.isoformat()]+[edition], key=lambda e:e['date'], reverse=True)[:3]
    OUT.write_text(json.dumps(data, ensure_ascii=False, indent=2)+'\n', encoding='utf-8')
    print(f'Digest {target}: {sum(len(s["items"]) for s in sections)} articles', flush=True)


if __name__ == '__main__':
    main()
