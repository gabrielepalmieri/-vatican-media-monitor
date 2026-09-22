#!/usr/bin/env python3
"""Raccoglie feed pubblici e genera il database statico della dashboard."""
from __future__ import annotations
import hashlib, html, json, re, ssl
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path
from urllib.parse import quote, urlparse
from urllib.request import Request, urlopen
from xml.etree import ElementTree as ET

ROOT = Path(__file__).resolve().parent
OUT = ROOT / "news.json"
MAX_ITEMS = 2000
RETENTION_DAYS = 7

EDITIONS = [
    ("Italia", "Italiano", "it", "IT", "IT:it"), ("Stati Uniti", "English", "en", "US", "US:en"),
    ("Regno Unito", "English", "en", "GB", "GB:en"), ("Francia", "Français", "fr", "FR", "FR:fr"),
    ("Germania", "Deutsch", "de", "DE", "DE:de"), ("Spagna", "Español", "es", "ES", "ES:es"),
    ("America Latina", "Español", "es-419", "MX", "MX:es-419"), ("Brasile", "Português", "pt-BR", "BR", "BR:pt-419"),
    ]
QUERIES = [
    '"Pope Leo XIV" OR "Papa Leone XIV" OR "Pape Léon XIV" OR "Papst Leo XIV" OR "Papa León XIV"',
    'Vatican OR "Holy See" OR Vaticano OR "Santa Sede" OR "Saint-Siège" OR Vatikan',
    '(Pope OR Vatican OR "Holy See") (peace OR war OR diplomacy OR migrants OR ecumenism OR abuse OR abuses OR safeguarding OR "sexual abuse" OR "child abuse" OR "protection of minors" OR finance)',
]
SOCIAL_QUERY = '("Pope Leo XIV" OR Vatican) (site:youtube.com OR site:x.com OR site:reddit.com OR site:tiktok.com OR site:instagram.com)'

# Testate interrogate anche con ricerche dedicate, per ridurre la dipendenza
# dall'ordinamento generale di Google News. La dashboard ne mostra l'esito.
PRIORITY_SOURCES = [
    ("Italia", "Corriere della Sera", ["corriere della sera", "corriere.it"], "corriere.it"),
    ("Italia", "la Repubblica", ["la repubblica", "repubblica.it"], "repubblica.it"),
    ("Italia", "La Stampa", ["la stampa", "lastampa.it"], "lastampa.it"),
    ("Italia", "Il Sole 24 Ore", ["il sole 24 ore", "ilsole24ore.com"], "ilsole24ore.com"),
    ("Italia", "Avvenire", ["avvenire", "avvenire.it"], "avvenire.it"),
    ("Francia", "Le Monde", ["le monde", "lemonde.fr"], "lemonde.fr"),
    ("Francia", "Le Figaro", ["le figaro", "lefigaro.fr"], "lefigaro.fr"),
    ("Francia", "Libération", ["libération", "liberation.fr"], "liberation.fr"),
    ("Francia", "La Croix", ["la croix", "la-croix.com"], "la-croix.com"),
    ("Francia", "France 24", ["france 24", "france24.com"], "france24.com"),
    ("Spagna", "El País", ["el país", "el pais", "elpais.com"], "elpais.com"),
    ("Spagna", "El Mundo", ["el mundo", "elmundo.es"], "elmundo.es"),
    ("Spagna", "ABC", ["abc.es", "abc"], "abc.es"),
    ("Spagna", "La Vanguardia", ["la vanguardia", "lavanguardia.com"], "lavanguardia.com"),
    ("Spagna", "El Confidencial", ["el confidencial", "elconfidencial.com"], "elconfidencial.com"),
    ("Regno Unito", "BBC", ["bbc", "bbc.com", "bbc.co.uk"], "bbc.co.uk"),
    ("Regno Unito", "The Guardian", ["the guardian", "theguardian.com"], "theguardian.com"),
    ("Regno Unito", "The Telegraph", ["the telegraph", "telegraph.co.uk"], "telegraph.co.uk"),
    ("Regno Unito", "The Independent", ["the independent", "independent.co.uk"], "independent.co.uk"),
    ("Regno Unito", "The Times", ["the times", "thetimes.com"], "thetimes.com"),
]

AGENCY_SOURCES = [
    ("Italia", "ANSA", ["ansa", "ansa.it"], "ansa.it"),
    ("Italia", "AgenSIR", ["agensir", "agensir.it", "agenzia sir"], "agensir.it"),
    ("Regno Unito", "Reuters", ["reuters", "reuters.com"], "reuters.com"),
    ("Stati Uniti", "Associated Press", ["associated press", "ap news", "apnews.com"], "apnews.com"),
    ("Francia", "AFP", ["agence france-presse", "afp", "afp.com"], "afp.com"),
    ("Germania", "dpa", ["deutsche presse-agentur", "dpa", "dpa.com"], "dpa.com"),
    ("Spagna", "EFE", ["agencia efe", "efe", "efe.com"], "efe.com"),
    ("Regno Unito", "PA Media", ["pa media", "press association"], "pa.media"),
    ("Stati Uniti", "Bloomberg", ["bloomberg", "bloomberg.com"], "bloomberg.com"),
    ("Stati Uniti", "Xinhua", ["xinhua", "news.cn"], "news.cn"),
    ("Stati Uniti", "Kyodo News", ["kyodo news", "kyodonews.net"], "kyodonews.net"),
    ("Stati Uniti", "Anadolu Agency", ["anadolu agency", "aa.com.tr"], "aa.com.tr"),
    ("Stati Uniti", "TASS", ["tass", "tass.com"], "tass.com"),
]

