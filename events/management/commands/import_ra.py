"""
management command: python manage.py import_ra

Pulls upcoming Portland-area events from Resident Advisor via their
internal GraphQL API (the same endpoint the RA website uses).

Events land as status=pending for admin review.

Usage:
    python manage.py import_ra
    python manage.py import_ra --days 21
    python manage.py import_ra --dry-run

To find Portland's area ID: visit https://ra.co/events/us/portland in a browser,
open DevTools → Network, look for a GraphQL POST to ra.co/graphql and find the
areas.eq value. Default here is 210 (Portland OR on RA's current schema).
"""
import time
import json
import re
import pytz
import requests
from datetime import datetime, timedelta

from django.core.management.base import BaseCommand
from django.utils import timezone
from django.utils.text import slugify
from events.models import Event, Genre

PDX_TZ      = pytz.timezone('America/Los_Angeles')
RA_GQL_URL  = 'https://ra.co/graphql'
RA_AREA_ID  = 125          # Resident Advisor area ID for Portland, OR (verified via area query)
RA_REFERRER = 'https://ra.co/events/us/portland'

HEADERS = {
    'User-Agent': (
        'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) '
        'AppleWebKit/537.36 (KHTML, like Gecko) '
        'Chrome/124.0.0.0 Safari/537.36'
    ),
    'Content-Type':  'application/json',
    'Accept':        'application/json',
    'Origin':        'https://ra.co',
    'Referer':       RA_REFERRER,
    'Accept-Language': 'en-US,en;q=0.9',
}

QUERY = """
query GET_PORTLAND_EVENTS($filters: FilterInputDtoInput, $pageSize: Int, $page: Int) {
  eventListings(filters: $filters, pageSize: $pageSize, page: $page) {
    data {
      id
      listingDate
      event {
        id
        title
        date
        startTime
        endTime
        flyerFront
        contentUrl
        cost
        isTicketed
        venue { name address }
        artists { name }
        genres { name }
        content
      }
    }
    totalResults
  }
}
"""


def _parse_dt(dt_str):
    """Return a PDX-aware datetime from an RA LocalDateTime string (no tz info)."""
    if not dt_str:
        return None
    try:
        # Strip milliseconds and any trailing tz chars
        raw = re.sub(r'\.\d+', '', str(dt_str)).split('+')[0].rstrip('Z')
        dt  = datetime.fromisoformat(raw)
        return PDX_TZ.localize(dt)
    except Exception:
        return None


def _fetch_page(session, date_from, date_to, page, size=50):
    payload = {
        'operationName': 'GET_PORTLAND_EVENTS',
        'query': QUERY,
        'variables': {
            'filters': {
                'areas':       {'eq': RA_AREA_ID},
                'listingDate': {'gte': date_from, 'lte': date_to},
            },
            'pageSize': size,
            'page':     page,
        },
    }
    r = session.post(RA_GQL_URL, json=payload, headers=HEADERS, timeout=20)
    r.raise_for_status()
    return r.json()


class Command(BaseCommand):
    help = 'Import upcoming Portland events from Resident Advisor'

    def add_arguments(self, parser):
        parser.add_argument('--days',    type=int, default=30,
                            help='Days ahead to fetch (default: 30)')
        parser.add_argument('--dry-run', action='store_true',
                            help='Print without saving')

    def handle(self, *args, **options):
        days    = options['days']
        dry_run = options['dry_run']

        now       = timezone.now()
        cutoff    = now + timedelta(days=days)
        date_from = now.strftime('%Y-%m-%d')
        date_to   = cutoff.strftime('%Y-%m-%d')

        self.stdout.write(f'Fetching RA Portland events {date_from} → {date_to}…')

        session  = requests.Session()
        page     = 1
        size     = 50
        total    = None
        all_rows = []

        while True:
            try:
                data = _fetch_page(session, date_from, date_to, page, size)
            except Exception as e:
                self.stderr.write(f'  Error on page {page}: {e}')
                break

            listings = (data.get('data') or {}).get('eventListings') or {}
            if total is None:
                total = listings.get('totalResults', 0)
                self.stdout.write(f'  {total} total results on RA')

            rows = listings.get('data') or []
            if not rows:
                break
            all_rows.extend(rows)

            if len(all_rows) >= total or len(rows) < size:
                break
            page += 1
            time.sleep(1.5)

        self.stdout.write(f'  Retrieved {len(all_rows)} listings')

        created = skipped = errors = 0

        for row in all_rows:
            ev = row.get('event') or {}
            if not ev:
                continue

            title = (ev.get('title') or '').strip()
            if not title:
                continue

            start_dt = _parse_dt(ev.get('startTime') or ev.get('date'))
            if not start_dt:
                skipped += 1
                continue

            end_dt = _parse_dt(ev.get('endTime')) if ev.get('endTime') else None

            venue_data  = ev.get('venue') or {}
            venue_name  = (venue_data.get('name') or '').strip()
            venue_addr  = (venue_data.get('address') or '').strip().rstrip("'")
            location    = f'{venue_name}, Portland, OR' if venue_name else 'Portland, OR'

            raw_url     = (ev.get('contentUrl') or '').strip()
            ticket_url  = (f'https://ra.co{raw_url}' if raw_url.startswith('/') else raw_url)
            description = (ev.get('content') or '').strip()[:2000]

            # RA flyer image
            flyer_url = (ev.get('flyerFront') or '').strip()
            if flyer_url and not flyer_url.startswith('http'):
                flyer_url = f'https://static.ra.co/{flyer_url}'

            genre_names = [g['name'] for g in (ev.get('genres') or []) if g.get('name')]
            artist_names = [a['name'] for a in (ev.get('artists') or []) if a.get('name')]

            if dry_run:
                self.stdout.write(
                    f'  [dry] {start_dt.strftime("%b %d %I:%M%p")}  {title[:50]}'
                    f'  @ {venue_name[:25]}'
                    + (f'  | {", ".join(artist_names[:3])}' if artist_names else '')
                )
                created += 1
                continue

            # Deduplicate: same normalised title + same calendar date
            exists = Event.objects.filter(
                title__iexact=title,
                start_date__date=start_dt.date(),
            ).exists()
            if exists:
                skipped += 1
                continue

            slug_base = slugify(f'{title}-{start_dt.strftime("%Y-%m-%d")}')[:90]
            slug = slug_base
            n = 1
            while Event.objects.filter(slug=slug).exists():
                slug = f'{slug_base}-{n}'; n += 1

            try:
                event = Event.objects.create(
                    title        = title[:200],
                    slug         = slug,
                    description  = description or f'Event at {location}',
                    location     = location[:300],
                    start_date   = start_dt,
                    end_date     = end_dt,
                    website      = ticket_url[:500] if ticket_url else '',
                    flyer_url    = flyer_url[:500] if flyer_url else '',
                    category     = 'music',
                    is_free      = False,
                    status       = 'pending',
                    submitted_by = 'ra-import',
                )

                # Wire up genres
                for gname in genre_names:
                    genre, _ = Genre.objects.get_or_create(name=gname)
                    event.genres.add(genre)

                created += 1
                self.stdout.write(f'  + {title[:55]}  [{start_dt.strftime("%b %d")}]')
            except Exception as e:
                self.stderr.write(f'  ERROR "{title[:40]}": {e}')
                errors += 1

        self.stdout.write(
            f'\nDone — created: {created}  skipped: {skipped}  errors: {errors}'
        )
        if created and not dry_run:
            self.stdout.write('Review at /admin/events/event/?status=pending')
