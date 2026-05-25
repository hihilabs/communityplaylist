"""
Social auto-posting for Community Playlist.

Handles Bluesky (AT Protocol, no external deps), Discord (webhooks),
and Buffer (queued publishing — YouTube Community, Instagram, Facebook,
TikTok, LinkedIn, Twitter/X) for board topics, Free & Trade offerings,
new approved events, and promoter profiles.

Entry points:
  post_topic(topic)         — board topic → Bluesky + Discord + Buffer (FB/Threads)
  post_offering(offering)   — Free & Trade item → Bluesky + Discord + Buffer
  post_event_discord(event) — new approved event → Discord only (no Buffer — too frequent)
  post_promoter(promoter)   — profile blast → Bluesky + Discord + Buffer
                              max 2/day via daily cap; trigger on is_verified or shop sync
  bluesky_events_digest()   — called by bluesky_digest management command;
                              handles 27-post split-by-category logic

Buffer config:
  Only BUFFER_ACCESS_TOKEN needed in settings — channel IDs hardwired in social.py.
  YouTube: add channel ID to BUFFER_CHANNELS after connecting UCiwtsacGi0MUuHzBzUQR7gA in Buffer.
"""
import json
import re
import time
import unicodedata
import urllib.parse
import urllib.request
import urllib.error
from datetime import datetime, timezone as dt_tz

BSKY_HOST = 'https://bsky.social'
CP_BASE   = 'https://communityplaylist.com'
LOGO      = 'https://hihi.communityplaylist.com/files/timeline_files/store_file6809b5ed4135d-community_playlist_site_logo_2025.png'

# Discord embed colors by content type
COLORS = {
    'general':   0x2a2a2a,
    'aid':       0x4caf50,
    'announce':  0xddaa33,
    'question':  0x8888ff,
    'offer':     0x4caf50,
    'give':      0x4caf50,
    'trade':     0x6699dd,
    'iso':       0xddaa33,
    'event':     0xff6b35,
}

# Category → filtered homepage link + hashtag
EVENT_CATS = {
    'music':  ('/?cat=music',  '#PDXMusic'),
    'arts':   ('/?cat=arts',   '#PDXArts'),
    'food':   ('/?cat=food',   '#PDXFood'),
    'bike':   ('/?cat=bike',   '#PDXBike'),
    'fund':   ('/?cat=fund',   '#PDXFundraiser'),
    'hybrid': ('/?cat=hybrid', '#PDXEvents'),
    '':       ('/',            '#PDXEvents'),
}

BOARD_TAGS = {
    'general':  '#PDXCommunity #Portland',
    'aid':      '#PDXAid #MutualAid #Portland',
    'announce': '#PDX #Portland',
    'question': '#PDXCommunity #Portland',
    'offer':    '#PDXFree #BuyNothingPDX #Portland',
}


# ── Helpers ───────────────────────────────────────────────────────────────────

def _event_handles(event, platform):
    """
    Collect @mention strings from artists + promoters linked to an event.
    Returns up to 5 handles total, deduped.
    platform: 'instagram' → ['@heavysetups', ...]
              'bluesky'   → ['@name.bsky.social', ...]
    """
    seen = set()
    handles = []
    field = 'instagram' if platform == 'instagram' else 'bluesky'
    sources = list(
        event.artists.exclude(**{field: ''}).values_list(field, flat=True)[:3]
    ) + list(
        event.promoters.exclude(**{field: ''}).values_list(field, flat=True)[:3]
    )
    for h in sources:
        h = h.strip().lstrip('@')
        if not h or h in seen:
            continue
        seen.add(h)
        if platform == 'bluesky' and '.' not in h:
            h = f'{h}.bsky.social'
        handles.append(f'@{h}')
        if len(handles) >= 5:
            break
    return handles


# Short-circuit overrides — genres where the slug would be wrong/ugly
_GENRE_OVERRIDES = {
    'r&b':   '#RnB',
    'j-r&b': '#JRnB',
}

# Aliases appended alongside the full tag for discoverability
_GENRE_ALIASES = {
    'drum and bass': '#DnB',
    'drum & bass':   '#DnB',
    'dnb':           '#DrumAndBass',
    'dubstep':       '#Dub',
}


def _slugify_tag(text):
    """'Drum & Bass' → '#DrumAndBass #DnB'  (& → and, accents stripped, CamelCase)"""
    key = text.lower().strip()
    if key in _GENRE_OVERRIDES:
        return _GENRE_OVERRIDES[key]
    norm = unicodedata.normalize('NFKD', text).encode('ascii', 'ignore').decode()
    norm = re.sub(r'&', ' and ', norm)
    norm = re.sub(r'[^a-zA-Z0-9 ]', '', norm)
    tag   = '#' + ''.join(w.capitalize() for w in norm.split() if w)
    alias = _GENRE_ALIASES.get(key)
    return f'{tag} {alias}' if alias else tag


