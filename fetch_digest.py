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
SECTIONS = ('Attualità', 'Internazionale', 'Vaticano', 'Chiesa', 'Società', 'Cultura e idee')
FORMAT_VERSION = 2
ARTICLES_PER_SECTION = 5
PUBLISHERS = {
    'ANSA': ('ansa','agenzia ansa','ansa.it'),
    'Corriere della Sera': ('corriere della sera','corriere.it'),
    'la Repubblica': ('la repubblica','repubblica.it'),
    'La Stampa': ('la stampa','lastampa.it'),
    'Il Sole 24 Ore': ('il sole 24 ore','ilsole24ore.com'),
    'Avvenire': ('avvenire','avvenire.it'),
    'Il Messaggero': ('il messaggero','ilmessaggero.it'),
    'Il Giornale': ('il giornale','ilgiornale.it'),
    'Il Tempo': ('il tempo','iltempo.it'),
    'Adnkronos': ('adnkronos','adnkronos.com'),
    'AgenSIR': ('agensir','agensir.it','sir','agenzia sir'),
    'Vatican News': ('vatican news','vaticannews.va','radio vaticana'),
    'Famiglia Cristiana': ('famiglia cristiana','famigliacristiana.it'),
    'Reuters': ('reuters','reuters.com'),
    'Associated Press': ('associated press','ap news','apnews.com','ap'),
    'AFP': ('afp','agence france-presse'),
    'BBC News': ('bbc news','bbc','bbc.com','bbc.co.uk'),
    'The Guardian': ('the guardian','theguardian.com'),
    'The New York Times': ('the new york times','nytimes.com'),
    'The Washington Post': ('the washington post','washingtonpost.com'),
    'Financial Times': ('financial times','ft.com'),
    'La Croix': ('la croix','la croix international','la-croix.com'),
    'I.MEDIA': ('i.media','imedia.news'),
    'OSV News': ('osv news','our sunday visitor'),
    'The Pillar': ('the pillar','pillarcatholic.com'),
    'TGcom24': ('tgcom24',),
}

def publisher_name(source):
    value = (source or '').casefold().strip()
    for name, aliases in PUBLISHERS.items():
        if value in aliases: return name
    return None
