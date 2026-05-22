"""
events/discord_bot.py — CP Discord bot posting layer.

Uses the bot token (not webhooks) so we can post, edit, delete, and pin
messages across all CP channels programmatically.

Channels (set in .env):
  DISCORD_CHAN_EVENTS   — approved events, daily digest, happening-now alerts
  DISCORD_CHAN_TRADE    — Free & Trade board offerings
  DISCORD_CHAN_DROPS    — new artist tracks / mix releases / vinyl drops

All functions are fire-and-forget safe (exceptions are swallowed and logged).
"""
import json
import urllib.request
import urllib.error
from django.conf import settings

DISCORD_API = "https://discord.com/api/v10"

CAT_EMOJI = {
    "music":  "🎵", "arts":   "🎨", "bike":  "🚲",
    "fund":   "💙", "food":   "🍴", "hybrid": "⚡",
}
CAT_COLOR = {
    "music":  0xCC88FF, "arts":  0x66BBFF, "bike":  0x55DD55,
    "fund":   0x6699FF, "food":  0xDDAA33, "hybrid": 0xFF9944,
}

# ── Low-level HTTP ─────────────────────────────────────────────────────────────

def _token():
    return getattr(settings, "DISCORD_BOT_TOKEN", "")

def _chan(key):
    return getattr(settings, key, "")