def _title_tags(title, max_words=3):
    """'Techno Night at the Crystal' → '#TechnoNight #Crystal'  (skip short/common words)"""
    skip = {'a','an','the','at','in','on','of','and','or','for','to','with','by','from','&'}
    words = [w for w in re.findall(r"[a-zA-Z0-9']+", title) if w.lower() not in skip and len(w) > 2]
    return ' '.join(_slugify_tag(w) for w in words[:max_words])


def _venue_tag(location):
    """Extract venue name (first segment before comma) → hashtag."""
    if not location:
        return ''
    name = location.split(',')[0].strip()
    return _slugify_tag(name) if name else ''


# ── Bluesky low-level ─────────────────────────────────────────────────────────

def _bsky_post(path, payload, token=None):
    headers = {'Content-Type': 'application/json'}
    if token:
        headers['Authorization'] = f'Bearer {token}'
    req = urllib.request.Request(
        f'{BSKY_HOST}/xrpc/{path}',
        data=json.dumps(payload).encode(),
        headers=headers,
        method='POST',
    )
    with urllib.request.urlopen(req, timeout=15) as r:
        return json.loads(r.read())


def _bsky_session():
    from django.conf import settings
    handle   = getattr(settings, 'BLUESKY_HANDLE', '')
    password = getattr(settings, 'BLUESKY_APP_PASSWORD', '')
    if not handle or not password:
        return None, None
    data = _bsky_post('com.atproto.server.createSession',
                      {'identifier': handle, 'password': password})
    return data['accessJwt'], data['did']


def _bsky_upload_blob(image_url, token):
    try:
        req = urllib.request.Request(image_url,
            headers={'User-Agent': 'CommunityPlaylist/1.0 (communityplaylist.com)'})
        with urllib.request.urlopen(req, timeout=15) as r:
            img_data = r.read()
            ctype = r.headers.get('Content-Type', 'image/jpeg').split(';')[0]
        upload = urllib.request.Request(
            f'{BSKY_HOST}/xrpc/com.atproto.repo.uploadBlob',
            data=img_data,
            headers={'Content-Type': ctype, 'Authorization': f'Bearer {token}'},
            method='POST',
        )
        with urllib.request.urlopen(upload, timeout=20) as r:
            return json.loads(r.read()).get('blob')
    except Exception:
        return None


def _bsky_facets(text, links=(), hashtags=()):
    """
    links    = list of url strings that appear literally in text
    hashtags = list of '#Tag' strings that appear literally in text
    """
    tb = text.encode('utf-8')
    facets = []
    for url in links:
        b = url.encode('utf-8')
        idx = tb.find(b)
        if idx < 0:
            continue
        facets.append({
            '$type': 'app.bsky.richtext.facet',
            'index': {'byteStart': idx, 'byteEnd': idx + len(b)},
            'features': [{'$type': 'app.bsky.richtext.facet#link', 'uri': url}],
        })
    for tag in hashtags:
        b = tag.encode('utf-8')
        idx = tb.find(b)
        if idx < 0:
            continue
        facets.append({
            '$type': 'app.bsky.richtext.facet',
            'index': {'byteStart': idx, 'byteEnd': idx + len(b)},
            'features': [{'$type': 'app.bsky.richtext.facet#tag',
                          'tag': tag.lstrip('#')}],
        })
    return facets or None


def _bsky_create(token, did, text, facets=None, embed=None, reply_ref=None):
    record = {
        '$type':     'app.bsky.feed.post',
        'text':      text[:300],
        'createdAt': datetime.now(dt_tz.utc).strftime('%Y-%m-%dT%H:%M:%S.000Z'),
        'langs':     ['en-US'],
    }
    if facets:
        record['facets'] = facets
    if embed:
        record['embed'] = embed
    if reply_ref:
        record['reply'] = reply_ref
    result = _bsky_post('com.atproto.repo.createRecord', {
        'repo': did, 'collection': 'app.bsky.feed.post', 'record': record,
    }, token=token)
    return result.get('uri', ''), result.get('cid', '')


# ── Discord low-level ─────────────────────────────────────────────────────────

def _discord_send(webhook_url, payload):
    if not webhook_url:
        return False
    try:
        req = urllib.request.Request(
            webhook_url,
            data=json.dumps(payload).encode(),
            headers={'Content-Type': 'application/json'},
            method='POST',
        )
        with urllib.request.urlopen(req, timeout=10):
            return True
    except Exception as e:
        print(f'[Discord] send failed: {e}')
        return False


# ── Board topic posting ────────────────────────────────────────────────────────

def post_topic(topic):
    """Post a board topic to Bluesky, Discord, and Buffer. Returns (bsky_ok, discord_ok, buffer_ok)."""
    return (
        _post_topic_bluesky(topic),
        _post_topic_discord(topic),
        post_buffer_topic(topic),
    )


