"""
management command: python manage.py import_19hz

Scrapes 19hz.info — the long-running PNW underground event calendar.
Covers Oregon/Portland and Seattle/PNW pages. One of the best free
data sources for PDX techno, bass, house, and underground shows.

Events land as status=pending for admin review.

Usage:
    python manage.py import_19hz
    python manage.py import_19hz --dry-run
    python manage.py import_19hz --region ore        # Oregon only
    python manage.py import_19hz --region seattle    # Seattle/PNW only
"""
import re
import time
import pytz
import requests
from datetime import datetime, timedelta

from django.core.management.base import BaseCommand
from django.utils import timezone
from django.utils.text import slugify
from events.models import Event

PDX_TZ = pytz.timezone('America/Los_Angeles')

REGIONS = {
    'ore':     'https://19hz.info/eventlisting_ORE.php',
    'seattle': 'https://19hz.info/eventlisting_Seattle.php',
}

HEADERS = {
    'User-Agent': 'Mozilla/5.0 (compatible; CommunityPlaylist/1.0; +https://communityplaylist.com)',
    'Accept': 'text/html,application/xhtml+xml',
    'Accept-Language': 'en-US,en;q=0.9',
}

# 19hz date format: "Tue May 14" or "Tue May 14, 2026"
DATE_RE  = re.compile(r'(?:\w{3}:\s+)?(\w{3})\s+(\d{1,2})(?:,?\s*(\d{4}))?')
TIME_RE  = re.compile(r'(\d{1,2}):(\d{2})\s*(am|pm)', re.I)
PRICE_RE = re.compile(r'\$[\d.]+(?:\s*[-–]\s*\$[\d.]+)?|free|FREE|\bno\s+cover\b', re.I)

# Portland relevance — filter out Seattle-only shows when scraping both
PDX_RE = re.compile(
    r'\b(portland|pdx|p\.?d\.?x|hillsboro|beaverton|gresham|lake\s*oswego'
    r'|oregon city|clackamas|milwaukie|se |sw |ne |nw |north portland)\b', re.I
)

MONTH_MAP = {
    'jan': 1, 'feb': 2, 'mar': 3, 'apr': 4, 'may': 5, 'jun': 6,
    'jul': 7, 'aug': 8, 'sep': 9, 'oct': 10, 'nov': 11, 'dec': 12,
}


def _parse_date_time(date_str, time_str, now):
    """Return a PDX-aware datetime from 19hz date + time strings, or None."""
    dm = DATE_RE.search(date_str or '')
    if not dm:
        return None
    try:
        month = MONTH_MAP.get(dm.group(1).lower())
        day   = int(dm.group(2))
        year  = int(dm.group(3)) if dm.group(3) else now.year
        # Handle year rollover (e.g. Dec → Jan)
        if month and month < now.month - 1:
            year += 1
        if not month:
            return None
        hour, minute = 21, 0   # default 9 PM
        tm = TIME_RE.search(time_str or '')
        if tm:
            hour   = int(tm.group(1))
            minute = int(tm.group(2))
            if tm.group(3).lower() == 'pm' and hour != 12:
                hour += 12
            elif tm.group(3).lower() == 'am' and hour == 12:
                hour = 0
        dt = datetime(year, month, day, hour, minute)
        return PDX_TZ.localize(dt)
    except Exception:
        return None


def _scrape_region(session, url):
    """
    Fetch and parse one 19hz region page.
    Row format: date+time | title @ venue | price | ... | event link | iso-date
    Returns list of raw event dicts.
    """
    try:
        r = session.get(url, headers=HEADERS, timeout=15)
        r.raise_for_status()
    except Exception as e:
        return [], str(e)

    import html as html_lib

    # Pull all <tr> blocks, then extract <td> and <a> content from each
    TR_RE   = re.compile(r'<tr[^>]*>(.*?)</tr>', re.S | re.I)
    TD_RE   = re.compile(r'<td[^>]*>(.*?)</td>', re.S | re.I)
    A_RE    = re.compile(r'<a[^>]+href=["\']([^"\']+)["\'][^>]*>(.*?)</a>', re.S | re.I)
    TAG_RE  = re.compile(r'<[^>]+>')

    def _text(html):
        return html_lib.unescape(TAG_RE.sub('', html)).strip()

    def _links(html):
        return [(m.group(1), _text(m.group(2))) for m in A_RE.finditer(html)]

    raw = []
    for tr_m in TR_RE.finditer(r.text):
        tr_html = tr_m.group(1)
        cells   = TD_RE.findall(tr_html)
        if len(cells) < 2:
            continue

        dt_cell    = cells[0]
        body_cell  = cells[1]
        price_cell = cells[2] if len(cells) > 2 else ''

        dt_text   = _text(dt_cell)
        body_text = _text(body_cell)

        # Col 0: "Tue: May 12 (8pm)" or "Tue: May 12 (9pm-11:59pm)"
        # Extract date portion and time
        dt_m = re.search(r'([A-Z][a-z]{2})\s+(\d{1,2})', dt_text)
        if not dt_m:
            continue

        time_m = re.search(r'\((\d{1,2}(?::\d{2})?\s*(?:am|pm))', dt_text, re.I)
        time_text = time_m.group(1) if time_m else ''

        # Full date string for _parse_date_time
        date_str = dt_text

        # Col 1: "Title @ Venue" — split on " @ " to get venue
        if ' @ ' in body_text:
            title, venue = body_text.split(' @ ', 1)
        else:
            title  = body_text
            venue  = ''
        title = title.strip()[:200]
        venue = venue.strip()[:200]

        price_text = _text(price_cell)

        # All <a> hrefs across all cells
        all_links = []
        for c in cells:
            all_links.extend(href for href, _ in _links(c)
                             if href.startswith('http'))

        raw.append({
            'date_text':  date_str,
            'time_text':  time_text,
            'title':      title,
            'detail':     venue,
            'price_text': price_text,
            'links':      list(dict.fromkeys(all_links)),
        })

    return raw, None


