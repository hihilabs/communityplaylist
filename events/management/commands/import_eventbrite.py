"""
management command: python manage.py import_eventbrite

Pulls upcoming Portland-area events from Eventbrite.

Two modes:
  • API mode (preferred):   requires EVENTBRITE_API_KEY in settings/.env
                            Free key: https://www.eventbrite.com/platform/api
  • Scrape mode (fallback): parses __NEXT_DATA__ JSON from public search page,
                            no key required but less reliable

Events land as status=pending for admin review.

Usage:
    python manage.py import_eventbrite
    python manage.py import_eventbrite --days 14
    python manage.py import_eventbrite --dry-run
    python manage.py import_eventbrite --scrape   # force scrape mode
"""
import re
import json
import time
import pytz
import requests
from datetime import datetime, timedelta

from django.conf import settings
from django.core.management.base import BaseCommand
from django.utils import timezone
from django.utils.text import slugify
from events.models import Event

PDX_TZ   = pytz.timezone('America/Los_Angeles')
PDX_LAT  = 45.5051
PDX_LNG  = -122.6750

EB_API    = 'https://www.eventbriteapi.com/v3/events/search/'
EB_SEARCH = 'https://www.eventbrite.com/d/or--portland/all-events/?sort=date&page={page}'

HEADERS = {
    'User-Agent': (
        'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) '
        'AppleWebKit/537.36 (KHTML, like Gecko) '
        'Chrome/124.0.0.0 Safari/537.36'
    ),
    'Accept-Language': 'en-US,en;q=0.9',
}


def _parse_dt(iso_str):
    if not iso_str:
        return None
    try:
        raw = iso_str.replace('Z', '+00:00')
        dt  = datetime.fromisoformat(raw)
        if dt.tzinfo is None:
            return PDX_TZ.localize(dt)
        return dt.astimezone(PDX_TZ)
    except Exception:
        return None


# ── API mode ──────────────────────────────────────────────────────────────────

def _api_fetch(session, api_key, date_from, date_to, page=1):
    r = session.get(
        EB_API,
        headers={**HEADERS, 'Authorization': f'Bearer {api_key}'},
        params={
            'location.address':      'Portland, OR',
            'location.within':       '50mi',
            'start_date.range_start': date_from + 'T00:00:00Z',
            'start_date.range_end':   date_to   + 'T23:59:59Z',
            'expand':                'venue,organizer,ticket_availability',
            'page_size':             50,
            'page':                  page,
            'sort_by':               'date',
        },
        timeout=20,
    )
    r.raise_for_status()
    return r.json()


def _api_normalize(ev):
    """Map Eventbrite API event to CP flat dict."""
    title     = (ev.get('name', {}).get('text') or '').strip()
    desc      = (ev.get('description', {}).get('text') or '').strip()[:2000]
    start_str = (ev.get('start', {}).get('utc') or '').strip()
    end_str   = (ev.get('end',   {}).get('utc') or '').strip()
    url       = (ev.get('url') or '').strip()
    is_free   = bool(ev.get('is_free'))

    # Ticket availability
    ta = ev.get('ticket_availability') or {}
    price_info = ''
    if not is_free:
        lo = ta.get('minimum_ticket_price', {})
        if lo and lo.get('display'):
            price_info = lo['display']

    venue = ev.get('venue') or {}
    addr  = venue.get('address') or {}
    venue_name = (venue.get('name') or '').strip()
    city       = (addr.get('city') or 'Portland').strip()
    location   = f'{venue_name}, {city}' if venue_name else city or 'Portland, OR'
    lat = venue.get('latitude')
    lng = venue.get('longitude')

    logo   = ev.get('logo') or {}
    flyer  = (logo.get('original', {}).get('url') or logo.get('url') or '').strip()

    return {
        'title':      title,
        'start':      _parse_dt(start_str),
        'end':        _parse_dt(end_str),
        'location':   location[:300],
        'website':    url[:500],
        'description':desc,
        'flyer_url':  flyer[:500],
        'is_free':    is_free,
        'price_info': price_info[:100],
        'latitude':   float(lat) if lat else None,
        'longitude':  float(lng) if lng else None,
    }


