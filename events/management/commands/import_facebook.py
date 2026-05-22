"""
management command: python manage.py import_facebook

Scrapes public Facebook pages and groups for upcoming events.
Requires a cookies.txt file from a logged-in Facebook session — Facebook
blocks all unauthenticated scraping as of 2024.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
SETUP (one-time):
  1. Install the "Get cookies.txt LOCALLY" extension in Chrome/Firefox
  2. Log in to Facebook in your browser
  3. Click the extension icon on facebook.com → Export cookies → Netscape format
  4. Save the file to:
       /var/www/vhosts/communityplaylist.com/django/.fb_cookies.txt
     OR set FB_COOKIES_FILE=/path/to/cookies.txt in your .env
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

Events are geo-checked (Portland 60mi radius) and land as status=pending.
Feed it any Facebook page slug, group ID, or full URL you find.

Usage:
    # Run all saved PDX pages
    python manage.py import_facebook

    # Scrape specific pages/groups this run
    python manage.py import_facebook --pages holocene.pdx ravepdx
    python manage.py import_facebook --pages https://www.facebook.com/ProcessPDX/

    # Dry run
    python manage.py import_facebook --dry-run --pages holocene.pdx

    # Add pages to the persistent list for all future runs
    python manage.py import_facebook --add holocene.pdx ravepdx

    # Show saved page list
    python manage.py import_facebook --list
"""
import re
import json
import math
import time
import pytz
from datetime import datetime, timedelta
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand
from django.utils import timezone
from django.utils.text import slugify
from events.models import Event

PDX_TZ  = pytz.timezone('America/Los_Angeles')

# Portland metro bounding box (generous — covers Vancouver WA, Hillsboro, Oregon City)
PDX_BBOX = {
    'lat_min': 45.15, 'lat_max': 45.80,
    'lng_min': -122.95, 'lng_max': -122.20,
}
PDX_LAT = 45.5231
PDX_LNG = -122.6765
PDX_RADIUS_MILES = 60

# Persistent page list stored next to this file
PAGES_FILE   = Path(__file__).parent / 'facebook_pages.json'

# Default cookies path — override with FB_COOKIES_FILE env var or settings
DEFAULT_COOKIES = Path('/var/www/vhosts/communityplaylist.com/django/.fb_cookies.txt')

# Seed list of known Portland Facebook pages/groups
DEFAULT_PAGES = [
    # Venues
    'holocene.pdx',
    'ProcessPDX',
    'mississippistudiospdx',
    'theroselandtheater',
    'crystalballroompdx',
    'WonderBallroomPDX',
    'hawthornetheatrepdx',
    'McMenaminsEdgefield',
    # Promoters / collectives
    'ravepdx',
    'GoodlyPDX',
    'portlandundergroundmusic',
    # Community / event groups (groups need --group flag in facebook-scraper)
    'PDXraveevents',
]

# Portland relevance check for events without coordinates
PDX_TEXT_RE = re.compile(
    r'\b(portland|pdx|p\.?d\.?x|oregon|hillsboro|beaverton|gresham|'
    r'se\s+\w|sw\s+\w|ne\s+\w|nw\s+\w|burnside|hawthorne|mississippi|'
    r'division|alberta|belmont|clinton|sellwood|pearl|lloyd|'
    r'vancouver\s+wa|n\s+portland)\b',
    re.I
)


def _load_pages():
    if PAGES_FILE.exists():
        try:
            return json.loads(PAGES_FILE.read_text())
        except Exception:
            pass
    return list(DEFAULT_PAGES)


def _save_pages(pages):
    PAGES_FILE.write_text(json.dumps(sorted(set(pages)), indent=2))


def _haversine(lat1, lon1, lat2, lon2):
    R = 3958.8
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dp = math.radians(lat2 - lat1)
    dl = math.radians(lon2 - lon1)
    a  = math.sin(dp/2)**2 + math.cos(phi1)*math.cos(phi2)*math.sin(dl/2)**2
    return R * 2 * math.asin(math.sqrt(a))


def _in_pdx(lat, lon):
    """True if coordinates are within ~60 miles of Portland."""
    if lat is None or lon is None:
        return None   # unknown — let text filter decide
    return _haversine(float(lat), float(lon), PDX_LAT, PDX_LNG) <= PDX_RADIUS_MILES