def _is_pdx(title, detail):
    text = f'{title} {detail}'
    return bool(PDX_RE.search(text))


class Command(BaseCommand):
    help = 'Import upcoming Portland events from 19hz.info (PNW underground calendar)'

    def add_arguments(self, parser):
        parser.add_argument('--region',  choices=['ore', 'seattle', 'both'], default='both',
                            help='Which 19hz page to scrape (default: both)')
        parser.add_argument('--dry-run', action='store_true',
                            help='Print without saving')
        parser.add_argument('--days',    type=int, default=60,
                            help='Skip events further than this many days out (default: 60)')

    def handle(self, *args, **options):
        region  = options['region']
        dry_run = options['dry_run']
        days    = options['days']

        now    = timezone.now()
        cutoff = now + timedelta(days=days)

        session   = requests.Session()
        all_raw   = []
        pages     = []

        if region in ('ore', 'both'):
            pages.append(('Oregon/PDX', REGIONS['ore']))
        if region in ('seattle', 'both'):
            pages.append(('Seattle/PNW', REGIONS['seattle']))

        for name, url in pages:
            self.stdout.write(f'Fetching 19hz {name}…')
            raw, err = _scrape_region(session, url)
            if err:
                self.stderr.write(f'  Error: {err}')
            else:
                self.stdout.write(f'  {len(raw)} rows parsed')
                all_raw.extend(raw)
            time.sleep(0.5)

        created = skipped = errors = 0

        for row in all_raw:
            title = row['title']
            if not title or len(title) < 3:
                skipped += 1
                continue

            start_dt = _parse_date_time(row['date_text'], row['time_text'], now)
            if not start_dt:
                skipped += 1
                continue
            if start_dt < now or start_dt > cutoff:
                skipped += 1
                continue

            detail = row['detail']

            # For Seattle page, require PDX relevance signal
            if region == 'both' and not _is_pdx(title, detail):
                skipped += 1
                continue

            # Price detection
            price_text = row['price_text'] or ''
            pm = PRICE_RE.search(price_text + ' ' + detail)
            is_free = bool(re.search(r'free|no\s+cover', price_text + ' ' + detail, re.I))
            price_info = pm.group(0) if pm and not is_free else ''

            # Pick best ticket/info link
            ticket_url = ''
            for lnk in row['links']:
                if any(x in lnk for x in ('eventbrite', 'ra.co', 'dice.fm', 'ticketfly', 'axs.com')):
                    ticket_url = lnk
                    break
            if not ticket_url and row['links']:
                ticket_url = row['links'][0]

            if dry_run:
                self.stdout.write(
                    f'  [dry] {start_dt.strftime("%b %d %I:%M%p")}  {title[:55]}'
                    + (f'  | {ticket_url[:50]}' if ticket_url else '')
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

            if ticket_url and Event.objects.filter(website=ticket_url[:200]).exists():
                skipped += 1
                continue

            slug_base = slugify(f'{title}-{start_dt.strftime("%Y-%m-%d")}')[:90]
            slug = slug_base; n = 1
            while Event.objects.filter(slug=slug).exists():
                slug = f'{slug_base}-{n}'; n += 1

            try:
                Event.objects.create(
                    title        = title,
                    slug         = slug,
                    description  = detail or f'Event sourced from 19hz.info',
                    location     = 'Portland, OR',
                    start_date   = start_dt,
                    website      = ticket_url[:500] if ticket_url else '',
                    is_free      = is_free,
                    price_info   = price_info[:100],
                    category     = 'music',
                    status       = 'pending',
                    submitted_by = '19hz-import',
                )
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
