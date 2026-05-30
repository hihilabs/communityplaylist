"""
Server-side event flyer generator — matches the gradient presets in event_flyer.html.

Produces a 1080×1080 PNG with:
  - Radial gradient background (same 8 presets, slug-hash assigned)
  - Event title, date, venue
  - Artist lineup (up to 5 names)
  - Category badge + communityplaylist.com watermark

Saves to MEDIA_ROOT/event_flyers/<slug>.png and returns the path.
"""
import os
import math

from PIL import Image, ImageDraw, ImageFont

CARD  = 1080
GUTTER = 64

# ── Gradient presets — mirrors GRAD_PRESETS in event_flyer.html ───────────────
# Each entry: (base_color, highlight_color, hi_cx, hi_cy)
#   cx/cy — highlight centre as fraction of card size
PRESETS = [
    # Cosmos  — deep purple glow
    {'name': 'Cosmos',   'base': (13,  13,  13),  'hi': (26, 10, 46),   'cx': 0.40, 'cy': 0.30},
    # Ember   — dark red ember
    {'name': 'Ember',    'base': (13,  5,   5),   'hi': (46, 10,  0),   'cx': 0.30, 'cy': 0.40},
    # Abyss   — midnight blue
    {'name': 'Abyss',    'base': (5,   5,   13),  'hi': (0,  21, 51),   'cx': 0.50, 'cy': 0.20},
    # Blush   — dark magenta
    {'name': 'Blush',    'base': (10,  0,   9),   'hi': (42,  0, 32),   'cx': 0.60, 'cy': 0.30},
    # Teal    — deep teal
    {'name': 'Teal',     'base': (5,   13,  13),  'hi': (0,  51, 51),   'cx': 0.50, 'cy': 0.25},
    # Dusk    — forest night
    {'name': 'Dusk',     'base': (5,   8,   5),   'hi': (10, 30, 10),   'cx': 0.35, 'cy': 0.35},
    # Infrared — dark crimson
    {'name': 'Infrared', 'base': (10,  2,   4),   'hi': (42,  0,  8),   'cx': 0.45, 'cy': 0.30},
    # Amber   — dark gold
    {'name': 'Amber',    'base': (10,  7,   0),   'hi': (42, 24,  0),   'cx': 0.40, 'cy': 0.30},
]

# Accent text colours that pair with each preset
ACCENT_COLOURS = [
    (180, 120, 255),   # Cosmos  — soft purple
    (255, 107,  53),   # Ember   — CP orange
    ( 80, 160, 255),   # Abyss   — sky blue
    (220,  80, 180),   # Blush   — pink
    ( 60, 220, 200),   # Teal    — cyan
    (100, 200,  80),   # Dusk    — lime
    (255,  60,  80),   # Infrared — red
    (255, 180,  40),   # Amber   — gold
]


def _slug_to_preset(slug):
    h = 0
    for ch in (slug or ''):
        h = ((h * 31) + ord(ch)) & 0xffff
    return h % len(PRESETS)


def _hex(rgb):
    return '#{:02x}{:02x}{:02x}'.format(*rgb)


def _radial_gradient(size, base, hi, cx, cy, radius_frac=0.65):
    """Return a PIL Image with a radial gradient from hi at (cx,cy) to base."""
    img  = Image.new('RGB', (size, size), base)
    draw = ImageDraw.Draw(img)
    rx   = int(size * radius_frac)
    ry   = int(size * radius_frac * 0.8)
    steps = 64
    for i in range(steps, 0, -1):
        t   = i / steps          # 1 = centre, 0 = edge
        r   = tuple(int(base[c] + (hi[c] - base[c]) * t) for c in range(3))
        sw  = int(rx * (i / steps))
        sh  = int(ry * (i / steps))
        x0  = int(cx * size - sw)
        y0  = int(cy * size - sh)
        x1  = int(cx * size + sw)
        y1  = int(cy * size + sh)
        draw.ellipse([x0, y0, x1, y1], fill=r)
    return img


def _font(size):
    return ImageFont.load_default(size=size)