def _post_topic_bluesky(topic):
    try:
        token, did = _bsky_session()
        if not token:
            return False

        url  = f'{CP_BASE}{topic.get_absolute_url()}'
        tags = BOARD_TAGS.get(topic.category, '#PDXCommunity #Portland')
        body_preview = (topic.body or '')[:180].strip()
        if len(topic.body or '') > 180:
            body_preview += '…'

        tag_list = tags.split()
        text = f'💬 {topic.title}\n\n{body_preview}\n\n{url}\n\n{tags}'
        text = text[:300]

        facets = _bsky_facets(text, links=[url], hashtags=tag_list)

        embed = {
            '$type': 'app.bsky.embed.external',
            'external': {
                'uri':         url,
                'title':       topic.title,
                'description': (topic.body or '')[:200],
            },
        }
        _bsky_create(token, did, text, facets=facets, embed=embed)
        return True
    except Exception as e:
        print(f'[Bluesky] topic post failed: {e}')
        return False


def _post_topic_discord(topic):
    from django.conf import settings
    webhook = getattr(settings, 'DISCORD_WEBHOOK_BOARD', '')
    if not webhook:
        return False

    cat_labels = {
        'general': 'General', 'aid': '🌹 Aid & Mutual Aid',
        'announce': '📢 Announcement', 'question': '❓ Question',
        'offer': '🎁 Free & Trade',
    }
    url   = f'{CP_BASE}{topic.get_absolute_url()}'
    color = COLORS.get(topic.category, 0x2a2a2a)
    desc  = (topic.body or '')[:400]

    payload = {
        # thread_name creates a new Forum thread when the webhook targets a Forum channel;
        # text channel webhooks silently ignore it.
        'thread_name': topic.title[:100],
        'embeds': [{
            'title':       topic.title,
            'url':         url,
            'description': desc,
            'color':       color,
            'author':      {'name': f'Community Board — {cat_labels.get(topic.category, topic.category)}'},
            'footer':      {'text': f'Posted by {topic.author_name} · communityplaylist.com',
                            'icon_url': LOGO},
            'timestamp':   topic.created_at.strftime('%Y-%m-%dT%H:%M:%SZ'),
        }],
    }
    return _discord_send(webhook, payload)


# ── Free & Trade offering posting ─────────────────────────────────────────────

def post_offering(offering):
    """Post a Free & Trade offering to Bluesky, Discord, and Buffer."""
    return (
        _post_offering_bluesky(offering),
        _post_offering_discord(offering),
        post_buffer_offering(offering),
    )


def _post_offering_bluesky(offering):
    try:
        token, did = _bsky_session()
        if not token:
            return False

        url  = f'{CP_BASE}{offering.get_absolute_url()}'
        hood = f' · {offering.neighborhood.name}' if offering.neighborhood else ''
        cat_icons = {'give': '🎁 FREE', 'trade': '🔄 TRADE', 'iso': '🔍 ISO'}
        cat_label = cat_icons.get(offering.category, '🎁')
        tags = '#PDXFree #BuyNothingPDX #Portland'
        if offering.neighborhood:
            tags += f' {_slugify_tag(offering.neighborhood.name)}'

        body_preview = (offering.body or '')[:140].strip()
        tag_list = [t for t in tags.split() if t.startswith('#')]

        text = f'{cat_label} — {offering.title}{hood}\n\n{body_preview}\n\n{url}\n\n{tags}'
        text = text[:300]

        facets = _bsky_facets(text, links=[url], hashtags=tag_list)
        thumb = None
        if offering.photo:
            thumb = _bsky_upload_blob(f'{CP_BASE}{offering.photo.url}', token)

        embed = {
            '$type': 'app.bsky.embed.external',
            'external': {
                'uri':         url,
                'title':       f'{cat_label} — {offering.title}',
                'description': (offering.body or '')[:200],
            },
        }
        if thumb:
            embed['external']['thumb'] = thumb

        _bsky_create(token, did, text, facets=facets, embed=embed)
        return True
    except Exception as e:
        print(f'[Bluesky] offering post failed: {e}')
        return False


def _post_offering_discord(offering):
    from django.conf import settings
    webhook = getattr(settings, 'DISCORD_WEBHOOK_BOARD', '')
    if not webhook:
        return False

    url   = f'{CP_BASE}{offering.get_absolute_url()}'
    color = COLORS.get(offering.category, 0x4caf50)
    cat_labels = {'give': '🎁 Free — Take It', 'trade': '🔄 Trade / Swap', 'iso': '🔍 In Search Of'}
    hood  = offering.neighborhood.name if offering.neighborhood else 'Portland'
    img   = f'{CP_BASE}{offering.photo.url}' if offering.photo else None

    embed = {
        'title':       f'{cat_labels.get(offering.category, "Offering")} — {offering.title}',
        'url':         url,
        'description': (offering.body or '')[:400],
        'color':       color,
        'author':      {'name': f'🎁 Free & Trade — {hood}'},
        'footer':      {'text': f'Posted by {offering.author_name} · communityplaylist.com',
                        'icon_url': LOGO},
        'timestamp':   offering.created_at.strftime('%Y-%m-%dT%H:%M:%SZ'),
    }
    if img:
        embed['thumbnail'] = {'url': img}
    if offering.contact_hint:
        embed['fields'] = [{'name': '📬 How to connect', 'value': offering.contact_hint, 'inline': False}]

    return _discord_send(webhook, {'embeds': [embed]})


