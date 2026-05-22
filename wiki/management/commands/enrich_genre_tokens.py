"""
enrich_genre_tokens — multi-source enrichment for GenreToken + CompoundGenre.

Flags (can be combined freely):
  --lastfm-tracks   Last.fm tag.gettoptracks → top_tracks_json on tokens
  --wikipedia       Wikipedia REST API → description, origin_year, derived_from
  --youtube         YouTube Data API → youtube_video_id (genre overview video)
  --compound-tracks Last.fm tag lookup + top tracks for CompoundGenre objects
  --skip-mb         Skip MusicBrainz genre validation
  --force           Overwrite existing non-empty fields
  --limit N         Stop after N tokens (useful for quota management)
  --dry-run         Print what would change, write nothing

Wikipedia fills: origin_year, derived_from FK, description (if blank or --force).
YouTube quota:   100 units/search; default 10 000/day → use --limit 90 per run.
"""
import re
import time
import urllib.request
import urllib.parse
import json
from collections import defaultdict
from itertools import permutations as _perms

from django.conf import settings
from django.core.management.base import BaseCommand

from wiki.models import GenreToken, CompoundGenre, TokenSource


# ── API bases ────────────────────────────────────────────────────────────────
LASTFM_API = 'https://ws.audioscrobbler.com/2.0/'
MB_API     = 'https://musicbrainz.org/ws/2/'
WP_API     = 'https://en.wikipedia.org/api/rest_v1/page/summary/'
YT_API     = 'https://www.googleapis.com/youtube/v3/'

MB_CONTACT = getattr(settings, 'MUSICBRAINZ_CONTACT', 'hello@communityplaylist.com')
USER_AGENT = f'CommunityPlaylistWiki/1.0 ( {MB_CONTACT} )'

# ── BPM / energy hints ────────────────────────────────────────────────────────
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

# ── Wikipedia helpers ─────────────────────────────────────────────────────────
_YEAR_EXACT  = re.compile(r'\bin\s+(1[89]\d\d|20[012]\d)\b')
_YEAR_DECADE = re.compile(
    r'\bin\s+(?:the\s+)?(?:(early|mid|late)\s+)?(1[89]\d0|20[012]0)s\b', re.I)
_DERIVED_RX  = [
    re.compile(r'(?:sub-?genre|subtype|variant|form|style|type|offshoot|branch)\s+of\s+([^,.;\n]{4,50})', re.I),
    re.compile(r'evolved?\s+(?:out\s+of|from)\s+([^,.;\n]{4,50})', re.I),
    re.compile(r'developed?\s+(?:out\s+of|from)\s+([^,.;\n]{4,50})', re.I),
    re.compile(r'rooted?\s+in\s+([^,.;\n]{4,50})', re.I),
    re.compile(r'derived?\s+from\s+([^,.;\n]{4,50})', re.I),
]


def _year_from_text(text: str) -> int | None:
    m = _YEAR_EXACT.search(text)
    if m:
        return int(m.group(1))
    m = _YEAR_DECADE.search(text)
    if m:
        decade = int(m.group(2))
        offset = {'early': 2, 'mid': 5, 'late': 8}.get((m.group(1) or '').lower(), 0)
        return decade + offset
    return None


# Tokens too generic to be a meaningful parent
_TOO_GENERIC = {'Music', 'Sound', 'Genre', 'Style', 'Listening', 'Recording', 'Song', 'Beat'}


def _derived_from_text(text: str, known: set[str]) -> str | None:
    for rx in _DERIVED_RX:
        m = rx.search(text)
        if not m:
            continue
        raw = re.sub(r'\s+', ' ', m.group(1)).strip().rstrip('.')
        raw_lower = raw.lower()
        for name in known:
            if name in _TOO_GENERIC:
                continue
            if name.lower() == raw_lower:
                return name
        for name in known:
            if name in _TOO_GENERIC:
                continue
            if len(name) >= 4 and name.lower() in raw_lower:
                return name
    return None


# ── HTTP helper ───────────────────────────────────────────────────────────────
def _get(url: str, params: dict | None = None, delay: float = 1.1) -> dict | None:
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


