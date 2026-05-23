"""
PIL-based social card generator for Buffer posts.

Produces 1–3 1080×1080 PNG cards per promoter:
  Card 1 — Hero: photo bg + name, type, genres
  Card 2 — Info: bio + social links
  Card 3 — Shop: record inventory (only if listings exist)

Cards are saved to MEDIA_ROOT/social_cards/ and returned as absolute URLs
that Buffer can fetch as carousel assets.
"""
import io
import os
import urllib.request

from PIL import Image, ImageDraw, ImageFont

CP_BASE    = 'https://communityplaylist.com'
CARD_SIZE  = 1080
GUTTER     = 64   # left/right margin

# Colour palette (matches CP dark theme)
C_BG       = (17,  17,  17)
C_SURFACE  = (22,  22,  22)
C_BORDER   = (34,  34,  34)
C_TEXT_HI  = (238, 238, 238)
C_TEXT_MID = (153, 153, 153)
C_TEXT_LO  = (68,  68,  68)
C_ACCENT   = (255, 107, 53)   # #ff6b35 fallback


# ── Helpers ───────────────────────────────────────────────────────────────────

def _hex_to_rgb(h, fallback=C_ACCENT):
    try:
        h = (h or '').lstrip('#')
        if len(h) != 6:
            return fallback
        return tuple(int(h[i:i+2], 16) for i in (0, 2, 4))
    except Exception:
        return fallback


def _font(size):
    return ImageFont.load_default(size=size)


def _wrap_text(draw, text, font, max_width):
    """Wrap text to fit max_width pixels. Returns list of lines."""
    words  = text.split()
    lines  = []
    line   = ''
    for w in words:
        test = f'{line} {w}'.strip()
        if draw.textlength(test, font=font) <= max_width:
            line = test
        else:
            if line:
                lines.append(line)
            line = w
    if line:
        lines.append(line)
    return lines


def _fetch_image(url, size):
    """Fetch an image from URL, resize/crop to square `size`. Returns PIL Image or None."""
    try:
        req = urllib.request.Request(url, headers={'User-Agent': 'CommunityPlaylist/1.0'})
        with urllib.request.urlopen(req, timeout=10) as r:
            img = Image.open(io.BytesIO(r.read())).convert('RGB')
        # Centre-crop to square then resize
        w, h   = img.size
        m      = min(w, h)
        left   = (w - m) // 2
        top    = (h - m) // 2
        img    = img.crop((left, top, left + m, top + m))
        return img.resize((size, size), Image.LANCZOS)
    except Exception:
        return None


def _gradient_overlay(img, start_y_frac=0.35, opacity=220):
    """Blend a black gradient over the bottom portion of img (in-place). Returns img."""
    overlay = Image.new('RGBA', img.size, (0, 0, 0, 0))
    draw    = ImageDraw.Draw(overlay)
    h       = img.size[1]
    start_y = int(h * start_y_frac)
    for y in range(start_y, h):
        a = int(opacity * (y - start_y) / (h - start_y))
        draw.line([(0, y), (img.size[0], y)], fill=(0, 0, 0, a))
    return Image.alpha_composite(img.convert('RGBA'), overlay).convert('RGB')


def _accent_bar(draw, accent, y, height=10):
    draw.rectangle([(0, y), (CARD_SIZE, y + height)], fill=accent)


def _watermark(draw, y=None):
    font = _font(26)
    y    = y or (CARD_SIZE - 46)
    draw.text((GUTTER, y), 'communityplaylist.com', font=font, fill=C_TEXT_LO)


# ── Card builders ─────────────────────────────────────────────────────────────

def _card_hero(promoter, accent):
    """Card 1 — photo background, name, type, genres."""
    img = Image.new('RGB', (CARD_SIZE, CARD_SIZE), C_BG)

    # Fetch + blend photo
    if promoter.photo:
        photo_url = f'{CP_BASE}{promoter.photo.url}'
        photo     = _fetch_image(photo_url, CARD_SIZE)
        if photo:
            img = _gradient_overlay(photo, start_y_frac=0.28, opacity=215)

    draw = ImageDraw.Draw(img)

    # Bottom accent bar
    _accent_bar(draw, accent, CARD_SIZE - 10)

    # Name (large)
    f_name  = _font(82)
    f_sub   = _font(38)
    f_genre = _font(30)

    name = promoter.name
    # Truncate name if it overflows
    while draw.textlength(name, font=f_name) > CARD_SIZE - GUTTER * 2 and len(name) > 4:
        name = name[:-2] + '…'

    name_y = CARD_SIZE - 310
    draw.text((GUTTER, name_y), name, font=f_name, fill=C_TEXT_HI)

    # Type label (no verified badge — verified status drives auto-promote, not display)
    type_str = promoter.get_types_display()
    draw.text((GUTTER, name_y + 96), type_str, font=f_sub, fill=accent)

    # Genres
    genres = ', '.join(promoter.genres.values_list('name', flat=True)[:4])
    if genres:
        draw.text((GUTTER, name_y + 150), genres, font=f_genre, fill=C_TEXT_MID)

    # Type label top-left (text only — PIL default font can't render emoji)
    type_label = promoter.get_types_display().split(' · ')[0].upper()
    f_badge = _font(28)
    badge_w = int(draw.textlength(type_label, font=f_badge)) + 24
    draw.rectangle([(GUTTER, GUTTER), (GUTTER + badge_w, GUTTER + 38)], fill=accent)
    draw.text((GUTTER + 12, GUTTER + 6), type_label, font=f_badge, fill=(255, 255, 255))

    _watermark(draw)
    return img