def _wrap(draw, text, font, max_w):
    words, lines, line = text.split(), [], ''
    for w in words:
        test = f'{line} {w}'.strip()
        if draw.textlength(test, font=font) <= max_w:
            line = test
        else:
            if line:
                lines.append(line)
            line = w
    if line:
        lines.append(line)
    return lines


def generate_event_flyer(event):
    """
    Generate a 1080×1080 gradient flyer for `event`.
    Saves to MEDIA_ROOT/event_flyers/<slug>.png.
    Returns the relative media path (suitable for ImageField.name).
    """
    from django.conf import settings

    idx     = _slug_to_preset(event.slug or str(event.pk))
    preset  = PRESETS[idx]
    accent  = ACCENT_COLOURS[idx]

    img  = _radial_gradient(CARD, preset['base'], preset['hi'], preset['cx'], preset['cy'])
    draw = ImageDraw.Draw(img)

    C_HI  = (238, 238, 238)
    C_MID = (160, 160, 160)
    C_LO  = (70,  70,  70)

    # Bottom accent bar
    draw.rectangle([(0, CARD - 10), (CARD, CARD)], fill=accent)
    # Top accent bar (thin)
    draw.rectangle([(0, 0), (CARD, 6)], fill=accent)

    # ── Category badge (top-left) ───────────────────────────────────────────
    cat = (event.category or 'Event').upper()
    f_badge = _font(28)
    bw = int(draw.textlength(cat, font=f_badge)) + 24
    draw.rectangle([(GUTTER, GUTTER), (GUTTER + bw, GUTTER + 38)], fill=accent)
    draw.text((GUTTER + 12, GUTTER + 6), cat, font=f_badge, fill=(255, 255, 255))

    # ── Date (top-right) ────────────────────────────────────────────────────
    f_date = _font(30)
    date_str = event.start_date.strftime('%a %b %-d · %-I:%M %p') if event.start_date else ''
    if date_str:
        dw = int(draw.textlength(date_str, font=f_date))
        draw.text((CARD - GUTTER - dw, GUTTER + 6), date_str, font=f_date, fill=accent)

    # ── Title ───────────────────────────────────────────────────────────────
    f_title = _font(76)
    f_title_sm = _font(56)
    max_w   = CARD - GUTTER * 2
    title   = event.title or ''

    # Use smaller font if title is long
    font_t  = f_title if len(title) <= 40 else f_title_sm
    lines   = _wrap(draw, title, font_t, max_w)[:3]
    lh      = int(font_t.size * 1.15)
    title_y = CARD - 340
    for ln in lines:
        draw.text((GUTTER, title_y), ln, font=font_t, fill=C_HI)
        title_y += lh

    # ── Venue ───────────────────────────────────────────────────────────────
    f_venue = _font(34)
    venue   = event.location or ''
    if len(venue) > 60:
        venue = venue[:58] + '…'
    draw.text((GUTTER, title_y + 12), venue, font=f_venue, fill=accent)

    # ── Artist lineup ───────────────────────────────────────────────────────
    artists = list(event.artists.values_list('name', flat=True)[:5])
    if artists:
        f_art = _font(30)
        lineup = '  ·  '.join(artists)
        if draw.textlength(lineup, font=f_art) > max_w:
            lineup = '  ·  '.join(artists[:3])
            if draw.textlength(lineup, font=f_art) > max_w:
                lineup = artists[0] + f'  +{len(artists)-1} more'
        draw.text((GUTTER, title_y + 58), lineup, font=f_art, fill=C_MID)

    # ── Watermark ───────────────────────────────────────────────────────────
    f_wm = _font(26)
    draw.text((GUTTER, CARD - 46), 'communityplaylist.com', font=f_wm, fill=C_LO)

    # ── Save ────────────────────────────────────────────────────────────────
    out_dir  = os.path.join(settings.MEDIA_ROOT, 'event_flyers')
    os.makedirs(out_dir, exist_ok=True)
    fname    = f'{event.slug or event.pk}.png'
    abs_path = os.path.join(out_dir, fname)
    img.save(abs_path, 'PNG', optimize=True)

    return f'event_flyers/{fname}'