# ── New approved event → Discord ──────────────────────────────────────────────

def post_event_discord(event):
    """Rich Discord embed for a newly approved event."""
    from django.conf import settings
    from django.utils.timezone import localtime
    webhook = getattr(settings, 'DISCORD_WEBHOOK_EVENTS', '')
    if not webhook:
        return False

    url    = f'{CP_BASE}/events/{event.slug}/'
    genres = ', '.join(event.genres.values_list('name', flat=True)[:4]) or 'various'
    start  = localtime(event.start_date).strftime('%a %b %-d @ %-I:%M %p')
    cost   = 'FREE' if event.is_free else (event.price_info or 'Paid')
    img    = f'{CP_BASE}{event.photo.url}' if event.photo else LOGO
    vtag   = _venue_tag(event.location)
    ttag   = _title_tags(event.title)
    cat_path, cat_hashtag = EVENT_CATS.get(event.category or '', EVENT_CATS[''])
    hood   = getattr(event, 'neighborhood', '') or ''
    ig_handles = ' '.join(_event_handles(event, 'instagram'))
    footer_tags = f'{ttag} {vtag} {cat_hashtag} #PDX'
    if ig_handles:
        footer_tags = f'{ig_handles}  {footer_tags}'

    embed = {
        'title':       event.title,
        'url':         url,
        'description': (event.description or '')[:300],
        'color':       0xff6b35,
        'thumbnail':   {'url': img},
        'fields': [
            {'name': '📅 When',    'value': start,                'inline': True},
            {'name': '📍 Where',   'value': event.location[:80],  'inline': True},
            {'name': '🎵 Genre',   'value': genres,               'inline': True},
            {'name': '💰 Cost',    'value': cost,                 'inline': True},
        ],
        'author':  {'name': '🌹 New Event — Community Playlist'},
        'footer':  {'text': f'{footer_tags}\ncommunityplaylist.com',
                    'icon_url': LOGO},
        'timestamp': event.created_at.strftime('%Y-%m-%dT%H:%M:%SZ'),
    }
    if hood:
        embed['fields'].append({'name': '🏘 Neighborhood', 'value': hood, 'inline': True})
    return _discord_send(webhook, {'embeds': [embed]})


# ── Discord Scheduled Events (native Events tab, requires bot token) ──────────

def create_discord_scheduled_event(event):
    """
    Creates a native Discord Scheduled Event (appears in the Events tab).
    Requires DISCORD_BOT_TOKEN and DISCORD_GUILD_ID in settings.
    Bot must have MANAGE_EVENTS permission in the server.
    Returns True on success.
    """
    from django.conf import settings
    token    = getattr(settings, 'DISCORD_BOT_TOKEN', '')
    guild_id = getattr(settings, 'DISCORD_GUILD_ID', '')
    if not token or not guild_id:
        return False

    try:
        url   = f'{CP_BASE}/events/{event.slug}/'
        desc  = (event.description or '')[:1000]
        if url not in desc:
            desc = f'{desc}\n\n{url}'.strip()

        # Discord requires start_time in ISO8601; end_time optional but recommended
        start_iso = event.start_date.strftime('%Y-%m-%dT%H:%M:%S+00:00')
        end_iso   = None
        if hasattr(event, 'end_date') and event.end_date:
            end_iso = event.end_date.strftime('%Y-%m-%dT%H:%M:%S+00:00')

        payload = {
            'name':                event.title[:100],
            'privacy_level':       2,          # GUILD_ONLY (required value)
            'scheduled_start_time': start_iso,
            'description':         desc[:1000],
            'entity_type':         3,          # EXTERNAL (location-based, not a voice channel)
            'entity_metadata':     {'location': (event.location or 'Portland, OR')[:100]},
        }
        if end_iso:
            payload['scheduled_end_time'] = end_iso

        # Optionally attach event cover image
        if event.photo:
            try:
                img_url = f'{CP_BASE}{event.photo.url}'
                req = urllib.request.Request(img_url,
                    headers={'User-Agent': 'CommunityPlaylist/1.0'})
                with urllib.request.urlopen(req, timeout=10) as r:
                    import base64
                    ctype = r.headers.get('Content-Type', 'image/jpeg').split(';')[0]
                    img_b64 = base64.b64encode(r.read()).decode()
                payload['image'] = f'data:{ctype};base64,{img_b64}'
            except Exception:
                pass  # image optional, skip on error

        api_url = f'https://discord.com/api/v10/guilds/{guild_id}/scheduled-events'
        req = urllib.request.Request(
            api_url,
            data=json.dumps(payload).encode(),
            headers={
                'Content-Type':  'application/json',
                'Authorization': f'Bot {token}',
            },
            method='POST',
        )
        with urllib.request.urlopen(req, timeout=15) as r:
            result = json.loads(r.read())
            return bool(result.get('id'))
    except Exception as e:
        print(f'[Discord] scheduled event creation failed: {e}')
        return False


