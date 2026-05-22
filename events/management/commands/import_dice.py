"""
management command: python manage.py import_dice

Pulls upcoming Portland-area events from Dice.fm via their public
widget/search API (no auth required for basic event browsing).

Events land as status=pending for admin review.

Usage:
    python manage.py import_dice
    python manage.py import_dice --days 30
    python manage.py import_dice --dry-run
"""
import time
import json
import pytz
import requests
from datetime import datetime, timedelta

from django.core.management.base import BaseCommand
from django.utils import timezone
from django.utils.text import slugify
from events.models import Event

PDX_TZ   = pytz.timezone('America/Los_Angeles')
PDX_LAT  = 45.5051
PDX_LNG  = -122.6750

# Dice public event search — geo + keyword approaches
DICE_SEARCH_URL = 'https://api.dice.fm/v1/search'
DICE_EVENT_URL  = 'https://api.dice.fm/v1/events'

HEADERS = {
    'User-Agent': (
        'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) '
        'AppleWebKit/537.36 (KHTML, like Gecko) '
        'Chrome/124.0.0.0 Safari/537.36'
    ),
    'Accept':          'application/json',
    'Accept-Language': 'en-US,en;q=0.9',
    'Origin':          'https://dice.fm',
    'Referer':         'https://dice.fm/',
    'x-api-key':       'dice-web-app',   # public key embedded in dice.fm JS
}


def _parse_dt(iso_str):
    """Parse a Dice ISO datetime string into a PDX-aware datetime."""
    if not iso_str:
        return None
    try:
        raw = iso_str.replace('Z', '+00:00')
        dt  = datetime.fromisoformat(raw)
        return dt.astimezone(PDX_TZ)
    except Exception:
        return None


def _fetch_page(session, offset, limit=20):
    """
    Dice geo-search for events near Portland.
    Falls back to a keyword search on 'portland' if geo returns nothing.
    """
    params = {
        'types':                'event,linkout',
        'coming_up':            'true',
        'page[size]':           limit,
        'page[number]':         offset // limit + 1,
        'filter[location]':     'Portland, OR',
        'sort':                 'date',
    }
    r = session.get(DICE_EVENT_URL, params=params, headers=HEADERS, timeout=15)
    r.raise_for_status()
    return r.json()


def _fetch_search(session, page=1, per_page=40):
    """Keyword search fallback — broader catch for PDX-tagged events."""
    params = {
        'q':         'portland',
        'types':     'event',
        'page':      page,
        'per_page':  per_page,
        'coming_up': 'true',
    }
    r = session.get(DICE_SEARCH_URL, params=params, headers=HEADERS, timeout=15)
    r.raise_for_status()
    return r.json()


def _normalize(ev_raw):
    """
    Map a raw Dice event dict to a flat dict of CP fields.
    Handles both the /events and /search response shapes.
    """
    # /events shape
    title      = (ev_raw.get('name') or ev_raw.get('title') or '').strip()
    ticket_url = (ev_raw.get('url') or ev_raw.get('event_link') or '').strip()
    start_str  = (ev_raw.get('date') or ev_raw.get('datetime') or
                  ev_raw.get('start_date') or '').strip()
    end_str    = (ev_raw.get('end_date') or '').strip()

    venue = ev_raw.get('venue') or {}
    if isinstance(venue, str):
        venue_name = venue
        city = 'Portland'
    else:
        venue_name = (venue.get('name') or '').strip()
        city       = (venue.get('city') or venue.get('location') or 'Portland').strip()

    location = f"{venue_name}, {city}" if venue_name else city or 'Portland, OR'

    desc = (ev_raw.get('description') or ev_raw.get('lineup_details') or '').strip()

    # Image
    images = ev_raw.get('images') or ev_raw.get('image') or []
    flyer  = ''
    if isinstance(images, list) and images:
        img = images[0]
        flyer = img.get('url', '') if isinstance(img, dict) else str(img)
    elif isinstance(images, str):
        flyer = images
    else:
        flyer = ev_raw.get('image_url') or ev_raw.get('flyer_url') or ''

    is_free     = bool(ev_raw.get('free') or ev_raw.get('is_free'))
    price_info  = str(ev_raw.get('price') or ev_raw.get('min_price') or '').strip()

    lat = (ev_raw.get('lat') or (venue.get('lat') if isinstance(venue, dict) else None))
    lng = (ev_raw.get('lng') or (venue.get('lng') if isinstance(venue, dict) else None))

    return {
        'title':      title,
        'start':      _parse_dt(start_str),
        'end':        _parse_dt(end_str) if end_str else None,
        'location':   location[:300],
        'website':    ticket_url[:500],
        'description':desc[:2000],
        'flyer_url':  flyer[:500] if flyer else '',
        'is_free':    is_free,
        'price_info': price_info[:100],
        'latitude':   float(lat) if lat else None,
        'longitude':  float(lng) if lng else None,
    }


