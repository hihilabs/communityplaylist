"""
management command: python manage.py import_bandcamp_artists

Discovers Portland-area artists on Bandcamp by scraping the public tag pages:
  - bandcamp.com/tag/portland
  - bandcamp.com/tag/portland-oregon
  - bandcamp.com/tag/pdx

Artists land as is_stub=True for admin review.  If a matching Artist record
already exists (by name), it just fills in missing fields (bandcamp URL, genres).

Also accepts a list of Bandcamp URLs you paste in manually:
    python manage.py import_bandcamp_artists --urls "https://someartist.bandcamp.com" ...

Usage:
    python manage.py import_bandcamp_artists
    python manage.py import_bandcamp_artists --tags portland pdx
    python manage.py import_bandcamp_artists --pages 3
    python manage.py import_bandcamp_artists --dry-run
    python manage.py import_bandcamp_artists --urls https://someone.bandcamp.com
"""
import re
import json
import time

import requests
from django.core.management.base import BaseCommand
from django.utils.text import slugify
from events.models import Artist, Genre

HEADERS = {
    'User-Agent': (
        'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) '
        'AppleWebKit/537.36 (KHTML, like Gecko) '
        'Chrome/124.0.0.0 Safari/537.36'
    ),
    'Accept-Language': 'en-US,en;q=0.9',
}

DEFAULT_TAGS = ['portland', 'portland-oregon', 'pdx']

# Regex to pull the tag page JSON blob (Bandcamp inlines it)
_TAG_DATA_RE  = re.compile(r'data-blob="([^"]+)"', re.S)
_NEXT_DATA_RE = re.compile(r'<script[^>]+id=["\']__NEXT_DATA__["\'][^>]*>(.*?)</script>', re.S)

# Bandcamp profile page patterns
_BC_JSON_RE = re.compile(r'data-band="([^"]+)"')
_BC_NAME_RE = re.compile(r'"name"\s*:\s*"([^"]+)"')


def _fetch_tag_page(session, tag, page=1):
    """Fetch a Bandcamp tag page and return a list of artist/release dicts."""
    url = f'https://bandcamp.com/tag/{tag}?tab=artists&page={page}'
    try:
        r = session.get(url, headers=HEADERS, timeout=15)
        r.raise_for_status()
        html = r.text
    except Exception as e:
        return [], f'HTTP error: {e}'

    # Try data-blob attribute (most reliable)
    m = _TAG_DATA_RE.search(html)
    if m:
        try:
            import html as html_lib
            blob = json.loads(html_lib.unescape(m.group(1)))
            items = (blob.get('hub', {}).get('tabs', [{}])[0].get('results')
                     or blob.get('results')
                     or [])
            return items, None
        except Exception:
            pass

    # Try __NEXT_DATA__
    m2 = _NEXT_DATA_RE.search(html)
    if m2:
        try:
            data  = json.loads(m2.group(1))
            items = (data.get('props', {}).get('pageProps', {}).get('artists')
                     or data.get('props', {}).get('pageProps', {}).get('results')
                     or [])
            return items, None
        except Exception:
            pass

    # Last resort: extract bandcamp.com subdomains from raw HTML
    subdomain_re = re.compile(r'https?://([\w-]+)\.bandcamp\.com(?:/[^"\'<>\s]*)?', re.I)
    names_re     = re.compile(r'"name"\s*:\s*"([^"]{2,80})"')
    subs  = subdomain_re.findall(html)
    names = names_re.findall(html)
    items = []
    for sub in set(subs):
        if sub in ('', 'f', 'store', 'support', 'merch'):
            continue
        items.append({'url_hints': [f'https://{sub}.bandcamp.com'], 'name': sub})
    return items, None


def _parse_artist(item):
    """
    Pull name, bandcamp URL, genre, and location from a raw tag result dict.
    Returns dict or None.
    """
    name = (item.get('name') or item.get('band_name') or item.get('title') or '').strip()
    if not name:
        return None

    # Bandcamp URL — prefer subdomain form
    bc_url = ''
    for key in ('bandcamp_url', 'url', 'item_url', 'page_url'):
        val = (item.get(key) or '').strip()
        if val and 'bandcamp.com' in val:
            bc_url = val.split('?')[0].rstrip('/')
            break
    if not bc_url:
        hints = item.get('url_hints') or []
        if hints:
            bc_url = hints[0].split('?')[0].rstrip('/')

    location = (item.get('location') or item.get('city') or '').strip()

    genre_names = []
    for key in ('genre', 'genres', 'tags'):
        val = item.get(key)
        if isinstance(val, str) and val:
            genre_names.append(val.title())
        elif isinstance(val, list):
            genre_names.extend(v.title() for v in val if isinstance(v, str) and v)

    return {
        'name':        name,
        'bandcamp':    bc_url,
        'location':    location,
        'genre_names': genre_names[:5],
    }


def _fetch_artist_page(session, bc_url):
    """Fetch a Bandcamp artist page and enrich name/genres if possible."""
    if not bc_url:
        return {}
    try:
        r = session.get(bc_url, headers=HEADERS, timeout=10)
        if not r.ok:
            return {}
        html = r.text
        m = _BC_JSON_RE.search(html)
        if m:
            import html as html_lib
            data = json.loads(html_lib.unescape(m.group(1)))
            return {
                'name':     (data.get('name') or '').strip(),
                'location': (data.get('city') or data.get('location') or '').strip(),
                'bio':      (data.get('bio') or '').strip()[:1000],
            }
    except Exception:
        pass
    return {}