def _is_pdx_relevant(event_dict):
    """
    Return True if a Facebook event dict is likely Portland-area.
    Checks coordinates first, then falls back to text in location/description/name.
    """
    lat = event_dict.get('latitude') or event_dict.get('lat')
    lon = event_dict.get('longitude') or event_dict.get('lng') or event_dict.get('lon')

    geo = _in_pdx(lat, lon)
    if geo is not None:
        return geo

    # Text fallback
    blob = ' '.join(str(event_dict.get(k, '')) for k in
                    ('location', 'location_name', 'description', 'name', 'title'))
    return bool(PDX_TEXT_RE.search(blob))


def _parse_fb_dt(ts_or_str):
    """Parse a Facebook event timestamp (int or ISO string) to PDX-aware datetime."""
    if not ts_or_str:
        return None
    try:
        if isinstance(ts_or_str, (int, float)):
            dt = datetime.utcfromtimestamp(float(ts_or_str))
            return PDX_TZ.localize(dt.replace(tzinfo=None))
        raw = str(ts_or_str).replace('Z', '+00:00')
        dt  = datetime.fromisoformat(raw)
        return dt.astimezone(PDX_TZ) if dt.tzinfo else PDX_TZ.localize(dt)
    except Exception:
        return None


def _slug_from_url(url_or_slug):
    """Extract page slug / ID from a full Facebook URL."""
    url_or_slug = url_or_slug.strip().rstrip('/')
    # Strip full URL down to page identifier
    m = re.search(
        r'facebook\.com/(?:pages/[^/]+/|groups/|events/)?([^/?#&]+)', url_or_slug
    )
    return m.group(1) if m else url_or_slug


def _resolve_cookies(cookies_arg):
    """
    Return a cookie path string, or None.
    Priority: --cookies arg → FB_COOKIES_FILE env → DEFAULT_COOKIES file.
    """
    import os
    if cookies_arg:
        return cookies_arg
    env = os.environ.get('FB_COOKIES_FILE', '')
    if env and Path(env).exists():
        return env
    if DEFAULT_COOKIES.exists():
        return str(DEFAULT_COOKIES)
    return None


def _scrape_page(page_id, max_events=30, cookies=None):
    """
    Fetch upcoming events from a Facebook page using facebook-scraper.
    Returns list of raw event dicts.
    Raises RuntimeError with a human-readable message on auth failures.
    """
    try:
        from facebook_scraper import get_page_info, get_posts, set_noscript
    except ImportError:
        raise RuntimeError('facebook-scraper not installed — run: pip install facebook-scraper lxml_html_clean')

    set_noscript(True)
    events = []
    kw = {'cookies': cookies} if cookies else {}

    # Pass 1: get_page_info — sometimes includes upcoming_events
    try:
        info = get_page_info(page_id, **kw)
        raw_events = info.get('upcoming_events') or info.get('events') or []
        for ev in raw_events[:max_events]:
            events.append(ev)
    except Exception as e:
        err = str(e)
        if 'login' in err.lower() or 'LoginRequired' in err:
            raise RuntimeError(
                f'Facebook requires login cookies for @{page_id}.\n'
                '  See command docstring for setup instructions.'
            )

    # Pass 2: scan recent posts for event cards
    if len(events) < max_events:
        try:
            for post in get_posts(page_id, pages=3,
                                  options={'posts_per_page': 20, 'allow_extra_requests': True},
                                  **kw):
                if post.get('is_event') or post.get('event'):
                    ev = post.get('event') or post
                    events.append(ev)
                if len(events) >= max_events:
                    break
        except Exception as e:
            err = str(e)
            if 'login' in err.lower() or 'LoginRequired' in err:
                raise RuntimeError(
                    f'Facebook requires login cookies for @{page_id}.\n'
                    '  See command docstring for setup instructions.'
                )

    return events


