"""
profile_builder.py

Given a fediverse AccountMeta, find an existing Artist / PromoterProfile / Venue
on the site using fuzzy name matching (≥90%). If no match is found, create a
claimable stub profile so the real person can discover and claim it.

Matching order:
  1. Exact (case-insensitive)
  2. SequenceMatcher ratio ≥ MATCH_THRESHOLD on normalised names
  3. No match → create Artist stub (most common case from music instances)

Stub profiles are created with:
  claimed_by  = None
  is_verified = False
  bio         = fediverse account bio
  social links mapped from known field labels
"""
import re
import unicodedata
from difflib import SequenceMatcher

from events.models import Artist, PromoterProfile, Venue

MATCH_THRESHOLD = 0.90

# Known fediverse field labels that map to our social link fields
_FIELD_MAP = {
    'instagram': 'instagram',
    'soundcloud': 'soundcloud',
    'bandcamp': 'bandcamp',
    'mixcloud': 'mixcloud',
    'youtube': 'youtube',
    'spotify': 'spotify',
    'mastodon': 'mastodon',
    'bluesky': 'bluesky',
    'tiktok': 'tiktok',
    'twitch': 'twitch',
    'website': 'website',
    'web': 'website',
    'link': 'website',
}


# ------------------------------------------------------------------
# Normalisation
# ------------------------------------------------------------------

def _norm(name: str) -> str:
    """Lowercase, strip accents, collapse non-alphanumeric runs to space."""
    nfkd = unicodedata.normalize('NFKD', name)
    ascii_ = nfkd.encode('ascii', 'ignore').decode()
    return re.sub(r'[^a-z0-9]+', ' ', ascii_.lower()).strip()


def _ratio(a: str, b: str) -> float:
    return SequenceMatcher(None, _norm(a), _norm(b)).ratio()


# ------------------------------------------------------------------
# Lookup helpers
# ------------------------------------------------------------------

def _best_artist(name: str):
    norm = _norm(name)
    best_obj, best_score = None, 0.0
    for a in Artist.objects.only('id', 'name'):
        score = SequenceMatcher(None, norm, _norm(a.name)).ratio()
        if score > best_score:
            best_obj, best_score = a, score
    return (best_obj, best_score) if best_score >= MATCH_THRESHOLD else (None, best_score)


def _best_promoter(name: str):
    norm = _norm(name)
    best_obj, best_score = None, 0.0
    for p in PromoterProfile.objects.only('id', 'name'):
        score = SequenceMatcher(None, norm, _norm(p.name)).ratio()
        if score > best_score:
            best_obj, best_score = p, score
    return (best_obj, best_score) if best_score >= MATCH_THRESHOLD else (None, best_score)


def _best_venue(name: str):
    norm = _norm(name)
    best_obj, best_score = None, 0.0
    for v in Venue.objects.only('id', 'name'):
        score = SequenceMatcher(None, norm, _norm(v.name)).ratio()
        if score > best_score:
            best_obj, best_score = v, score
    return (best_obj, best_score) if best_score >= MATCH_THRESHOLD else (None, best_score)


# ------------------------------------------------------------------
# Social link extraction
# ------------------------------------------------------------------

def _extract_social(extra_fields: dict) -> dict:
    """Map fediverse account.fields to Artist/PromoterProfile field names."""
    out = {}
    for label, value in extra_fields.items():
        key = _FIELD_MAP.get(label.lower().strip())
        if key and value:
            out[key] = value.strip()
    return out


# ------------------------------------------------------------------
# Public API
# ------------------------------------------------------------------

def find_or_stub(account, source=None):
    """
    Given an AccountMeta, return:
      ('existing', obj)  — matched existing Artist / PromoterProfile / Venue
      ('created',  obj)  — new stub Artist created and saved
      ('skip',     None) — display_name empty, nothing to do

    source: optional FediverseSource (used for notes on the stub).
    """
    name = (account.display_name or account.username or '').strip()
    if not name:
        return 'skip', None

    # 1. Check Artists
    artist, score = _best_artist(name)
    if artist:
        return 'existing', artist

    # 2. Check PromoterProfiles
    promoter, score = _best_promoter(name)
    if promoter:
        return 'existing', promoter

    # 3. Check Venues
    venue, score = _best_venue(name)
    if venue:
        return 'existing', venue

    # 4. No match — create a claimable stub Artist
    social = _extract_social(account.extra_fields)
    bio    = account.bio_text.strip()

    source_note = f'Auto-generated from {source.instance_url}' if source else 'Auto-generated from Fediverse'

    stub = Artist(
        name       = name,
        bio        = bio,
        website    = social.get('website', account.website or ''),
        instagram  = social.get('instagram', ''),
        soundcloud = social.get('soundcloud', ''),
        bandcamp   = social.get('bandcamp', ''),
        mixcloud   = social.get('mixcloud', ''),
        youtube    = social.get('youtube', ''),
        spotify    = social.get('spotify', ''),
        mastodon   = account.url,   # we know their fediverse URL
        bluesky    = social.get('bluesky', ''),
        tiktok     = social.get('tiktok', ''),
        twitch     = social.get('twitch', ''),
        claimed_by  = None,
        is_verified = False,
    )
    stub.save()   # triggers slug generation
    return 'created', stub