class Command(BaseCommand):
    help = 'Discover Portland Bandcamp artists from tag pages and save as stubs'

    def add_arguments(self, parser):
        parser.add_argument('--tags',    nargs='+', default=DEFAULT_TAGS,
                            help='Bandcamp tags to search (default: portland portland-oregon pdx)')
        parser.add_argument('--pages',   type=int, default=2,
                            help='Pages per tag to fetch (default: 2)')
        parser.add_argument('--dry-run', action='store_true',
                            help='Print without saving')
        parser.add_argument('--urls',    nargs='*', default=[],
                            help='Paste specific Bandcamp artist URLs to import directly')
        parser.add_argument('--enrich',  action='store_true',
                            help='Fetch each artist page to get bio/location (slower)')

    def handle(self, *args, **options):
        tags     = options['tags']
        pages    = options['pages']
        dry_run  = options['dry_run']
        urls     = options['urls'] or []
        enrich   = options['enrich']

        session  = requests.Session()
        raw_pool = []
        seen_bc  = set()

        # ── Manual URL list ────────────────────────────────────────────────
        for url in urls:
            url = url.strip().rstrip('/')
            if 'bandcamp.com' not in url:
                self.stderr.write(f'  skip (not bandcamp): {url}')
                continue
            if url not in seen_bc:
                seen_bc.add(url)
                # Derive name from subdomain
                m = re.match(r'https?://([\w-]+)\.bandcamp\.com', url)
                name = m.group(1).replace('-', ' ').title() if m else url
                raw_pool.append({'name': name, 'bandcamp': url, 'location': '', 'genre_names': []})

        # ── Tag page discovery ────────────────────────────────────────────
        for tag in tags:
            self.stdout.write(f'\nScanning bandcamp.com/tag/{tag}…')
            for p in range(1, pages + 1):
                items, err = _fetch_tag_page(session, tag, page=p)
                if err:
                    self.stderr.write(f'  tag={tag} page={p} error: {err}')
                    break
                if not items:
                    break
                self.stdout.write(f'  page {p}: {len(items)} items')
                for item in items:
                    parsed = _parse_artist(item)
                    if not parsed:
                        continue
                    bc = parsed['bandcamp']
                    key = bc or parsed['name'].lower()
                    if key in seen_bc:
                        continue
                    seen_bc.add(key)
                    raw_pool.append(parsed)
                time.sleep(1.0)

        self.stdout.write(f'\n{len(raw_pool)} candidate artists')

        created = updated = skipped = errors = 0

        for idx, parsed in enumerate(raw_pool):
            name = parsed['name']
            if not name or len(name) < 2:
                skipped += 1
                continue

            if enrich and parsed['bandcamp']:
                if idx > 0 and idx % 5 == 0:
                    time.sleep(2)
                extra = _fetch_artist_page(session, parsed['bandcamp'])
                if extra.get('name'):
                    parsed['name'] = extra['name']
                    name = parsed['name']
                if extra.get('location'):
                    parsed['location'] = extra['location']

            if dry_run:
                self.stdout.write(
                    f'  [dry] {name[:50]}'
                    + (f'  | {parsed["bandcamp"]}' if parsed['bandcamp'] else '')
                    + (f'  | {parsed["location"]}' if parsed["location"] else '')
                )
                created += 1
                continue

            # Update existing artist or create stub
            existing = Artist.objects.filter(name__iexact=name).first()
            if existing:
                changed = False
                if parsed['bandcamp'] and not existing.bandcamp:
                    existing.bandcamp = parsed['bandcamp']
                    changed = True
                if changed:
                    existing.save(update_fields=['bandcamp'])
                    updated += 1
                    self.stdout.write(f'  ~ updated {name[:50]}')
                else:
                    skipped += 1
                continue

            # Check by Bandcamp URL
            if parsed['bandcamp'] and Artist.objects.filter(bandcamp=parsed['bandcamp']).exists():
                skipped += 1
                continue

            slug_base = slugify(name)[:90] or 'artist'
            slug = slug_base; n = 1
            while Artist.objects.filter(slug=slug).exists():
                slug = f'{slug_base}-{n}'; n += 1

            try:
                artist = Artist.objects.create(
                    name     = name[:200],
                    slug     = slug,
                    bandcamp = parsed['bandcamp'][:500] if parsed['bandcamp'] else '',
                    is_stub  = True,
                )
                for gname in parsed['genre_names']:
                    genre, _ = Genre.objects.get_or_create(name=gname)
                    artist.genres.add(genre)
                created += 1
                self.stdout.write(f'  + {name[:50]}')
            except Exception as e:
                self.stderr.write(f'  ERROR "{name[:40]}": {e}')
                errors += 1

        self.stdout.write(
            f'\nDone — created: {created}  updated: {updated}  '
            f'skipped: {skipped}  errors: {errors}'
        )
        if (created or updated) and not dry_run:
            self.stdout.write('Review at /admin/events/artist/?is_stub__exact=1')