# ── Events digest helpers (used by bluesky_digest command) ────────────────────

def events_by_category(events):
    """Split a queryset into dict of {category: [events]}."""
    buckets = {}
    for e in events:
        cat = e.category or 'music'
        buckets.setdefault(cat, []).append(e)
    return buckets


def build_event_batch_posts(events, daily_limit=27):
    """
    Given a queryset of today's events, return a list of (header_text, [event_texts]) tuples.
    If total <= daily_limit: one batch.
    If total > daily_limit: split by category, one batch per category.
    Each batch is posted as a Bluesky thread (header + per-event replies).
    """
    from django.utils.timezone import localtime

    cat_labels = {
        'music': '🎵 Music',
        'arts':  '🎨 Arts & Comedy',
        'food':  '🍎 Food & Community',
        'bike':  '🚲 Bike',
        'fund':  '💛 Fundraisers',
        'hybrid':'✦ Hybrid',
        '':      '🌹 Events',
    }

    event_list = list(events)
    total = len(event_list)

    if total <= daily_limit:
        buckets = {'all': event_list}
    else:
        buckets = events_by_category(event_list)

    batches = []
    for cat, cat_events in buckets.items():
        if not cat_events:
            continue
        if cat == 'all':
            label = '🌹 Today in Portland'
            cat_path, cat_tag = '/', '#PDXEvents'
        else:
            label = f'{cat_labels.get(cat, "Events")} Tonight'
            cat_path, cat_tag = EVENT_CATS.get(cat, ('/', '#PDXEvents'))

        link = f'{CP_BASE}{cat_path}'
        from django.utils.timezone import localtime as _lt
        from django.utils import timezone as _tz
        date_str = _lt(_tz.now()).strftime('%a %b %-d')
        header = f'{label} — {date_str}\n{link}\n\n{cat_tag} #Portland #PDX'

        event_texts = []
        for e in cat_events:
            start  = _lt(e.start_date).strftime('%-I:%M %p')
            genres = ', '.join(e.genres.values_list('name', flat=True)[:2]) or 'various'
            cost   = 'FREE' if e.is_free else (e.price_info or 'Paid')
            vtag    = _venue_tag(e.location)
            ttag    = _title_tags(e.title, max_words=2)
            eurl    = f'{CP_BASE}/events/{e.slug}/'
            loc     = e.location[:50]
            handles = _event_handles(e, 'bluesky')
            handle_line = ('  '.join(handles) + '\n') if handles else ''
            text    = (
                f'{e.title}\n'
                f'📅 {start}  📍 {loc}\n'
                f'🎵 {genres}  {cost}\n'
                f'{handle_line}{vtag}  {ttag}\n{eurl}'
            )
            event_texts.append((text[:300], eurl, [vtag, ttag] + handles))

        batches.append((header, link, event_texts))

    return batches


# ── Promoter profile blast ─────────────────────────────────────────────────────

def _hex_to_discord_int(hex_color, default=0xff6b35):
    try:
        return int((hex_color or '').lstrip('#'), 16)
    except ValueError:
        return default


def _bsky_post_text(text, hashtags=()):
    """Post plain text to Bluesky. Returns True on success."""
    try:
        token, did = _bsky_session()
        if not token:
            return False
        facets = _bsky_facets(text, hashtags=hashtags)
        uri, _ = _bsky_create(token, did, text, facets=facets or None)
        return bool(uri)
    except Exception as e:
        print(f'[Bluesky/CTA] {e}')
        return False