# ── Scrape mode ───────────────────────────────────────────────────────────────

_NEXT_RE = re.compile(r'<script[^>]+id=["\']__NEXT_DATA__["\'][^>]*>(.*?)</script>', re.S)
_JSON_RE = re.compile(r'window\.__eventbrite_data__\s*=\s*(\{.*?\});', re.S)


def _scrape_fetch(session, page=1):
    url = EB_SEARCH.format(page=page)
    r   = session.get(url, headers=HEADERS, timeout=15)
    r.raise_for_status()
    html = r.text

    # Try __NEXT_DATA__ first
    m = _NEXT_RE.search(html)
    if m:
        try:
            data = json.loads(m.group(1))
            # Walk down to the event list — path varies by EB version
            props = data.get('props', {}).get('pageProps', {})
            # Try several known paths
            events = (props.get('events')
                      or props.get('eventSearch', {}).get('events', {}).get('results')
                      or props.get('search_data', {}).get('events', {}).get('results')
                      or [])
            if events:
                return events, data
        except Exception:
            pass

    # Try inline JSON blob
    m2 = _JSON_RE.search(html)
    if m2:
        try:
            data   = json.loads(m2.group(1))
            events = data.get('events') or []
            if events:
                return events, data
        except Exception:
            pass

    return [], {}


def _scrape_normalize(ev):
    """Map scraped Eventbrite event dict to CP flat dict."""
    title     = (ev.get('name') or ev.get('title') or '').strip()
    start_str = (ev.get('start_date') or ev.get('start', {}).get('utc') or '').strip()
    end_str   = (ev.get('end_date') or ev.get('end', {}).get('utc') or '').strip()
    url       = (ev.get('url') or ev.get('eventUrl') or '').strip()
    is_free   = bool(ev.get('is_free') or ev.get('isFree'))

    venue = ev.get('venue') or ev.get('primaryVenueLocation') or {}
    venue_name = (venue.get('name') or '').strip()
    city       = (venue.get('city') or venue.get('cityName') or 'Portland').strip()
    location   = f'{venue_name}, {city}' if venue_name else city or 'Portland, OR'
    lat = venue.get('latitude') or venue.get('lat')
    lng = venue.get('longitude') or venue.get('lng')

    logo  = ev.get('logo') or ev.get('image') or {}
    flyer = (logo.get('url') or logo.get('original', {}).get('url') or '').strip()
    if not flyer and isinstance(ev.get('image'), str):
        flyer = ev.get('image', '')

    desc = (ev.get('description') or ev.get('summary') or '').strip()[:2000]

    return {
        'title':      title,
        'start':      _parse_dt(start_str),
        'end':        _parse_dt(end_str),
        'location':   location[:300],
        'website':    url[:500],
        'description':desc,
        'flyer_url':  flyer[:500],
        'is_free':    is_free,
        'price_info': '',
        'latitude':   float(lat) if lat else None,
        'longitude':  float(lng) if lng else None,
    }


# ── Command ───────────────────────────────────────────────────────────────────

