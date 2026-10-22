"""Identify social accounts only from explicit publisher metadata or profile URLs."""
import re
import json
import base64
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from html.parser import HTMLParser
from urllib.parse import urlparse, unquote, quote


def profile_account(url, platform):
    try:
        parsed = urlparse(url)
    except ValueError:
        return None
    if parsed.scheme not in {"http", "https"}:
        return None
    host = (parsed.hostname or "").lower().removeprefix("www.").removeprefix("m.")
    parts = [unquote(p) for p in parsed.path.split("/") if p]
    if not parts:
        return None
    handle = None
    profile = None
    if platform == "X" and host in {"x.com", "twitter.com"}:
        if re.fullmatch(r'[A-Za-z0-9_]{1,15}', parts[0]) and parts[0].lower() not in {"home", "search", "intent", "share", "i", "explore", "settings", "hashtag"}:
            handle = parts[0]
            profile = "https://x.com/" + handle
    elif platform == "Instagram" and host == "instagram.com":
        if re.fullmatch(r'[A-Za-z0-9_.]{1,30}', parts[0]) and parts[0].lower() not in {"p", "reel", "reels", "stories", "explore", "accounts", "direct", "share", "about"}:
            handle = parts[0]
            profile = "https://www.instagram.com/" + handle + "/"
    elif platform == "TikTok" and host == "tiktok.com" and re.fullmatch(r'@[A-Za-z0-9_.]{1,30}', parts[0]):
        handle = parts[0][1:]
        profile = "https://www.tiktok.com/@" + handle
    elif platform == "YouTube" and host == "youtube.com" and re.fullmatch(r'@[\w.-]{3,40}', parts[0]):
        handle = parts[0][1:]
        profile = "https://www.youtube.com/@" + handle
    elif platform == "Facebook" and host == "facebook.com":
        if re.fullmatch(r'[A-Za-z0-9.]{3,80}', parts[0]) and not parts[0].isdigit() and parts[0].lower() not in {"watch", "reel", "reels", "share", "shares", "photo", "photos", "videos", "groups", "story.php", "permalink.php", "profile.php", "plugins", "events", "login", "sharer.php", "help"}:
            handle = parts[0]
            profile = "https://www.facebook.com/" + handle
    elif platform == "Reddit" and host in {"reddit.com", "old.reddit.com"} and len(parts) > 1 and parts[0] in {"user", "u"} and re.fullmatch(r'[A-Za-z0-9_-]{3,32}', parts[1]):
        handle = parts[1]
        profile = "https://www.reddit.com/user/" + handle + "/"
    return {"author": "@" + handle, "author_url": profile} if handle else None


def feed_account(item, platform, link):
    """Never infer the poster from mentions, hashtags, credits or caption prose."""
    if not platform:
        return {}
    source = item.find("source")
    source_url = source.get("url", "") if source is not None else ""
    account = profile_account(link, platform) or profile_account(source_url, platform)
    if account:
        return account
    for element in item:
        if element.tag not in {"author", "{http://purl.org/dc/elements/1.1/}creator"}:
            continue
        name = " ".join("".join(element.itertext()).split())
        if element.find("name") is not None:
            name = " ".join(element.findtext("name", "").split())
        if not 2 <= len(name) <= 100 or re.search(r'https?://|[^\s@]+@[^\s@]+\.[^\s@]+|[<>]', name):
            continue
        if name.casefold() in {"x", "twitter", "youtube", "instagram", "facebook", "tiktok", "reddit", "google news"}:
            continue
        return {"author": name, "author_url": ""}
    return {}