def _post_promoter_bluesky(promoter):
    try:
        token, did = _bsky_session()
        if not token:
            return False

        url      = f'{CP_BASE}{promoter.get_absolute_url()}'
        genres   = list(promoter.genres.values_list('name', flat=True)[:5])
        bio_prev = (promoter.bio or '')[:180].strip()
        if len(promoter.bio or '') > 180:
            bio_prev += '…'

        type_icon = promoter.get_type_icons()

        listings   = promoter.record_listings.filter(is_available=True)
        shop_count = listings.count()
        shop_line  = ''
        if shop_count:
            formats  = list(listings.exclude(format='').values_list('format', flat=True).distinct()[:3])
            pay_opts = []
            if promoter.sol_wallet:             pay_opts.append('SOL')
            if promoter.shop_pay_in_person:     pay_opts.append('in person')
            if promoter.shop_open_to_trade:     pay_opts.append('trades')
            fmt_str  = ' · '.join(formats) if formats else 'Vinyl'
            pay_str  = ' / '.join(pay_opts)
            shop_line = f'\n🛒 {shop_count} records for sale ({fmt_str})'
            if pay_str:
                shop_line += f' — {pay_str}'

        live_line    = f'\n🔴 LIVE on Twitch right now' if promoter.is_live and promoter.twitch else ''
        genre_tags   = ' '.join(_slugify_tag(g) for g in genres)
        tag_str      = f'{genre_tags} #PDX #Portland'.strip()

        text = (
            f'{type_icon} {promoter.name}\n\n'
            f'{bio_prev}'
            f'{shop_line}'
            f'{live_line}\n\n'
            f'{url}\n\n'
            f'{tag_str}'
        )[:300]

        tag_list = [t for t in tag_str.split() if t.startswith('#')]
        facets   = _bsky_facets(text, links=[url], hashtags=tag_list)

        thumb = None
        if promoter.photo:
            thumb = _bsky_upload_blob(f'{CP_BASE}{promoter.photo.url}', token)

        embed = {
            '$type': 'app.bsky.embed.external',
            'external': {
                'uri':         url,
                'title':       f'{promoter.name} — Community Playlist',
                'description': (promoter.bio or '')[:200],
            },
        }
        if thumb:
            embed['external']['thumb'] = thumb

        _bsky_create(token, did, text, facets=facets, embed=embed)
        return True
    except Exception as e:
        print(f'[Bluesky] promoter post failed: {e}')
        return False


def _post_promoter_discord(promoter):
    from django.conf import settings
    webhook = (getattr(settings, 'DISCORD_WEBHOOK_PROFILES', '')
               or getattr(settings, 'DISCORD_WEBHOOK_EVENTS', ''))
    if not webhook:
        return False

    url       = f'{CP_BASE}{promoter.get_absolute_url()}'
    color     = _hex_to_discord_int(promoter.brand_color)
    type_line = promoter.get_types_display()
    img       = f'{CP_BASE}{promoter.photo.url}' if promoter.photo else LOGO

    socials = []
    if promoter.instagram:  socials.append(f'[IG](https://instagram.com/{promoter.instagram})')
    if promoter.soundcloud: socials.append(f'[SC](https://soundcloud.com/{promoter.soundcloud})')
    if promoter.mixcloud:   socials.append(f'[MC](https://mixcloud.com/{promoter.mixcloud}/)')
    if promoter.spotify:    socials.append(f'[Spotify]({promoter.spotify})')
    if promoter.bandcamp:   socials.append(f'[Bandcamp]({promoter.bandcamp})')
    if promoter.youtube:    socials.append(f'[YouTube]({promoter.youtube})')
    if promoter.twitch:     socials.append(f'[Twitch](https://twitch.tv/{promoter.twitch})')
    if promoter.bluesky:    socials.append(f'[Bsky](https://bsky.app/profile/{promoter.bluesky})')
    if promoter.discord:    socials.append(f'[Discord]({promoter.discord})')
    if promoter.website:    socials.append(f'[Website]({promoter.website})')

    listings   = promoter.record_listings.filter(is_available=True)
    shop_count = listings.count()
    shop_text  = None
    if shop_count:
        formats   = list(listings.exclude(format='').values_list('format', flat=True).distinct()[:4])
        fmt_str   = ' · '.join(formats) if formats else 'Vinyl'
        pay_parts = []
        if promoter.sol_wallet:             pay_parts.append('◎ SOL')
        if promoter.shop_pay_in_person:     pay_parts.append('🤝 In Person')
        if promoter.shop_open_to_trade:     pay_parts.append('🔄 Trade')
        pay_str  = '  '.join(pay_parts)
        shop_text = f'{shop_count} records for sale — {fmt_str}'
        if pay_str:
            shop_text += f'\n{pay_str}'

    genres = ', '.join(promoter.genres.values_list('name', flat=True)[:6]) or None

    fields = []
    if genres:
        fields.append({'name': '🎵 Genres',    'value': genres,                    'inline': True})
    if type_line:
        fields.append({'name': '🏷 Type',      'value': type_line,                 'inline': True})
    if socials:
        fields.append({'name': '🔗 Links',     'value': '  ·  '.join(socials[:6]), 'inline': False})
    if shop_text:
        fields.append({'name': '🛒 Record Shop', 'value': shop_text,               'inline': False})
    if promoter.is_live and promoter.twitch:
        fields.append({'name': '📺 Live Now',
                       'value': f'[twitch.tv/{promoter.twitch}](https://twitch.tv/{promoter.twitch})',
                       'inline': False})

    verified_mark = ' ✓' if promoter.is_verified else ''
    payload = {
        'embeds': [{
            'title':       f'{promoter.name}{verified_mark}',
            'url':         url,
            'description': (promoter.bio or '')[:300],
            'color':       color,
            'thumbnail':   {'url': img},
            'fields':      fields,
            'author':      {'name': f'🌹 Community Playlist — {type_line}'},
            'footer':      {'text': 'communityplaylist.com', 'icon_url': LOGO},
            'timestamp':   promoter.created_at.strftime('%Y-%m-%dT%H:%M:%SZ'),
        }],
    }
    return _discord_send(webhook, payload)