TOPICS = {
    "Papa Leone XIV": ["leo xiv", "leone xiv", "léon xiv", "león xiv"],
    "Pace e diplomazia": ["peace", "pace", "paix", "paz", "krieg", "war", "guerra", "diplom"],
    "Viaggi apostolici": ["travel", "trip", "visit", "voyage", "reise", "viaje", "viaggio"],
    "Abusi e tutela": ["abuse", "abus", "safeguard", "tutela", "protección"],
    "Finanze": ["finance", "financial", "bank", "ior", "finanz", "econom"],
    "Nomine e Curia": ["appoint", "nomina", "appointment", "curia", "bishop", "vescovo", "évêque"],
    "Ecumenismo e dialogo": ["ecumen", "interfaith", "dialogue", "dialogo", "œcumé"],
    "Società e diritti": ["migrant", "migration", "climate", "rights", "diritti", "migranti"],
    "Santa Sede": ["holy see", "santa sede", "saint-siège", "heiliger stuhl", "curia romana", "roman curia", "vatican secretary of state", "segreteria di stato"],
}

def clean(s: str) -> str:
    return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", "", s or ""))).strip()

def valid_title(title: str) -> bool:
    """Scarta pagine-sezione, firme e semplici etichette restituite come notizie."""
    words=re.findall(r"[a-zà-ÿ0-9]+",title.casefold())
    subjects=("pope","papa","pape","papst","vatican","vaticano","leone","leo","léon","león","holy see","santa sede")
    if title.startswith("©") or title.casefold() in {"vatican media","ultime news","your details","style video"}: return False
    return len(words)>3 or any(subject in title.casefold() for subject in subjects)

def topic_for(title: str) -> str:
    low = title.lower()
    for topic, words in TOPICS.items():
        if any(w in low for w in words): return topic
    return "Attualità"

def published(value: str) -> str:
    try:
        d = parsedate_to_datetime(value)
        if d.tzinfo is None: d = d.replace(tzinfo=timezone.utc)
        return d.astimezone(timezone.utc).isoformat()
    except Exception:
        return datetime.now(timezone.utc).isoformat()

def source_from(item, title: str, link: str) -> str:
    source = item.find("source")
    if source is not None and clean(source.text or ""): return clean(source.text or "")
    if " - " in title: return title.rsplit(" - ", 1)[-1]
    return urlparse(link).netloc.replace("www.", "") or "Fonte web"

def fetch(url: str) -> bytes:
    req = Request(url, headers={"User-Agent": "VaticanMediaMonitor/1.0 (+GitHub Actions)", "Accept": "application/rss+xml, application/xml, text/xml"})
    ctx = ssl.create_default_context()
    with urlopen(req, timeout=15, context=ctx) as r: return r.read()

def parse_feed(url: str, country: str, language: str, kind: str) -> list[dict]:
    out=[]
    try: root=ET.fromstring(fetch(url))
    except Exception as exc:
        print(f"Feed non disponibile: {url[:90]} ({exc})"); return out
    for item in root.findall(".//item")[:100]:
        title=clean(item.findtext("title", "")); link=clean(item.findtext("link", ""))
        if not title or not link or not valid_title(title): continue
        source=source_from(item,title,link)
        display_title=title[:-len(source)-3].strip() if title.endswith(" - "+source) else title
        if not valid_title(display_title): continue
        uid=hashlib.sha1((display_title.lower()+source.lower()).encode()).hexdigest()[:16]
        out.append({"id":uid,"title":display_title,"url":link,"source":source,"country":country,"language":language,"published":published(item.findtext("pubDate", "")),"topic":topic_for(display_title),"kind":kind,"cluster_size":1})
    return out

def feed_url(query: str, hl: str, gl: str, ceid: str) -> str:
    return f"https://news.google.com/rss/search?q={quote(query)}&hl={hl}&gl={gl}&ceid={ceid}"

def source_queries(country: str) -> list[str]:
    """Una ricerca per fonte evita che poche testate dominino una query unica."""
    subjects='(Pope OR Papa OR Pape OR Papst OR Vatican OR Vaticano OR "Holy See" OR "Santa Sede" OR "Saint-Siège") when:7d'
    return [f'{subjects} (site:{domain} OR source:"{name}")'
            for item_country, name, _, domain in PRIORITY_SOURCES + AGENCY_SOURCES
            if item_country == country]