class PostLinks(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.canonical = []
        self.links = []

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if tag == 'link' and a.get('rel') == 'canonical':
            self.canonical.append(a.get('href', ''))
        if tag == 'meta' and a.get('property') == 'og:url':
            self.canonical.append(a.get('content', ''))
        if tag == 'a':
            self.links.append(a.get('href', ''))


def post_url(url, platform):
    """Require a post permalink, never a link to a suggested account."""
    parsed = urlparse(url)
    host = (parsed.hostname or '').lower().removeprefix('www.').removeprefix('m.')
    if parsed.scheme != 'https':
        return False
    path = parsed.path
    return bool(
        platform == 'X' and host in {'x.com', 'twitter.com'} and re.fullmatch(r'/[A-Za-z0-9_]{1,15}/status/\d+/?', path)
        or platform == 'YouTube' and host in {'youtube.com', 'youtu.be'} and (path == '/watch' and 'v=' in parsed.query or host == 'youtu.be' and len(path) > 2 or path.startswith('/shorts/'))
        or platform == 'TikTok' and host == 'tiktok.com' and re.fullmatch(r'/@[A-Za-z0-9_.]+/video/\d+/?', path)
        or platform == 'Instagram' and host == 'instagram.com' and re.fullmatch(r'/(?:p|reel)/[A-Za-z0-9_-]+/?', path)
        or platform == 'Facebook' and host == 'facebook.com' and re.fullmatch(r'/[A-Za-z0-9.]+/(?:posts|videos)/[A-Za-z0-9]+/?', path))


def resolve_account(item, fetch):
    platform, original = item.get('source', ''), item.get('url', '')
    resolved = original if post_url(original, platform) else ''
    if not resolved and urlparse(original).hostname == 'news.google.com':
        try:
            from googlenewsdecoder import gnewsdecoder
            result = gnewsdecoder(original, timeout=10)
            candidate = result.get('decoded_url', '') if result.get('success') else ''
            if post_url(candidate, platform):
                resolved = candidate
        except Exception:
            pass
        # Older RSS links contain the publisher URL; newer links need the landing page.
        token = original.split('/')[-1].split('?')[0]
        try:
            decoded = base64.urlsafe_b64decode(token + '=' * (-len(token) % 4)).decode('utf-8', errors='ignore')
            candidates = re.findall(r'https://[^\s\x00-\x20<>"\x7f]+', decoded)
            resolved = resolved or next((u for u in candidates if post_url(u, platform)), '')
        except (ValueError, UnicodeError):
            pass
        if not resolved:
            parser = PostLinks()
            parser.feed(fetch(original).decode('utf-8', errors='replace'))
            candidates = set(u for u in parser.canonical if post_url(u, platform))
            if not candidates:
                candidates = set(u for u in parser.links if post_url(u, platform))
            if len(candidates) == 1:
                resolved = candidates.pop()
    if not resolved:
        return {}
    account = profile_account(resolved, platform)
    endpoints = {'YouTube': 'https://www.youtube.com/oembed?format=json&url=',
                 'TikTok': 'https://www.tiktok.com/oembed?url=',
                 'X': 'https://publish.twitter.com/oembed?omit_script=true&url='}
    if platform in endpoints:
        try:
            metadata = json.loads(fetch(endpoints[platform] + quote(resolved, safe='')))
            name = ' '.join(str(metadata.get('author_name', '')).split())
            author_url = metadata.get('author_url', '')
            host = (urlparse(author_url).hostname or '').lower().removeprefix('www.')
            allowed = {'YouTube': {'youtube.com'}, 'TikTok': {'tiktok.com'}, 'X': {'twitter.com', 'x.com'}}[platform]
            if 2 <= len(name) <= 100 and host in allowed and urlparse(author_url).scheme == 'https':
                account = {'author': name, 'author_url': author_url}
        except Exception:
            pass
    return account or {}


def enrich_social_posts(items, fetch, limit=20):
    """Bound public metadata requests; failed lookups wait a day before retrying."""
    now = datetime.now(timezone.utc)
    known = {x['url']: {k: x[k] for k in ('author', 'author_url') if k in x}
             for x in items if x.get('kind') == 'social' and x.get('author')}
    checked = {x['url']: x['account_checked_at'] for x in items if x.get('account_checked_at')}
    jobs = {}
    for item in sorted(items, key=lambda x: x.get('published', ''), reverse=True):
        if item.get('kind') != 'social' or item['url'] in known or item['url'] in jobs:
            continue
        try:
            if now - datetime.fromisoformat(checked[item['url']]) < timedelta(days=1):
                continue
        except (KeyError, ValueError, TypeError):
            pass
        if len(jobs) < limit:
            jobs[item['url']] = item
    def lookup(pair):
        url, item = pair
        try:
            return url, resolve_account(item, fetch)
        except Exception:
            return url, {}
    with ThreadPoolExecutor(max_workers=4) as pool:
        for url, account in pool.map(lookup, jobs.items()):
            checked[url] = now.isoformat()
            if account:
                known[url] = account
    for item in items:
        if item.get('kind') != 'social':
            continue
        if item['url'] in known:
            item.update(known[item['url']])
        if item['url'] in checked:
            item['account_checked_at'] = checked[item['url']]
    print(f'Social accounts: {len(known)} identified, {len(jobs)} public metadata checks', flush=True)