def post_promoter(promoter):
    """Blast a promoter profile to Bluesky, Discord, and Buffer.

    Trigger on is_verified transitioning True, or after a record shop sync
    adds new listings. Returns (bsky_ok, discord_ok, buffer_ok).
    """
    results = (
        _post_promoter_bluesky(promoter),
        _post_promoter_discord(promoter),
        post_buffer_promoter(promoter),
    )
    if any(results):
        from django.utils import timezone
        promoter.last_promoted_at = timezone.now()
        promoter.save(update_fields=['last_promoted_at'])
    return results


# ── Buffer (queued publishing — FB, Instagram, Threads, YouTube Community) ─────
#
# Uses Buffer's GraphQL API (v2 personal key tokens only — v1 is blocked).
# Channel IDs are hardwired; only BUFFER_ACCESS_TOKEN lives in settings.
# Add YouTube channel ID below once connected in Buffer dashboard.

BUFFER_GQL  = 'https://api.buffer.com/graphql'
BUFFER_DAILY_PROMOTER_LIMIT = 2  # max profile highlights queued per day

# Hardwired channel IDs (fetched 2026-05-22 via API)
BUFFER_CHANNELS = {
    'instagram': '6a10766c090476fb994aff0a',   # @community_playlist
    'facebook':  '6a107692090476fb994affaa',   # Community Playlist
    'threads':   '6a1077a7090476fb994b0473',   # @community_playlist
    # 'youtube': '<id>',                        # UCiwtsacGi0MUuHzBzUQR7gA — add after connecting in Buffer
}

# Required post-type metadata per channel
_BUFFER_META = {
    'instagram': {'instagram': {'type': 'post', 'shouldShareToFeed': True}},
    'facebook':  {'facebook':  {'type': 'post'}},
    'threads':   {'threads':   {'type': 'post'}},
}

_BUFFER_MUTATION = """
mutation CreatePost($input: CreatePostInput!) {
    createPost(input: $input) {
        __typename
        ... on PostActionSuccess { post { id status } }
        ... on UnexpectedError   { message }
        ... on InvalidInputError { message }
        ... on LimitReachedError { message }
    }
}
"""


def _buffer_post_channel(token, channel_key, text, image_urls=None):
    """Queue one post to a single Buffer channel. Returns True on success.

    image_urls: list of absolute image URLs (carousel if >1, single image if 1).
    Instagram requires at least one image — channel is skipped if none provided.
    """
    channel_id = BUFFER_CHANNELS.get(channel_key)
    if not channel_id:
        return False
    # Instagram requires an image
    if channel_key == 'instagram' and not image_urls:
        return False

    inp = {
        'channelId':      channel_id,
        'text':           text[:2000],
        'schedulingType': 'automatic',
        'mode':           'addToQueue',
        'metadata':       _BUFFER_META.get(channel_key, {}),
    }
    if image_urls:
        inp['assets'] = [{'image': {'url': u}} for u in image_urls]

    payload = json.dumps({'query': _BUFFER_MUTATION, 'variables': {'input': inp}}).encode()
    req = urllib.request.Request(
        BUFFER_GQL, data=payload,
        headers={'Content-Type': 'application/json', 'Authorization': f'Bearer {token}'},
        method='POST',
    )
    try:
        with urllib.request.urlopen(req, timeout=15) as r:
            result = json.loads(r.read())
        cp = result.get('data', {}).get('createPost', {})
        if cp.get('__typename') == 'PostActionSuccess':
            return True
        if cp.get('message'):
            print(f'[Buffer:{channel_key}] {cp["message"]}')
        return False
    except Exception as e:
        print(f'[Buffer:{channel_key}] request failed: {e}')
        return False


def _buffer_send(text, channels=None, image_url=None, image_urls=None):
    """Queue a post to Buffer. channels=None → all channels. Staggers calls by 0.5s.

    image_urls (list) takes priority over single image_url for carousel posts.
    """
    from django.conf import settings
    token = getattr(settings, 'BUFFER_ACCESS_TOKEN', '')
    if not token:
        return False

    urls    = image_urls or ([image_url] if image_url else None)
    targets = channels or list(BUFFER_CHANNELS.keys())
    results = []
    for i, ch in enumerate(targets):
        results.append(_buffer_post_channel(token, ch, text, image_urls=urls))
        if i < len(targets) - 1:
            time.sleep(0.5)
    return any(results)


