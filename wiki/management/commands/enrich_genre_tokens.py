"""
enrich_genre_tokens — fetch Last.fm + MusicBrainz data for each GenreToken.

Fills in description, mood, energy, bpm_min/max and creates TokenSource
records.  Safe to re-run: only overwrites blank fields, never clobbers
manually-written content.

Sources:
  Last.fm tag.getinfo  — description, listener count
  MusicBrainz genres   — validates the token is a known MB genre
"""
import time
import urllib.request
import urllib.parse
import json
import re

from django.conf import settings
from django.core.management.base import BaseCommand

from wiki.models import GenreToken, TokenSource


LASTFM_API  = 'https://ws.audioscrobbler.com/2.0/'
MB_API      = 'https://musicbrainz.org/ws/2/'
MB_CONTACT  = getattr(settings, 'MUSICBRAINZ_CONTACT', 'hello@communityplaylist.com')
USER_AGENT  = f'CommunityPlaylistWiki/1.0 ( {MB_CONTACT} )'

# BPM ranges and energy guesses for well-known tokens
# Used only when the token has no bpm data yet — never overwrites manual entries
_BPM_HINTS = {
    'Ambient':     (60,  90,  'low'),
    'Bass':        (130, 160, 'high'),
    'Breakbeat':   (120, 145, 'high'),
    'Breaks':      (120, 145, 'high'),
    'Dance':       (120, 135, 'high'),
    'Deep':        (120, 128, 'mid'),
    'Disco':       (110, 130, 'high'),
    'Downtempo':   (70,  100, 'low'),
    'Drum':        (160, 180, 'very_high'),
    'Dub':         (70,  100, 'low'),
    'Dubstep':     (138, 142, 'high'),
    'Electronic':  (120, 140, 'high'),
    'Electro':     (120, 135, 'high'),
    'G-Funk':      (90,  105, 'mid'),
    'Garage':      (125, 135, 'high'),
    'Grime':       (140, 142, 'high'),
    'Hip':         (80,  100, 'mid'),
    'Hop':         (80,  100, 'mid'),
    'House':       (120, 130, 'high'),
    'Jazz':        (100, 200, 'mid'),
    'Jungle':      (160, 180, 'very_high'),
    'Metal':       (100, 220, 'very_high'),
    'Pop':         (100, 130, 'mid'),
    'Punk':        (160, 200, 'very_high'),
    'R&B':         (60,  90,  'low'),
    'Rap':         (80,  100, 'mid'),
    'Rock':        (100, 160, 'high'),
    'Soul':        (60,  100, 'low'),
    'Tech':        (130, 150, 'high'),
    'Techno':      (130, 150, 'very_high'),
    'Trance':      (128, 145, 'very_high'),
    'Trap':        (60,  75,  'high'),
    'Trip':        (80,  100, 'low'),
}


def _get(url, params=None, delay=1.1):
    """Simple rate-limited GET → parsed JSON."""
    if params:
        url = url + '?' + urllib.parse.urlencode(params)
    req = urllib.request.Request(url, headers={'User-Agent': USER_AGENT})
    try:
        with urllib.request.urlopen(req, timeout=15) as r:
            data = json.load(r)
        time.sleep(delay)
        return data
    except Exception:
        time.sleep(delay)
        return None


def _lastfm_tag(name: str, api_key: str) -> dict | None:
    data = _get(LASTFM_API, {
        'method': 'tag.getinfo',
        'tag': name,
        'api_key': api_key,
        'format': 'json',
    })
    return data.get('tag') if data else None


def _mb_genre(name: str) -> dict | None:
    data = _get(MB_API + 'genre/', {
        'query': f'name:"{name}"',
        'fmt': 'json',
        'limit': 1,
    }, delay=1.2)
    genres = (data or {}).get('genres', [])
    return genres[0] if genres else None


def _clean_html(text: str) -> str:
    text = re.sub(r'<[^>]+>', '', text)
    text = re.sub(r'\s+', ' ', text).strip()
    # Last.fm appends "Read more on Last.fm" — strip it
    text = re.sub(r'\s*Read more on Last\.fm\.?\s*$', '', text, flags=re.I)
    return text[:2000]


class Command(BaseCommand):
    help = 'Enrich GenreTokens with Last.fm and MusicBrainz data'

    def add_arguments(self, parser):
        parser.add_argument('--lastfm-key', default='',
                            help='Last.fm API key (falls back to settings.LASTFM_API_KEY)')
        parser.add_argument('--skip-mb', action='store_true',
                            help='Skip MusicBrainz lookups')
        parser.add_argument('--force', action='store_true',
                            help='Overwrite existing descriptions (default: only fill blanks)')
        parser.add_argument('--dry-run', action='store_true')

    def handle(self, *args, **options):
        api_key = options['lastfm_key'] or getattr(settings, 'LASTFM_API_KEY', '')
        skip_mb = options['skip_mb']
        force   = options['force']
        dry     = options['dry_run']

        tokens = list(GenreToken.objects.all().prefetch_related('sources'))
        self.stdout.write(f'Enriching {len(tokens)} tokens…')

        updated = skipped = 0

        for token in tokens:
            changed = False
            self.stdout.write(f'  {token.name}', ending=' ')

            # ── Last.fm ───────────────────────────────────────────────────
            if api_key:
                tag_data = _lastfm_tag(token.name, api_key)
                if tag_data:
                    raw_desc = tag_data.get('wiki', {}).get('content', '') or \
                               tag_data.get('wiki', {}).get('summary', '')
                    desc = _clean_html(raw_desc)
                    listeners = int(tag_data.get('reach', 0) or 0)

                    if desc and (force or not token.description):
                        if not dry:
                            token.description = desc
                        changed = True

                    if not dry:
                        src, _ = TokenSource.objects.get_or_create(
                            token=token, source='lastfm',
                            defaults={'confidence': 'derived'},
                        )
                        if listeners:
                            src.listener_count = listeners
                            src.source_name    = token.name
                            src.save(update_fields=['listener_count', 'source_name'])
                    self.stdout.write('lastfm✓', ending=' ')
                else:
                    self.stdout.write('lastfm–', ending=' ')
            else:
                self.stdout.write('(no lastfm key)', ending=' ')

            # ── MusicBrainz ───────────────────────────────────────────────
            if not skip_mb:
                mb = _mb_genre(token.name)
                if mb:
                    if not dry:
                        TokenSource.objects.get_or_create(
                            token=token, source='musicbrainz',
                            defaults={
                                'source_name': mb.get('name', token.name),
                                'confidence': 'verified',
                            },
                        )
                    self.stdout.write('mb✓', ending=' ')
                else:
                    self.stdout.write('mb–', ending=' ')

            # ── BPM / energy hints ────────────────────────────────────────
            hint = _BPM_HINTS.get(token.name)
            if hint and not dry:
                bpm_lo, bpm_hi, energy = hint
                if not token.bpm_min:
                    token.bpm_min = bpm_lo
                    changed = True
                if not token.bpm_max:
                    token.bpm_max = bpm_hi
                    changed = True
                if not token.energy:
                    token.energy = energy
                    changed = True

            if changed and not dry:
                token.save()
                updated += 1
            elif not changed:
                skipped += 1

            self.stdout.write('')  # newline

        self.stdout.write(self.style.SUCCESS(
            f'Done — {updated} tokens updated, {skipped} unchanged'
        ))