FEEDS = (
    ('ANSA', 'Italiano', 'https://www.ansa.it/sito/notizie/topnews/topnews_rss.xml'),
    ('la Repubblica', 'Italiano', 'https://www.repubblica.it/rss/homepage/rss2.0.xml'),
    ('Vatican News', 'Italiano', 'https://www.vaticannews.va/it.rss.xml'),
    ('Corriere della Sera', 'Italiano', 'https://www.corriere.it/rss/homepage.xml'),
    ('La Stampa', 'Italiano', 'https://www.lastampa.it/rss/copertina.xml'),
    ('ANSA', 'Italiano', 'https://www.ansa.it/sito/notizie/mondo/mondo_rss.xml', 'Internazionale'),
    ('ANSA', 'Italiano', 'https://www.ansa.it/sito/notizie/cultura/cultura_rss.xml', 'Cultura e idee'),
    ('AgenSIR', 'Italiano', 'https://www.agensir.it/feed/', 'Chiesa'),
    ('BBC News', 'English', 'https://feeds.bbci.co.uk/news/world/rss.xml', 'Internazionale'),
    ('BBC News', 'English', 'https://feeds.bbci.co.uk/news/entertainment_and_arts/rss.xml', 'Cultura e idee'),
    ('The Guardian', 'English', 'https://www.theguardian.com/world/rss', 'Internazionale'),
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
    hint = item.get('digest_hint')
    if re.search(r'\b(?:oroscopo|superenalotto|black friday|sconti|calciomercato|gossip|highlights|serie a|champions league|formula 1|motogp|tennis|basket|pallacanestro|pallavolo|rugby|juve|juventus|sinner|football|premier league)\b', title):
        return None
    if hint == 'Cultura e idee' or re.search(r'\b(?:editorial\w*|filosof\w*|teolog\w*|saggio|saggi|letteratura|scrittor\w*|romanzo|romanzi|mostra|museo|musei|poesia|cultura|culturale|culturali|cinema|teatro|libri|libro|arte|artista|artisti|orchestra|essay|literature|museum\w*|philosoph\w*)\b', title):
        return 'Cultura e idee'
    if re.search(r'\b(?:vatican\w*|vatikan\w*|holy see|santa sede|pontific\w*|pope|papst|pape|prevost|leone xiv|leo xiv|leon xiv|(?:il|del|al|el|do) papa|papa (?:leone|leon|francesco)|conclave|angelus|curia|parolin)\b', title):
        return 'Vaticano'
    if hint == 'Chiesa' or re.search(r'\b(?:chiesa|chiese|church\w*|catholic\w*|cattolic\w*|vescov\w*|bishop\w*|dioces\w*|parroc\w*|sacerdot\w*|cardinal\w*|missionar\w*|sinod\w*|sinodale|religios\w*|caritas|ecumen\w*|cristian\w*|christian\w*|cei|rupnik)\b', title):
        return 'Chiesa'
    if re.search(r'\b(?:guerra|tregua|ucrain\w*|russia|putin|zelensk\w*|trump|gaza|israel\w*|hamas|libano|iran|teheran|kuwait|cina|shenzhen|siria|sudan|congo|libia|yemen|cuba|venezuela|argentina|peru|uruguay|brasile|colombia|messico|diplom\w*|unione europea|onu|nato|ceasefire|war|ukraine|china|russia|germany|france|united states|united nations|g7|g20)\b', title):
        return 'Internazionale'
    if re.search(r'\b(?:scuol\w*|student\w*|istruzione|universit\w*|sanita|salute|ospedal\w*|medic\w*|pover\w*|migrant\w*|immigra\w*|rifugiat\w*|diritt\w*|clima\w*|ambien\w*|famiglie|anzian\w*|giovan\w*|bambin\w*|disabili\w*|volontar\w*|solidar\w*|lavor\w*|pension\w*|violenza sulle donne|femminicid\w*|health|school\w*|education|poverty|refugee\w*|climate|children|rights|homeless\w*)\b', title):
        return 'Società'
    if hint == 'Internazionale':
        return 'Internazionale'
    if re.search(r'\b(?:governo|parlament\w*|ministr\w*|premier|president\w*|elezion\w*|voto|manovra|econom\w*|pil|inflazione|giustizia|magistrat\w*|meloni|salvini|mattarella|politic\w*|election\w*|government|minister)\b', title):
        return 'Attualità'
    return None


def read_feed(config):
    source, language, url, *hints = config
    try:
        req = Request(url, headers={'User-Agent': 'VaticanMediaMonitor/1.0', 'Accept': 'application/rss+xml,application/xml'})
        with urlopen(req, timeout=12) as response:
            root = ET.fromstring(response.read(3_000_000))
        items = []
        for entry in root.findall('.//item')[:150]:
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
                          'summary_origin': 'feed' if description else '', 'digest_hint': hints[0] if hints else ''})
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
        publisher = publisher_name(item.get('source'))
        if not publisher or not section or not date or not cutoff-timedelta(hours=24) <= date <= cutoff:
            continue
        if not item.get('url') or not item.get('source'):
            continue
        link = item.get('article_url') or item['url']
        if urlparse(link).scheme not in {'http', 'https'}:
            continue
        candidates.append({**item, 'source':publisher, 'url': link, 'section': section, 'topic': section, '_date': date})

    def score(item):
        age = (cutoff-item['_date']).total_seconds()/3600
        italian = item.get('language') == 'Italiano' or item.get('source') == 'TGcom24'
        preferred = bool(re.search(r'ansa|reuters|associated press|bbc|avvenire|corriere della sera|repubblica|vatican news|adnkronos|messaggero|tgcom', item['source'], re.I))
        repeated = min(int(item.get('cluster_size', 1)), 6)
        regional = (urlparse(item['url']).hostname or '').endswith('.repubblica.it') and (urlparse(item['url']).hostname or '') != 'www.repubblica.it'
        return (-3 if regional else 0) + (8 if italian else 0) + (4 if preferred else 0) + (1 if item.get('summary') else 0) + repeated - age/4

    source_counts = {name: {} for name in SECTIONS}
    candidates.sort(key=score, reverse=True)
    international = next((x for x in candidates if x['section']=='Internazionale' and x['source'] in {'Reuters','Associated Press','BBC News','The Guardian','Financial Times','The New York Times','The Washington Post'}),None)
    if international:
        candidates.remove(international)
        candidates.insert(0,international)
    for source_cap in (1, 2, 3):
        for item in candidates:
            section = item['section']
            bucket = groups[section]
            if len(bucket) >= ARTICLES_PER_SECTION or item['url'] in seen_urls:
                continue
            if source_counts[section].get(item['source'], 0) >= source_cap:
                continue
            current_words = words(item['title'])
            duplicate = False
            for old in [x for group in groups.values() for x in group]:
                old_words = words(old['title'])
                overlap = len(current_words & old_words)
                if normalized(item['title']) == normalized(old['title']) or (item.get('cluster_id') and item.get('cluster_id') == old.get('cluster_id')) or (overlap >= 3 and overlap/max(1, min(len(current_words), len(old_words))) >= .55):
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
    if any(e.get('date') == target.isoformat() and e.get('format_version') == FORMAT_VERSION and e.get('pdf_url') and (ROOT/e['pdf_url']).is_file() for e in data['editions']):
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
    with ThreadPoolExecutor(max_workers=6) as pool:
        for fresh, status in pool.map(read_feed, FEEDS):
            items = fresh + items
            feed_status.append(status)
    sections = select_sections(items, cutoff)
    if not any(section['items'] for section in sections):
        raise RuntimeError('No recent articles: previous editions retained')
    with ThreadPoolExecutor(max_workers=6) as pool:
        list(pool.map(add_excerpt, [item for section in sections for item in section['items']]))
    edition = {'format_version':FORMAT_VERSION, 'date': target.isoformat(), 'available_at': available.isoformat(), 'prepared_at': now.isoformat(),
               'coverage_from': (cutoff-timedelta(hours=24)).isoformat(), 'coverage_to': cutoff.isoformat(),
               'sections': sections, 'feeds': feed_status}
    from render_digest import write_pdf
    write_pdf(edition, ROOT)
    data['editions'] = sorted([e for e in data['editions'] if e['date'] != target.isoformat()]+[edition], key=lambda e:e['date'], reverse=True)[:3]
    OUT.write_text(json.dumps(data, ensure_ascii=False, indent=2)+'\n', encoding='utf-8')
    print(f'Digest {target}: {sum(len(s["items"]) for s in sections)} articles', flush=True)


if __name__ == '__main__':
    main()