class Command(BaseCommand):
    help = 'Import upcoming Portland events from Facebook pages and groups'

    def add_arguments(self, parser):
        parser.add_argument('--pages',   nargs='*', default=[],
                            help='Facebook page slugs or URLs to scrape this run')
        parser.add_argument('--add',     nargs='*', default=[],
                            help='Add page slugs to the persistent list and exit')
        parser.add_argument('--list',    action='store_true',
                            help='Print the saved page list and exit')
        parser.add_argument('--dry-run', action='store_true',
                            help='Print without saving')
        parser.add_argument('--days',    type=int, default=60,
                            help='Skip events further than this many days out (default: 60)')
        parser.add_argument('--cookies', type=str, default='',
                            help='Path to Netscape-format cookies.txt for logged-in scraping')

    def handle(self, *args, **options):
        saved_pages = _load_pages()

        # --list
        if options['list']:
            self.stdout.write('Saved Facebook pages:')
            for p in sorted(saved_pages):
                self.stdout.write(f'  {p}')
            return

        # --add
        if options['add']:
            new = [_slug_from_url(u) for u in options['add']]
            merged = sorted(set(saved_pages) | set(new))
            _save_pages(merged)
            self.stdout.write(f'Added {new} → {len(merged)} pages saved.')
            return

        # Build run list: explicit --pages overrides saved list, else use saved
        run_pages = [_slug_from_url(u) for u in options['pages']] if options['pages'] else saved_pages
        dry_run   = options['dry_run']
        days      = options['days']
        cookies   = _resolve_cookies(options['cookies'] or '')

        if not cookies:
            self.stdout.write(self.style.WARNING(
                'No Facebook cookies file found.\n'
                '  Facebook requires login to scrape pages/groups.\n'
                '  See command docstring: python manage.py import_facebook --help\n'
                '  Continuing anyway — pages may fail with LoginRequired.\n'
            ))

        now    = timezone.now()
        cutoff = now + timedelta(days=days)

        self.stdout.write(f'Scraping {len(run_pages)} Facebook pages…')

        created = skipped = errors = 0

        for page_id in run_pages:
            self.stdout.write(f'\n  @{page_id}')
            try:
                raw_events = _scrape_page(page_id, cookies=cookies)
            except Exception as e:
                self.stderr.write(f'    scrape error: {e}')
                errors += 1
                time.sleep(2)
                continue

            self.stdout.write(f'    {len(raw_events)} events found')

            for ev in raw_events:
                # Normalise field names (facebook-scraper uses various keys)
                title = (
                    ev.get('name') or ev.get('title') or ev.get('header') or ''
                ).strip()
                if not title:
                    continue

                start_dt = _parse_fb_dt(
                    ev.get('start_timestamp') or ev.get('start_time') or
                    ev.get('start') or ev.get('date')
                )
                if not start_dt:
                    skipped += 1
                    continue
                if start_dt < now or start_dt > cutoff:
                    skipped += 1
                    continue

                end_dt = _parse_fb_dt(
                    ev.get('end_timestamp') or ev.get('end_time') or ev.get('end')
                )

                # Geo filter
                if not _is_pdx_relevant(ev):
                    self.stdout.write(f'    skip (not PDX): {title[:40]}')
                    skipped += 1
                    continue

                location = (
                    ev.get('location_name') or ev.get('location') or
                    ev.get('venue_name') or 'Portland, OR'
                ).strip()[:300]

                description = (ev.get('description') or ev.get('text') or '').strip()[:2000]
                ticket_url  = (ev.get('ticket_uri') or ev.get('url') or
                               ev.get('event_url') or '').strip()
                is_free     = bool(re.search(r'\bfree\b|\bno\s+cover\b', description, re.I))
                lat         = ev.get('latitude') or ev.get('lat')
                lon         = ev.get('longitude') or ev.get('lng')

                if dry_run:
                    self.stdout.write(
                        f'    [dry] {start_dt.strftime("%b %d %I:%M%p")}  {title[:50]}'
                        f'  @ {location[:30]}'
                    )
                    created += 1
                    continue

                exists = Event.objects.filter(
                    title__iexact=title,
                    start_date__date=start_dt.date(),
                ).exists()
                if exists:
                    skipped += 1
                    continue

                fb_url = ev.get('event_url') or ev.get('url') or ''
                if fb_url and Event.objects.filter(website=fb_url[:200]).exists():
                    skipped += 1
                    continue

                slug_base = slugify(f'{title}-{start_dt.strftime("%Y-%m-%d")}')[:90]
                slug = slug_base; n = 1
                while Event.objects.filter(slug=slug).exists():
                    slug = f'{slug_base}-{n}'; n += 1

                try:
                    Event.objects.create(
                        title        = title[:200],
                        slug         = slug,
                        description  = description or f'Event sourced from Facebook/@{page_id}',
                        location     = location,
                        start_date   = start_dt,
                        end_date     = end_dt,
                        website      = (ticket_url or fb_url)[:500],
                        is_free      = is_free,
                        status       = 'pending',
                        submitted_by = f'fb-{page_id}'[:100],
                        latitude     = float(lat) if lat else None,
                        longitude    = float(lon) if lon else None,
                    )
                    created += 1
                    self.stdout.write(f'    + {title[:55]}  [{start_dt.strftime("%b %d")}]')
                except Exception as e:
                    self.stderr.write(f'    ERROR "{title[:40]}": {e}')
                    errors += 1

            time.sleep(3)  # be polite between pages

        self.stdout.write(
            f'\nDone — created: {created}  skipped: {skipped}  errors: {errors}'
        )
        if created and not dry_run:
            self.stdout.write('Review at /admin/events/event/?status=pending')