# ── Last.fm helpers ───────────────────────────────────────────────────────────
def _lastfm_tag(name: str, api_key: str) -> dict | None:
    data = _get(LASTFM_API, {
        'method': 'tag.getinfo', 'tag': name,
        'api_key': api_key, 'format': 'json',
    })
    return data.get('tag') if data else None


def _lastfm_top_tracks(tag: str, api_key: str, limit: int = 5) -> list:
    data = _get(LASTFM_API, {
        'method': 'tag.gettoptracks', 'tag': tag,
        'api_key': api_key, 'format': 'json', 'limit': limit,
    })
    raw = (data or {}).get('tracks', {}).get('track', [])
    if isinstance(raw, dict):
        raw = [raw]
    result = []
    for t in raw:
        artist = t.get('artist', {})
        result.append({
            'name':       t.get('name', ''),
            'artist':     artist.get('name', '') if isinstance(artist, dict) else str(artist),
            'playcount':  int(t.get('playcount', 0) or 0),
            'lastfm_url': t.get('url', ''),
        })
    return result


def _compound_lfm_search(token_names: list[str], api_key: str) -> tuple[str, list]:
    """Try permutations of token names as Last.fm tags; return (found_tag, tracks)."""
    from itertools import permutations as perms_fn
    n = len(token_names)
    tested = set()

    def _try(tag: str) -> list:
        if tag in tested:
            return []
        tested.add(tag)
        return _lastfm_top_tracks(tag, api_key, limit=5)

    # Full permutations for small sets (4! = 24 — feasible)
    if n <= 4:
        for perm in perms_fn(token_names):
            for joiner in (' ', '-', ' & ', ' and '):
                t = _try(joiner.join(perm).lower())
                if len(t) >= 3:
                    return joiner.join(perm).lower(), t
    else:
        for joiner in (' ', '-', ' & ', ' and '):
            t = _try(joiner.join(token_names).lower())
            if len(t) >= 3:
                return joiner.join(token_names).lower(), t

    # Sub-permutation fallback: shorter tags catch "trip hop" inside [Downtempo, Hop, Trip]
    for sub_len in (3, 2):
        if sub_len >= n:
            continue
        for perm in perms_fn(token_names, sub_len):
            for joiner in (' ', '-'):
                t = _try(joiner.join(perm).lower())
                if len(t) >= 3:
                    return joiner.join(perm).lower(), t

    return '', []


# ── MusicBrainz helper ────────────────────────────────────────────────────────
def _mb_genre(name: str) -> dict | None:
    data = _get(MB_API + 'genre/', {
        'query': f'name:"{name}"', 'fmt': 'json', 'limit': 1,
    }, delay=1.2)
    genres = (data or {}).get('genres', [])
    return genres[0] if genres else None


# ── Wikipedia helpers ─────────────────────────────────────────────────────────
def _wikipedia_summary(name: str) -> dict | None:
    """Try several title patterns; return summary dict if a music page is found."""
    for title in [f'{name} music', name, f'{name} (music)', f'{name} (genre)']:
        slug = urllib.parse.quote(title.replace(' ', '_'))
        data = _get(WP_API + slug, delay=1.1)
        if not data or data.get('type') == 'disambiguation':
            continue
        extract = (data.get('extract') or '').lower()
        if any(w in extract for w in ('music', 'genre', 'sound', 'rhythm', 'beat', 'tempo', 'melodic', 'recorded')):
            data['_title'] = title
            return data
    return None


# ── YouTube helper ────────────────────────────────────────────────────────────
def _youtube_search_video(query: str, api_key: str) -> str | None:
    data = _get(YT_API + 'search', {
        'part': 'snippet', 'q': query, 'type': 'video',
        'videoCategoryId': '10', 'maxResults': 1, 'key': api_key,
    }, delay=0.3)
    items = (data or {}).get('items', [])
    return items[0].get('id', {}).get('videoId') if items else None


# ── Text cleaner ─────────────────────────────────────────────────────────────
def _clean_html(text: str) -> str:
    text = re.sub(r'<[^>]+>', '', text)
    text = re.sub(r'\s+', ' ', text).strip()
    text = re.sub(r'\s*Read more on Last\.fm\.?\s*$', '', text, flags=re.I)
    return text[:2000]