class Command(BaseCommand):
    help = 'Import upcoming Portland events from Dice.fm'

    def add_arguments(self, parser):
        parser.add_argument('--days',    type=int, default=30,
                            help='Days ahead to fetch (default: 30)')
        parser.add_argument('--dry-run', action='store_true',
                            help='Print without saving')

    def handle(self, *args, **options):
        days    = options['days']
        dry_run = options['dry_run']

        cutoff  = timezone.now() + timedelta(days=days)
        session = requests.Session()

        all_events = []
        seen_ids   = set()

        # ── Pass 1: location-filtered event listing ────────────────────────
        self.stdout.write('Fetching Dice.fm Portland events…')
        page = 1
        while True:
            try:
                data = _fetch_page(session, (page - 1) * 20, limit=20)
            except Exception as e:
                self.stderr.write(f'  /events error (page {page}): {e}')
                break

            items = data.get('events') or data.get('data') or []
            if not items:
                break

            for item in items:
                uid = str(item.get('id') or item.get('url') or item.get('name') or '')
                if uid and uid not in seen_ids:
                    seen_ids.add(uid)
                    all_events.append(item)

            meta  = data.get('meta') or data.get('links') or {}
            total = int(meta.get('total') or meta.get('count') or 0)
            if page * 20 >= total or total == 0 or len(items) < 20:
                break
            page += 1
            time.sleep(0.8)

        # ── Pass 2: keyword search fallback ────────────────────────────────
        self.stdout.write('  Running keyword search fallback…')
        try:
            sdata  = _fetch_search(session, page=1, per_page=40)
            sitems = sdata.get('events') or sdata.get('data') or sdata.get('results') or []
            for item in sitems:
                uid = str(item.get('id') or item.get('url') or '')
                if uid and uid not in seen_ids:
                    seen_ids.add(uid)
                    all_events.append(item)
        except Exception as e:
            self.stderr.write(f'  search fallback error: {e}')

        self.stdout.write(f'  {len(all_events)} candidate events')

        created = skipped = errors = 0

        for raw in all_events:
            try:
                ev = _normalize(raw)
            except Exception as e:
                errors += 1
                continue

            if not ev['title'] or not ev['start']:
                skipped += 1
                continue
            if ev['start'] > cutoff:
                skipped += 1
                continue
            # Portland relevance guard
            loc_lower = ev['location'].lower()
            if not any(kw in loc_lower for kw in ('portland', 'or', 'pdx', 'oregon')):
                if not any(kw in (ev['description'] or '').lower() for kw in ('portland', 'pdx')):
                    skipped += 1
                    continue

            if dry_run:
                self.stdout.write(
                    f'  [dry] {ev["start"].strftime("%b %d %I:%M%p")}  '
                    f'{ev["title"][:50]}  @ {ev["location"][:30]}'
                )
                created += 1
                continue

            exists = Event.objects.filter(
                title__iexact=ev['title'],
                start_date__date=ev['start'].date(),
            ).exists()
            if exists:
                skipped += 1
                continue

            if ev['website'] and Event.objects.filter(website=ev['website'][:200]).exists():
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
                    category     = 'music',
                    status       = 'pending',
                    submitted_by = 'dice-import',
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