def _buffer_promoter_quota_ok():
    """Return True if today's promoter highlight cap hasn't been reached."""
    try:
        from django.core.cache import cache
        from django.utils.timezone import now
        key = f'buffer_promoter_{now().date().isoformat()}'
        count = cache.get(key, 0)
        if count >= BUFFER_DAILY_PROMOTER_LIMIT:
            print(f'[Buffer] daily promoter limit ({BUFFER_DAILY_PROMOTER_LIMIT}) reached — skipping')
            return False
        cache.set(key, count + 1, timeout=86400)
        return True
    except Exception:
        return True  # don't block on cache errors


def post_buffer_promoter(promoter):
    """Queue a promoter highlight to Buffer (FB + Threads always; IG if photo exists).

    Capped at BUFFER_DAILY_PROMOTER_LIMIT per day — slow and steady.
    """
    if not _buffer_promoter_quota_ok():
        return False

    url      = f'{CP_BASE}{promoter.get_absolute_url()}'
    bio_prev = (promoter.bio or '')[:200].strip()
    if len(promoter.bio or '') > 200:
        bio_prev += '…'
    genre_tags   = ' '.join(_slugify_tag(g) for g in promoter.genres.values_list('name', flat=True)[:5])
    type_icon    = promoter.get_type_icons()
    listings     = promoter.record_listings.filter(is_available=True)
    shop_count   = listings.count()
    shop_line    = ''
    if shop_count:
        formats   = list(listings.exclude(format='').values_list('format', flat=True).distinct()[:3])
        pay_parts = []
        if promoter.sol_wallet:             pay_parts.append('◎ SOL')
        if promoter.shop_pay_in_person:     pay_parts.append('🤝 in person')
        if promoter.shop_open_to_trade:     pay_parts.append('🔄 trades')
        shop_line = f'\n🛒 {shop_count} records for sale — {" · ".join(formats) or "Vinyl"}'
        if pay_parts:
            shop_line += f'  ({" / ".join(pay_parts)})'

    socials = []
    if promoter.instagram:  socials.append(f'📷 @{promoter.instagram}')
    if promoter.soundcloud: socials.append(f'☁ SC/{promoter.soundcloud}')
    if promoter.mixcloud:   socials.append(f'🎛 MC/{promoter.mixcloud}')
    social_line = '\n' + '  ·  '.join(socials[:3]) if socials else ''

    text = (
        f'{type_icon} {promoter.name}\n\n'
        f'{bio_prev}'
        f'{social_line}'
        f'{shop_line}\n\n'
        f'{url}\n\n'
        f'{genre_tags} #PDX #Portland #CommunityPlaylist'
    )
    # Generate PIL social cards (hero + info + shop); fall back to raw photo
    image_urls = None
    try:
        from board.social_cards import generate_promoter_cards
        image_urls = generate_promoter_cards(promoter) or None
    except Exception as e:
        print(f'[Buffer] card generation failed: {e}')
    if not image_urls and promoter.photo:
        image_urls = [f'{CP_BASE}{promoter.photo.url}']

    return _buffer_send(text, image_urls=image_urls)


def post_buffer_offering(offering):
    """Queue a Free & Trade offering to FB + Threads (+ IG if photo)."""
    url       = f'{CP_BASE}{offering.get_absolute_url()}'
    cat_icons = {'give': '🎁 FREE', 'trade': '🔄 TRADE', 'iso': '🔍 ISO'}
    cat_label = cat_icons.get(offering.category, '🎁')
    hood      = f' · {offering.neighborhood.name}' if offering.neighborhood else ''
    body_prev = (offering.body or '')[:220].strip()

    text = (
        f'{cat_label} — {offering.title}{hood}\n\n'
        f'{body_prev}\n\n'
        f'{url}\n\n'
        f'#PDXFree #BuyNothingPDX #Portland'
    )
    img = f'{CP_BASE}{offering.photo.url}' if offering.photo else None
    return _buffer_send(text, image_url=img)


def post_buffer_topic(topic):
    """Queue a board topic to FB + Threads (no IG — text-only)."""
    url       = f'{CP_BASE}{topic.get_absolute_url()}'
    tags      = BOARD_TAGS.get(topic.category, '#PDXCommunity #Portland')
    body_prev = (topic.body or '')[:220].strip()
    if len(topic.body or '') > 220:
        body_prev += '…'

    text = f'💬 {topic.title}\n\n{body_prev}\n\n{url}\n\n{tags}'
    # Topics are text-only → skip Instagram
    return _buffer_send(text, channels=['facebook', 'threads'])
