"""
management command: sync_discord_events

Push upcoming approved CP events to the Discord server's native Events tab.
Skips events that already exist on Discord (matched by title + start time).

Usage:
    python manage.py sync_discord_events            # next 30 days
    python manage.py sync_discord_events --days 7   # next 7 days
    python manage.py sync_discord_events --dry-run  # preview only
"""
import json
import time
import urllib.request
import urllib.error
from datetime import timedelta

from django.core.management.base import BaseCommand
from django.utils import timezone
from django.conf import settings

from events.models import Event


DISCORD_API = 'https://discord.com/api/v10'


def _headers(token):
    return {
        'Content-Type':  'application/json',
        'Authorization': f'Bot {token}',
    }


def _get_existing_events(token, guild_id):
    """Fetch all scheduled events currently on the Discord server."""
    url = f'{DISCORD_API}/guilds/{guild_id}/scheduled-events'
    req = urllib.request.Request(url, headers=_headers(token))
    try:
        with urllib.request.urlopen(req, timeout=15) as r:
            return json.loads(r.read())
    except Exception as e:
        print(f'  [!] Could not fetch existing Discord events: {e}')
        return []


def _push_event(token, guild_id, event):
    """POST a single CP event to Discord Scheduled Events. Returns created event dict or None."""
    from board.social import CP_BASE
    import base64

    cp_url = f'{CP_BASE}/events/{event.slug}/'
    desc   = (event.description or '')[:900]
    if cp_url not in desc:
        desc = f'{desc}\n\n{cp_url}'.strip()

    # Discord wants UTC ISO8601
    start_iso = event.start_date.strftime('%Y-%m-%dT%H:%M:%S+00:00')
    end_iso   = None
    if event.end_date:
        end_iso = event.end_date.strftime('%Y-%m-%dT%H:%M:%S+00:00')
    else:
        # Discord EXTERNAL events require an end time — default +2 hours
        fallback_end = event.start_date + timedelta(hours=2)
        end_iso = fallback_end.strftime('%Y-%m-%dT%H:%M:%S+00:00')

    payload = {
        'name':                 event.title[:100],
        'privacy_level':        2,           # GUILD_ONLY
        'scheduled_start_time': start_iso,
        'scheduled_end_time':   end_iso,
        'description':          desc[:1000],
        'entity_type':          3,           # EXTERNAL
        'entity_metadata':      {'location': (event.location or 'Portland, OR')[:100]},
    }

    # Attach cover image if available
    photo = None
    if event.photo:
        photo = event.photo
    elif hasattr(event, 'approved_photos') and event.approved_photos.exists():
        photo = event.approved_photos.first().image

    if photo:
        try:
            img_url = f'{CP_BASE}{photo.url}'
            req = urllib.request.Request(img_url,
                headers={'User-Agent': 'CommunityPlaylist/1.0'})
            with urllib.request.urlopen(req, timeout=10) as r:
                ctype = r.headers.get('Content-Type', 'image/jpeg').split(';')[0]
                img_b64 = base64.b64encode(r.read()).decode()
            payload['image'] = f'data:{ctype};base64,{img_b64}'
        except Exception:
            pass

    api_url = f'{DISCORD_API}/guilds/{guild_id}/scheduled-events'
    req = urllib.request.Request(
        api_url,
        data=json.dumps(payload).encode(),
        headers=_headers(token),
        method='POST',
    )
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            return json.loads(r.read())
    except urllib.error.HTTPError as e:
        body = e.read().decode('utf-8', errors='replace')
        print(f'  [!] HTTP {e.code}: {body[:200]}')
        return None
    except Exception as e:
        print(f'  [!] Error: {e}')
        return None


class Command(BaseCommand):
    help = 'Push upcoming CP events to Discord native Scheduled Events tab'

    def add_arguments(self, parser):
        parser.add_argument('--days',        type=int, default=30,  help='How many days ahead to sync (default 30)')
        parser.add_argument('--dry-run',     action='store_true',   help='Preview without posting')
        parser.add_argument('--limit',       type=int, default=50,  help='Max events to push per run (default 50)')
        parser.add_argument('--export-json', action='store_true',   help='Print events as JSON to stdout (for Unraid sync worker)')

    def handle(self, *args, **options):
        import base64 as _b64
        token    = getattr(settings, 'DISCORD_BOT_TOKEN', '')
        guild_id = getattr(settings, 'DISCORD_GUILD_ID',  '')
        dry_run  = options['dry_run']
        days     = options['days']
        limit    = options['limit']

        # ── JSON export mode: dump upcoming events to stdout, exit ───────────
        if options['export_json']:
            import json as _json
            now    = timezone.now()
            cutoff = now + timedelta(days=days)
            qs     = (Event.objects
                      .filter(status='approved', start_date__gte=now, start_date__lte=cutoff)
                      .order_by('start_date')[:limit])
            out = []
            for e in qs:
                photo_url = ''
                try:
                    if e.photo:
                        photo_url = settings.SITE_URL + e.photo.url
                except Exception:
                    pass
                out.append({
                    'slug':        e.slug,
                    'title':       e.title,
                    'location':    e.location or 'Portland, OR',
                    'description': (e.description or '')[:1000],
                    'start_iso':   e.start_date.strftime('%Y-%m-%dT%H:%M:%S+00:00'),
                    'end_iso':     e.end_date.strftime('%Y-%m-%dT%H:%M:%S+00:00') if e.end_date else None,
                    'url':         f'{settings.SITE_URL}/events/{e.slug}/',
                    'photo_url':   photo_url,
                })
            self.stdout.write(_json.dumps(out))
            return

        if not token or not guild_id:
            self.stderr.write('DISCORD_BOT_TOKEN or DISCORD_GUILD_ID not set in .env')
            return

        now     = timezone.now()
        cutoff  = now + timedelta(days=days)
        events  = (Event.objects
                   .filter(status='approved', start_date__gte=now, start_date__lte=cutoff)
                   .order_by('start_date')[:limit])

        self.stdout.write(f'Found {events.count()} upcoming local events (next {days} days)')

        if dry_run:
            self.stdout.write('[DRY RUN] Would push:')
            for e in events:
                self.stdout.write(f'  • {e.start_date:%b %d %H:%M}  {e.title[:60]}')
            return

        # Fetch what's already on Discord to avoid duplicates
        existing = _get_existing_events(token, guild_id)
        existing_keys = set()
        for ev in existing:
            # Key: normalised title + date prefix (YYYY-MM-DD)
            t = (ev.get('name') or '').strip().lower()
            s = (ev.get('scheduled_start_time') or '')[:10]
            existing_keys.add(f'{t}|{s}')

        self.stdout.write(f'{len(existing)} events already on Discord')

        pushed = skipped = failed = 0
        for e in events:
            key = f'{e.title.strip().lower()[:100]}|{e.start_date.strftime("%Y-%m-%d")}'
            if key in existing_keys:
                skipped += 1
                continue

            self.stdout.write(f'  → Pushing: {e.title[:55]}  [{e.start_date:%b %d}]')
            result = _push_event(token, guild_id, e)
            if result and result.get('id'):
                pushed += 1
                self.stdout.write(f'    ✓ Created Discord event {result["id"]}')
            else:
                failed += 1

            time.sleep(0.6)  # stay under Discord's rate limit (50 req/s global)

        self.stdout.write(
            f'\nDone — pushed: {pushed}  skipped (already exists): {skipped}  failed: {failed}'
        )