def _post(path, payload):
    token = _token()
    if not token:
        return None
    data = json.dumps(payload).encode()
    req = urllib.request.Request(
        f"{DISCORD_API}{path}",
        data=data,
        headers={
            "Authorization": f"Bot {token}",
            "Content-Type":  "application/json",
            "User-Agent":    "CommunityPlaylist/1.0",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            return json.loads(r.read())
    except Exception as e:
        print(f"[discord_bot] POST {path} error: {e}")
        return None

def _patch(path, payload):
    token = _token()
    if not token:
        return None
    data = json.dumps(payload).encode()
    req = urllib.request.Request(
        f"{DISCORD_API}{path}",
        data=data,
        headers={
            "Authorization": f"Bot {token}",
            "Content-Type":  "application/json",
        },
        method="PATCH",
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            return json.loads(r.read())
    except Exception as e:
        print(f"[discord_bot] PATCH {path} error: {e}")
        return None

def _delete(path):
    token = _token()
    if not token:
        return
    req = urllib.request.Request(
        f"{DISCORD_API}{path}",
        headers={"Authorization": f"Bot {token}"},
        method="DELETE",
    )
    try:
        with urllib.request.urlopen(req, timeout=10):
            pass
    except Exception as e:
        print(f"[discord_bot] DELETE {path} error: {e}")

def _pin(channel_id, message_id):
    _post(f"/channels/{channel_id}/pins/{message_id}", {})

def _unpin(channel_id, message_id):
    _delete(f"/channels/{channel_id}/pins/{message_id}")

def _get_pins(channel_id):
    token = _token()
    if not token:
        return []
    req = urllib.request.Request(
        f"{DISCORD_API}/channels/{channel_id}/pins",
        headers={"Authorization": f"Bot {token}"},
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            return json.loads(r.read())
    except Exception:
        return []

def _post_to_channel(channel_id, payload):
    if not channel_id:
        return None
    return _post(f"/channels/{channel_id}/messages", payload)

# ── 1. New approved event announcement ────────────────────────────────────────

def post_event_approved(event):
    """
    Post a rich embed to #cp-events when an event is approved.
    Called from admin.py after status → approved.
    """
    chan = _chan("DISCORD_CHAN_EVENTS")
    if not chan:
        return

    site_url = getattr(settings, "SITE_URL", "https://communityplaylist.com")
    cat      = event.category or ""
    emoji    = CAT_EMOJI.get(cat, "📅")
    color    = CAT_COLOR.get(cat, 0xFF6B35)

    try:
        time_str = event.start_date.strftime("%-I:%M %p, %a %b %-d")
    except Exception:
        time_str = str(event.start_date)

    location = event.location or "Portland, OR"
    if event.neighborhood:
        location = f"{event.neighborhood} · {location}"

    desc_parts = []
    if event.description:
        desc_parts.append(event.description[:300].strip())
        if len(event.description) > 300:
            desc_parts.append("…")

    free_tag = "  🆓 **FREE**" if event.is_free else ""
    footer   = f"{location}{free_tag}"

    embed = {
        "title":       f"{emoji} {event.title}",
        "url":         f"{site_url}/events/{event.slug}/",
        "description": "\n".join(desc_parts) if desc_parts else None,
        "color":       color,
        "fields": [
            {"name": "🕐 When",  "value": time_str,  "inline": True},
            {"name": "📍 Where", "value": location[:100], "inline": True},
        ],
        "footer": {"text": "communityplaylist.com · PDX Events"},
    }

    # Add thumbnail if available
    try:
        if event.photo:
            embed["thumbnail"] = {"url": site_url + event.photo.url}
    except Exception:
        pass

    genres = [g.name for g in event.genres.all()[:5]]
    if genres:
        embed["fields"].append({"name": "🎼 Genres", "value": " · ".join(genres), "inline": False})

    content = f"**New event just dropped** — {emoji}"
    _post_to_channel(chan, {"content": content, "embeds": [embed]})


# ── 2. Free & Trade board offering ────────────────────────────────────────────

def post_trade_offering(offering):
    """
    Post to #cp-free-trade when someone lists something on the board.
    Called from board/views.py after Offering is created.
    """
    chan = _chan("DISCORD_CHAN_TRADE")
    if not chan:
        return

    site_url = getattr(settings, "SITE_URL", "https://communityplaylist.com")

    condition_emoji = {
        "give":  "🆓",
        "trade": "🔄",
        "iso":   "🙏",
    }.get(getattr(offering, "category", ""), "📦")

    title = getattr(offering, "title", str(offering))
    desc  = getattr(offering, "body", "") or ""
    hood_obj = getattr(offering, "neighborhood", None)
    hood  = hood_obj.name if hood_obj else "Portland"
    poster = getattr(offering, "author_name", None) or "Community"

    embed = {
        "title":       f"{condition_emoji} {title}",
        "description": desc[:400] if desc else None,
        "color":       0xDDAA33,
        "fields": [
            {"name": "📍 Area",   "value": hood,   "inline": True},
            {"name": "👤 Posted", "value": poster,  "inline": True},
        ],
        "footer": {"text": "Reply on the CP board → communityplaylist.com/board/"},
        "url":    f"{site_url}/board/",
    }

    cat_label = {"give": "Free pickup", "trade": "Trade offer", "iso": "ISO request"}.get(
        getattr(offering, "category", ""), "New listing"
    )
    content = f"**{cat_label}** on the board {condition_emoji}"
    _post_to_channel(chan, {"content": content, "embeds": [embed]})


# ── 3. New track / mix drop ───────────────────────────────────────────────────

def post_track_drop(track):
    """
    Post to #cp-drops when a new playlist track is added to an artist.
    Called from events/views.py or admin after track is approved/published.
    """
    chan = _chan("DISCORD_CHAN_DROPS")
    if not chan:
        return

    site_url = getattr(settings, "SITE_URL", "https://communityplaylist.com")
    artist   = getattr(track, "artist", None)
    title    = getattr(track, "title", "Untitled")
    source   = getattr(track, "source", "") or ""

    source_emoji = {"youtube": "▶️", "soundcloud": "☁️", "bandcamp": "🏕️",
                    "spotify": "💚", "mixcloud": "🌀"}.get(source.lower(), "🎵")

    artist_name = artist.name if artist else "Unknown Artist"
    artist_url  = f"{site_url}/artists/{artist.slug}/" if artist else site_url
    genres      = ([g.name for g in artist.genres.all()[:3]] if artist else [])

    embed = {
        "title":       f"{source_emoji} {title}",
        "url":         artist_url,
        "description": f"New drop from **{artist_name}**" + (f"\n_{' · '.join(genres)}_" if genres else ""),
        "color":       0xCC88FF,
        "footer":      {"text": "Stream on communityplaylist.com/player/"},
    }

    try:
        if artist and artist.photo:
            embed["thumbnail"] = {"url": site_url + artist.photo.url}
    except Exception:
        pass

    content = f"🎵 **New drop** just landed"
    _post_to_channel(chan, {"content": content, "embeds": [embed]})


# ── 4. Ko-fi supporter shoutout ───────────────────────────────────────────────

def post_kofi_shoutout(from_name, message, support_type, kofi_url, is_public=True):
    """
    Rich Ko-fi shoutout embed to #cp-events.
    Replaces the old webhook-based shoutout.
    """
    chan = _chan("DISCORD_CHAN_EVENTS")
    if not chan:
        return

    emoji = {"Subscription": "⭐", "Shop_Order": "🛒", "Commission": "🎨"}.get(support_type, "☕")
    label = {"Subscription": "subscribed", "Shop_Order": "placed a shop order",
             "Commission": "commissioned"}.get(support_type, "bought a coffee")

    desc = f"**{from_name}** just {label} on Ko-fi! {emoji}"
    if message and is_public:
        desc += f'\n\n> *"{message}"*'
    desc += f"\n\n[Support Community Playlist ☕]({kofi_url})"

    embed = {
        "title":       f"{emoji} Ko-fi — Thank You, {from_name}!",
        "description": desc,
        "color":       0xFF5E5B,
        "url":         kofi_url,
        "footer":      {"text": "communityplaylist.com stays free thanks to supporters like you"},
    }
    _post_to_channel(chan, {"embeds": [embed]})


# ── 5. Happening-now alert ────────────────────────────────────────────────────

def post_happening_now(events):
    """
    Post (or update) a happening-now blurb to #cp-events.
    Pass a list of Event objects starting within the next 60 minutes.
    Called by the discord_happening_now management command (runs hourly).
    """
    chan = _chan("DISCORD_CHAN_EVENTS")
    if not chan or not events:
        return

    site_url = getattr(settings, "SITE_URL", "https://communityplaylist.com")
    lines = []
    for e in events[:8]:
        emoji = CAT_EMOJI.get(e.category or "", "📍")
        try:
            t = e.start_date.strftime("%-I:%M %p")
        except Exception:
            t = ""
        lines.append(f"{emoji} **[{e.title}]({site_url}/events/{e.slug}/)** — {t}")

    embed = {
        "title":       "🔴 Happening in Portland right now",
        "description": "\n".join(lines),
        "color":       0xFF4444,
        "footer":      {"text": "communityplaylist.com · PDX Events"},
        "url":         site_url,
    }
    _post_to_channel(chan, {"embeds": [embed]})


# ── 6. Daily digest ───────────────────────────────────────────────────────────

def post_daily_digest(events_by_cat):
    """
    Post a morning digest thread to #cp-events.
    events_by_cat: dict of {category_label: [Event, ...]}
    Called by discord_daily_digest management command (runs at 8 AM).
    """
    chan = _chan("DISCORD_CHAN_EVENTS")
    if not chan:
        return

    from django.utils import timezone
    site_url = getattr(settings, "SITE_URL", "https://communityplaylist.com")
    today    = timezone.localtime(timezone.now()).strftime("%A, %B %-d")

    total = sum(len(v) for v in events_by_cat.values())
    if not total:
        return

    fields = []
    for cat, evs in events_by_cat.items():
        emoji = CAT_EMOJI.get(cat, "📅")
        lines = []
        for e in evs[:6]:
            try:
                t = e.start_date.strftime("%-I:%M %p")
            except Exception:
                t = ""
            free = " 🆓" if e.is_free else ""
            lines.append(f"`{t}` [{e.title[:36]}]({site_url}/events/{e.slug}/){free}")
        if len(evs) > 6:
            lines.append(f"_+{len(evs)-6} more…_")
        fields.append({
            "name":   f"{emoji} {cat.title()}",
            "value":  "\n".join(lines),
            "inline": False,
        })

    embed = {
        "title":       f"📅 PDX Today — {today}",
        "description": f"**{total} events** happening in Portland today. Get out there.",
        "color":       0xFF6B35,
        "fields":      fields[:25],
        "footer":      {"text": "communityplaylist.com · Free PDX event listings"},
        "url":         site_url,
    }

    hour = timezone.localtime(timezone.now()).hour
    if hour < 12:
        greeting = "☀️ **Good morning, PDX!**"
    elif hour < 17:
        greeting = "🌤️ **Good afternoon, PDX!**"
    else:
        greeting = "🌆 **Good evening, PDX!**"

    result = _post_to_channel(chan, {
        "content": f"{greeting} Here's what's on today:",
        "embeds":  [embed],
    })

    # Pin the digest and unpin yesterday's
    if result and result.get("id"):
        msg_id = result["id"]
        old_pins = _get_pins(chan)
        _pin(chan, msg_id)
        # Remove pins older than this one (keep only latest digest pinned)
        for pin in old_pins:
            if pin.get("author", {}).get("bot") and pin["id"] != msg_id:
                _unpin(chan, pin["id"])