def source_matches(source: str, aliases: list[str]) -> bool:
    value=source.casefold()
    return any(alias.casefold() in value for alias in aliases)

def coverage_for(items: list[dict]) -> list[dict]:
    coverage=[]
    for sources, group in ((PRIORITY_SOURCES,"Testata"),(AGENCY_SOURCES,"Agenzia")):
        for country, name, aliases, _ in sources:
            matches=[x for x in items if source_matches(x["source"],aliases)]
            coverage.append({
                "country":country,
                "source":name,
                "group":group,
                "count":len(matches),
                "last_seen":max((x["published"] for x in matches),default=None),
                "item_ids":[x["id"] for x in sorted(matches,key=lambda item:item["published"],reverse=True)],
            })
    return coverage

def balanced_selection(items: list[dict]) -> list[dict]:
    """Riserva spazio a ogni fonte monitorata e limita quelle dominanti."""
    configured=PRIORITY_SOURCES + AGENCY_SOURCES
    def configured_name(item: dict) -> str | None:
        for _, name, aliases, _ in configured:
            if source_matches(item["source"],aliases): return name
        return None
    selected=[]; selected_ids=set(); counts={}
    for _, name, aliases, _ in configured:
        for item in items:
            marker=(item["id"],item["source"])
            if marker not in selected_ids and source_matches(item["source"],aliases):
                selected.append(item); selected_ids.add(marker); counts[name]=counts.get(name,0)+1
                if counts[name]>=5: break
    for item in items:
        if len(selected)>=MAX_ITEMS: break
        marker=(item["id"],item["source"])
        if marker in selected_ids: continue
        name=configured_name(item)
        if name and counts.get(name,0)>=60: continue
        selected.append(item); selected_ids.add(marker)
        if name: counts[name]=counts.get(name,0)+1
    return sorted(selected,key=lambda x:x["published"],reverse=True)

def cluster(items: list[dict]) -> None:
    stop={"the","and","for","with","from","that","this","pope","papa","pape","papst","vatican","vaticano","santa","sede","holy","see","leone","leo","xiv","del","della","delle","degli","per","con","dans","pour","avec","und","der","die","das","von","los","las","una","uno"}
    groups=[]
    for x in items:
        words={w for w in re.findall(r"[a-zà-ÿ0-9]+",x["title"].casefold()) if len(w)>3 and w not in stop}
        best=None; best_score=0
        for group in groups:
            union=words | group["words"]
            score=len(words & group["words"])/len(union) if union else 0
            if score>best_score: best, best_score=group, score
        if best is not None and best_score>=0.34 and len(words & best["words"])>=2:
            best["items"].append(x); best["words"] |= words
        else:
            groups.append({"words":words,"items":[x]})
    for group in groups:
        sources=sorted({x["source"] for x in group["items"]})
        cluster_id=min(x["id"] for x in group["items"])
        for x in group["items"]:
            x["cluster_id"]=cluster_id
            x["cluster_size"]=len(sources)
            x["cluster_sources"]=sources

def main() -> None:
    items=[]
    jobs=[]
    for country, language, hl, gl, ceid in EDITIONS:
        for query in QUERIES: jobs.append((feed_url(query,hl,gl,ceid),country,language,"news"))
        jobs.append((feed_url(SOCIAL_QUERY,hl,gl,ceid),country,language,"social"))
        for dedicated in source_queries(country):
            jobs.append((feed_url(dedicated,hl,gl,ceid),country,language,"news"))
    with ThreadPoolExecutor(max_workers=8) as pool:
        futures=[pool.submit(parse_feed,*job) for job in jobs]
        for future in as_completed(futures): items += future.result()
    # Conserva gli articoli recenti già trovati: i feed di ricerca cambiano
    # ordine e possono smettere di mostrare un articolo dopo poche ore.
    if OUT.exists():
        try:
            previous=json.loads(OUT.read_text(encoding="utf-8"))
            cutoff=datetime.now(timezone.utc)-timedelta(days=RETENTION_DAYS)
            for item in previous.get("items",[]):
                if (isinstance(item,dict) and item.get("title") and item.get("source")
                    and datetime.fromisoformat(item["published"].replace("Z","+00:00"))>=cutoff):
                    items.append(item)
        except (OSError, ValueError, KeyError, TypeError) as exc:
            print(f"Archivio precedente non utilizzabile: {exc}")
    unique={}
    for x in items:
        key=(re.sub(r"\W+","",x["title"].lower())[:160],x["source"].casefold())
        if key not in unique or x["published"]>unique[key]["published"]: unique[key]=x
    ordered=sorted(unique.values(),key=lambda x:x["published"],reverse=True)
    result=balanced_selection(ordered)
    cluster(result)
    OUT.write_text(json.dumps({"updated_at":datetime.now(timezone.utc).isoformat(),"items":result,"source_coverage":coverage_for(result)},ensure_ascii=False,indent=2),encoding="utf-8")
    print(f"Salvati {len(result)} contenuti in {OUT}")

if __name__ == "__main__": main()