# ── Command ───────────────────────────────────────────────────────────────────
class Command(BaseCommand):
    help = 'Enrich GenreTokens and CompoundGenres from Last.fm, Wikipedia, YouTube'

    def add_arguments(self, parser):
        parser.add_argument('--lastfm-key', default='')
        parser.add_argument('--yt-key', default='')
        parser.add_argument('--skip-mb', action='store_true')
        parser.add_argument('--lastfm-tracks', action='store_true',
                            help='Fetch top 5 tracks per token from Last.fm')
        parser.add_argument('--wikipedia', action='store_true',
                            help='Fetch Wikipedia: origin_year, derived_from, description')
        parser.add_argument('--youtube', action='store_true',
                            help='Search YouTube for genre overview video per token')
        parser.add_argument('--compound-tracks', action='store_true',
                            help='Fetch Last.fm top tracks for CompoundGenre objects')
        parser.add_argument('--compound-youtube', action='store_true',
                            help='Search YouTube overview video for CompoundGenre objects')
        parser.add_argument('--force', action='store_true',
                            help='Overwrite non-empty fields')
        parser.add_argument('--limit', type=int, default=0,
                            help='Max tokens/compounds to process (0 = all)')
        parser.add_argument('--dry-run', action='store_true')

    def handle(self, *args, **options):
        api_key        = options['lastfm_key']    or getattr(settings, 'LASTFM_API_KEY', '')
        yt_key         = options['yt_key']         or getattr(settings, 'YOUTUBE_API_KEY', '')
        skip_mb        = options['skip_mb']
        do_tracks      = options['lastfm_tracks']
        do_wikipedia   = options['wikipedia']
        do_youtube     = options['youtube']
        do_cmpd_tracks = options['compound_tracks']
        do_cmpd_yt     = options['compound_youtube']
        force          = options['force']
        limit          = options['limit']
        dry            = options['dry_run']

        # ── Token enrichment ───────────────────────────────────────────────
        tokens = list(GenreToken.objects.all().prefetch_related('sources'))
        known_names = {t.name for t in tokens}
        if limit:
            tokens = tokens[:limit]
        self.stdout.write(f'Enriching {len(tokens)} tokens…')

        updated = skipped = 0

        for token in tokens:
            changed = False
            self.stdout.write(f'  {token.name}', ending=' ')

            # ── Last.fm tag.getinfo ────────────────────────────────────────
            if api_key and not do_wikipedia and not do_tracks and not do_youtube:
                tag_data = _lastfm_tag(token.name, api_key)
                if tag_data:
                    raw_desc  = tag_data.get('wiki', {}).get('content', '') or \
                                tag_data.get('wiki', {}).get('summary', '')
                    desc      = _clean_html(raw_desc)
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
                    self.stdout.write('lfm✓', ending=' ')

            # ── Last.fm top tracks ─────────────────────────────────────────
            if do_tracks and api_key:
                if force or not token.top_tracks_json:
                    tracks = _lastfm_top_tracks(token.name, api_key)
                    if tracks:
                        if not dry:
                            token.top_tracks_json = tracks
                        changed = True
                        self.stdout.write(f'tracks({len(tracks)})✓', ending=' ')
                    else:
                        self.stdout.write('tracks–', ending=' ')

            # ── Wikipedia ─────────────────────────────────────────────────
            if do_wikipedia:
                wp = _wikipedia_summary(token.name)
                if wp:
                    extract = wp.get('extract', '')
                    # Description
                    short = wp.get('description', '') or ''
                    desc_candidate = extract[:800] if len(extract) > len(short) else short
                    if desc_candidate and (force or not token.description):
                        if not dry:
                            token.description = desc_candidate[:2000]
                        changed = True
                    # Origin year
                    year = _year_from_text(extract)
                    if year and (force or not token.origin_year):
                        if not dry:
                            token.origin_year = year
                        changed = True
                    # Derived from
                    if not token.derived_from or force:
                        parent_name = _derived_from_text(extract, known_names - {token.name})
                        if parent_name:
                            parent_obj = next((t for t in tokens if t.name == parent_name), None)
                            if parent_obj and parent_obj.pk and not dry:
                                token.derived_from = parent_obj
                            if parent_name:
                                changed = True
                    # Wikipedia URL → store on token via TokenSource
                    wp_url = (wp.get('content_urls') or {}).get('desktop', {}).get('page', '')
                    if wp_url and not dry:
                        TokenSource.objects.update_or_create(
                            token=token, source='wikipedia',
                            defaults={
                                'source_name': wp.get('_title', token.name),
                                'source_url':  wp_url,
                                'confidence':  'derived',
                            },
                        )
                    yr_str = f'~{year}' if year else '?'
                    self.stdout.write(f'wp({yr_str})✓', ending=' ')
                else:
                    self.stdout.write('wp–', ending=' ')

            # ── MusicBrainz ───────────────────────────────────────────────
            if not skip_mb and not do_tracks and not do_wikipedia and not do_youtube:
                mb = _mb_genre(token.name)
                if mb:
                    if not dry:
                        TokenSource.objects.get_or_create(
                            token=token, source='musicbrainz',
                            defaults={
                                'source_name': mb.get('name', token.name),
                                'confidence':  'verified',
                            },
                        )
                    self.stdout.write('mb✓', ending=' ')

            # ── YouTube overview video ────────────────────────────────────
            if do_youtube and yt_key:
                if force or not token.youtube_video_id:
                    vid = _youtube_search_video(f'{token.name} genre music mix', yt_key)
                    if vid:
                        if not dry:
                            token.youtube_video_id = vid
                        changed = True
                        self.stdout.write(f'yt✓', ending=' ')
                    else:
                        self.stdout.write('yt–', ending=' ')

            # ── BPM / energy hints ────────────────────────────────────────
            hint = _BPM_HINTS.get(token.name)
            if hint and not dry:
                bmin, bmax, energy = hint
                if not token.bpm_min:
                    token.bpm_min = bmin; changed = True
                if not token.bpm_max:
                    token.bpm_max = bmax; changed = True
                if not token.energy:
                    token.energy  = energy; changed = True

            if changed and not dry:
                token.save()
                updated += 1
            elif not changed:
                skipped += 1

            self.stdout.write('')  # newline

        self.stdout.write(self.style.SUCCESS(
            f'Tokens — {updated} updated, {skipped} unchanged'
        ))

        # ── Compound genre enrichment ──────────────────────────────────────
        if not do_cmpd_tracks and not do_cmpd_yt:
            return

        compounds = list(
            CompoundGenre.objects
            .prefetch_related('tokens')
            .order_by('-track_count')
        )
        if limit:
            compounds = compounds[:limit]
        self.stdout.write(f'\nEnriching {len(compounds)} compound genres…')

        c_updated = c_skipped = 0

        for compound in compounds:
            token_names = [t.name for t in compound.tokens.all()]
            if not token_names:
                continue
            self.stdout.write(f'  {compound.name}', ending=' ')
            c_changed = False

            if do_cmpd_tracks and api_key:
                if force or not compound.top_tracks_json:
                    # Use stored lastfm_tag if available, otherwise search
                    if compound.lastfm_tag:
                        tracks = _lastfm_top_tracks(compound.lastfm_tag, api_key)
                        found_tag = compound.lastfm_tag
                    else:
                        found_tag, tracks = _compound_lfm_search(token_names, api_key)
                    if tracks:
                        if not dry:
                            compound.top_tracks_json = tracks
                            if found_tag and not compound.lastfm_tag:
                                compound.lastfm_tag = found_tag
                        c_changed = True
                        self.stdout.write(f'tracks({len(tracks)})✓', ending=' ')
                    else:
                        self.stdout.write('tracks–', ending=' ')

            if do_cmpd_yt and yt_key:
                if force or not compound.youtube_video_id:
                    # Build a human-readable query from the stored lastfm_tag or token names
                    query_name = compound.lastfm_tag or ' '.join(token_names)
                    vid = _youtube_search_video(f'{query_name} genre music mix', yt_key)
                    if vid:
                        if not dry:
                            compound.youtube_video_id = vid
                        c_changed = True
                        self.stdout.write('yt✓', ending=' ')
                    else:
                        self.stdout.write('yt–', ending=' ')

            if c_changed and not dry:
                compound.save()
                c_updated += 1
            else:
                c_skipped += 1

            self.stdout.write('')

        self.stdout.write(self.style.SUCCESS(
            f'Compounds — {c_updated} updated, {c_skipped} unchanged'
        ))