def _card_info(promoter, accent):
    """Card 2 — bio text + social links."""
    img  = Image.new('RGB', (CARD_SIZE, CARD_SIZE), C_BG)
    draw = ImageDraw.Draw(img)

    # Top accent bar
    _accent_bar(draw, accent, 0)

    f_name = _font(68)
    f_body = _font(36)
    f_sm   = _font(30)

    y = 50
    # Name
    draw.text((GUTTER, y), promoter.name, font=f_name, fill=C_TEXT_HI)
    y += 90

    # Thin separator
    draw.line([(GUTTER, y), (CARD_SIZE - GUTTER, y)], fill=C_BORDER, width=2)
    y += 24

    # Bio — wrap to 5 lines max
    bio = (promoter.bio or '').strip()
    if bio:
        max_w = CARD_SIZE - GUTTER * 2
        lines = _wrap_text(draw, bio, f_body, max_w)[:6]
        for ln in lines:
            draw.text((GUTTER, y), ln, font=f_body, fill=C_TEXT_MID)
            y += 48
        y += 24

    # Social links (plain text — PIL default font cannot render emoji)
    socials = []
    if promoter.instagram:  socials.append(f'IG  @{promoter.instagram}')
    if promoter.soundcloud: socials.append(f'SC  soundcloud.com/{promoter.soundcloud}')
    if promoter.mixcloud:   socials.append(f'MX  mixcloud.com/{promoter.mixcloud}')
    if promoter.bandcamp:   socials.append(f'BC  Bandcamp')
    if promoter.spotify:    socials.append(f'SP  Spotify')
    if promoter.twitch:     socials.append(f'TW  twitch.tv/{promoter.twitch}')
    if promoter.website:    socials.append(f'WW  {promoter.website[:45]}')
    if promoter.discord:    socials.append(f'DC  Discord')
    if promoter.kofi:       socials.append(f'KF  ko-fi.com/{promoter.kofi}')

    y = max(y, 550)
    for s in socials[:6]:
        draw.text((GUTTER, y), s, font=f_sm, fill=C_TEXT_HI)
        y += 52

    # CP URL bottom
    _accent_bar(draw, accent, CARD_SIZE - 10)
    _watermark(draw)
    return img


def _card_shop(promoter, accent, listings):
    """Card 3 — record shop inventory. Only built when listings exist."""
    img  = Image.new('RGB', (CARD_SIZE, CARD_SIZE), C_BG)
    draw = ImageDraw.Draw(img)

    _accent_bar(draw, accent, 0)

    f_title  = _font(68)
    f_header = _font(44)
    f_item   = _font(32)
    f_price  = _font(32)
    f_sm     = _font(26)

    y = 50
    draw.text((GUTTER, y), 'RECORD SHOP', font=f_title, fill=accent)
    y += 90

    draw.text((GUTTER, y), promoter.name, font=f_header, fill=C_TEXT_HI)
    y += 60

    count = listings.count()
    draw.text((GUTTER, y), f'{count} records available', font=f_header, fill=C_TEXT_MID)
    y += 56

    draw.line([(GUTTER, y), (CARD_SIZE - GUTTER, y)], fill=C_BORDER, width=2)
    y += 28

    # Top listings
    for item in listings.order_by('row_index')[:7]:
        artist_title = f'{item.artist[:28]}  —  {item.title[:28]}'
        draw.text((GUTTER, y), artist_title, font=f_item, fill=C_TEXT_HI)
        if item.price_display or item.price_sol > 0:
            price_str = item.price_display or f'◎ {item.price_sol}'
            pw = draw.textlength(price_str, font=f_price)
            draw.text((CARD_SIZE - GUTTER - pw, y), price_str, font=f_price, fill=accent)
        y += 48
        if y > CARD_SIZE - 160:
            draw.text((GUTTER, y), '…', font=f_item, fill=C_TEXT_LO)
            break

    # Payment options
    pay_parts = []
    if promoter.sol_wallet:             pay_parts.append('SOL')
    if promoter.shop_pay_in_person:     pay_parts.append('In Person')
    if promoter.shop_open_to_trade:     pay_parts.append('Trade')

    if pay_parts:
        pay_str = '  ·  '.join(pay_parts)
        draw.text((GUTTER, CARD_SIZE - 90), pay_str, font=f_header, fill=accent)

    _accent_bar(draw, accent, CARD_SIZE - 10)
    _watermark(draw)
    return img


# ── Public entry point ────────────────────────────────────────────────────────

def generate_promoter_cards(promoter):
    """
    Generate 1–3 1080×1080 PNG social cards for a promoter profile.
    Saves to MEDIA_ROOT/social_cards/ and returns a list of absolute URLs
    (https://communityplaylist.com/media/social_cards/...) ready for Buffer.
    """
    from django.conf import settings

    accent   = _hex_to_rgb(promoter.brand_color)
    listings = promoter.record_listings.filter(is_available=True)

    cards = [
        ('card1', _card_hero(promoter, accent)),
        ('card2', _card_info(promoter, accent)),
    ]
    if listings.count():
        cards.append(('card3', _card_shop(promoter, accent, listings)))

    out_dir = os.path.join(settings.MEDIA_ROOT, 'social_cards')
    os.makedirs(out_dir, exist_ok=True)

    urls = []
    for label, img in cards:
        fname = f'{promoter.slug}_{label}.png'
        img.save(os.path.join(out_dir, fname), 'PNG', optimize=True)
        urls.append(f'{CP_BASE}{settings.MEDIA_URL}social_cards/{fname}')

    return urls