class Command(BaseCommand):
    help = 'Import upcoming Portland events from Eventbrite (API or scrape)'

    def add_arguments(self, parser):
        parser.add_argument('--days',    type=int, default=30,
                            help='Days ahead to fetch (default: 30)')
        parser.add_argument('--dry-run', action='store_true',
                            help='Print without saving')
        parser.add_argument('--scrape',  action='store_true',
                            help='Force scrape mode even if API key is set')

    def handle(self, *args, **options):
        days     = options['days']
        dry_run  = options['dry_run']
        force_scrape = options['scrape']

        now      = timezone.now()
        cutoff   = now + timedelta(days=days)
        date_from = now.strftime('%Y-%m-%d')
        date_to   = cutoff.strftime('%Y-%m-%d')

        api_key  = getattr(settings, 'EVENTBRITE_API_KEY', '')
        use_api  = bool(api_key) and not force_scrape

        session  = requests.Session()
        all_norm = []

        if use_api:
            self.stdout.write(f'Fetching Eventbrite Portland events via API ({date_from} → {date_to})…')
            page = 1
            while True:
                try:
                    data  = _api_fetch(session, api_key, date_from, date_to, page)
                except Exception as e:
                    self.stderr.write(f'  API error (page {page}): {e}')
                    break
                events = data.get('events') or []
                for ev in events:
                    try:
                        all_norm.append(_api_normalize(ev))
                    except Exception:
                        pass
                pagination = data.get('pagination') or {}
                if not pagination.get('has_more_items'):
                    break
                page += 1
                time.sleep(0.5)
        else:
            if not api_key:
                self.stdout.write(
                    'No EVENTBRITE_API_KEY in settings — using scrape mode.\n'
                    '  Get a free key: https://www.eventbrite.com/platform/api'
                )
            self.stdout.write(f'Fetching Eventbrite Portland events via scrape…')
            for p in range(1, 6):
                try:
                    raw_events, _ = _scrape_fetch(session, page=p)
                except Exception as e:
                    self.stderr.write(f'  Scrape error (page {p}): {e}')
                    break
                if not raw_events:
                    break
                for ev in raw_events:
                    try:
                        all_norm.append(_scrape_normalize(ev))
                    except Exception:
                        pass
                time.sleep(1.2)

        self.stdout.write(f'  {len(all_norm)} candidates')

        created = skipped = errors = 0

        for ev in all_norm:
            if not ev['title'] or not ev['start']:
                skipped += 1
                continue
            if ev['start'] > cutoff or ev['start'] < now:
                skipped += 1
                continue

            if dry_run:
                self.stdout.write(
                    f'  [dry] {ev["start"].strftime("%b %d %I:%M%p")}  '
                    f'{ev["title"][:50]}  @ {ev["location"][:30]}'
                    + ('  FREE' if ev['is_free'] else '')
                )
                created += 1
                continue

            exists_title = Event.objects.filter(
                title__iexact=ev['title'],
                start_date__date=ev['start'].date(),
            ).exists()
            exists_url = (ev['website'] and
                          Event.objects.filter(website=ev['website'][:200]).exists())
            if exists_title or exists_url:
                skipped += 1
                continue

            slug_base = slugify(f'{ev["title"]}-{ev["start"].strftime("%Y-%m-%d")}')[:90]
            slug = slug_base; n = 1
            while Event.objects.filter(slug=slug).exists():
                slug = f'{slug_base}-{n}'; n += 1

            try:
                Event.objects.create(
                    title        = ev['title'][:200],
                    slug         = slug,
                    description  = ev['description'] or f'Event at {ev["location"]}',
                    location     = ev['location'],
                    start_date   = ev['start'],
                    end_date     = ev['end'],
                    website      = ev['website'],
                    flyer_url    = ev['flyer_url'],
                    is_free      = ev['is_free'],
                    price_info   = ev['price_info'],
                    status       = 'pending',
                    submitted_by = 'eventbrite-import',
                    latitude     = ev['latitude'],
                    longitude    = ev['longitude'],
                )
                created += 1
                self.stdout.write(f'  + {ev["title"][:55]}  [{ev["start"].strftime("%b %d")}]')
            except Exception as e:
                self.stderr.write(f'  ERROR "{ev["title"][:40]}": {e}')
                errors += 1

        self.stdout.write(
            f'\nDone — created: {created}  skipped: {skipped}  errors: {errors}'
        )
        if created and not dry_run:
            self.stdout.write('Review at /admin/events/event/?status=pending')
