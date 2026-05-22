"""
management command: python manage.py post_random_social

Randomly picks one of three content types and posts it to enabled platforms.

Post types (weighted):
  record  (40%) — a RecordListing available for sale
  profile (40%) — an Artist or PromoterProfile with a bio
  zine    (20%) — a board Topic (stand-in until a Zine model exists)

A given object won't be re-posted to the same platform within REPOST_DAYS days.

Run on a schedule (e.g. 3x per week):
  0 12 * * 1,3,5  python manage.py post_random_social
"""
import random
from datetime import timedelta

from django.conf import settings
from django.core.management.base import BaseCommand
from django.utils import timezone

from events.models import RecordListing, Artist, PromoterProfile
from board.models import Topic
from social.models import SocialPost
from social.platforms.bluesky import BlueskyPlatform

REPOST_DAYS = 30
SITE_URL    = getattr(settings, 'SITE_URL', 'https://communityplaylist.com').rstrip('/')

WEIGHTS = {'record': 40, 'profile': 40, 'zine': 20}


def _was_recently_posted(platform_key, model_name, obj_id):
    cutoff = timezone.now() - timedelta(days=REPOST_DAYS)
    return SocialPost.objects.filter(
        platform=platform_key,
        object_model=model_name,
        object_id=obj_id,
        success=True,
        posted_at__gte=cutoff,
    ).exists()


# ------------------------------------------------------------------
# Text builders
# ------------------------------------------------------------------

def _record_text(listing):
    parts = [f'🎵 For Sale: {listing.artist} — {listing.title}']
    meta  = ' · '.join(filter(None, [listing.format, listing.condition, listing.price_display]))
    if meta:
        parts.append(meta)
    parts.append(f'Sold by {listing.promoter.name}')
    url = f'{SITE_URL}/promoters/{listing.promoter.slug}/'
    parts.append(url)
    parts.append('#pdx #portland #vinyl #recordshop')
    return '\n'.join(parts), url


def _profile_text(obj):
    kind = 'Artist' if isinstance(obj, Artist) else 'Crew / Sound System'
    bio  = (obj.bio or '').strip()
    snippet = (bio[:220] + '…') if len(bio) > 220 else bio
    url  = f'{SITE_URL}{obj.get_absolute_url()}'
    lines = [f'👤 PDX {kind}: {obj.name}']
    if snippet:
        lines.append(snippet)
    lines.append(url)
    lines.append('#pdx #portland #music')
    return '\n'.join(lines), url


def _zine_text(topic):
    snippet = (topic.body[:220] + '…') if len(topic.body) > 220 else topic.body
    url  = f'{SITE_URL}{topic.get_absolute_url()}'
    lines = [f'📖 {topic.title}', snippet, url, '#pdx #communityplaylist']
    return '\n'.join(lines), url


# ------------------------------------------------------------------
# Pickers
# ------------------------------------------------------------------

def _pick_record():
    qs = RecordListing.objects.filter(is_available=True).select_related('promoter')
    candidates = [r for r in qs if not _was_recently_posted('bluesky', 'RecordListing', r.pk)]
    return random.choice(candidates) if candidates else None


def _pick_profile():
    artists   = list(Artist.objects.exclude(bio=''))
    promoters = list(PromoterProfile.objects.filter(is_public=True).exclude(bio=''))
    pool      = artists + promoters
    candidates = [p for p in pool if not _was_recently_posted('bluesky', type(p).__name__, p.pk)]
    return random.choice(candidates) if candidates else None


def _pick_zine():
    candidates = [
        t for t in Topic.objects.all()
        if not _was_recently_posted('bluesky', 'Topic', t.pk)
    ]
    return random.choice(candidates) if candidates else None


# ------------------------------------------------------------------
# Command
# ------------------------------------------------------------------

class Command(BaseCommand):
    help = 'Post a random record, profile, or zine to Bluesky'

    def add_arguments(self, parser):
        parser.add_argument('--dry-run', action='store_true', help='Print text without posting')
        parser.add_argument('--type', choices=['record', 'profile', 'zine'], help='Force a specific post type')

    def handle(self, *args, **options):
        dry_run   = options['dry_run']
        post_type = options.get('type') or random.choices(
            list(WEIGHTS.keys()), weights=list(WEIGHTS.values())
        )[0]

        self.stdout.write(f'Selected type: {post_type}')

        if post_type == 'record':
            obj = _pick_record()
            if not obj:
                self.stdout.write('No eligible records found.'); return
            text, url = _record_text(obj)
            model_name = 'RecordListing'

        elif post_type == 'profile':
            obj = _pick_profile()
            if not obj:
                self.stdout.write('No eligible profiles found.'); return
            text, url = _profile_text(obj)
            model_name = type(obj).__name__

        else:  # zine
            obj = _pick_zine()
            if not obj:
                self.stdout.write('No eligible topics found.'); return
            text, url = _zine_text(obj)
            model_name = 'Topic'

        self.stdout.write(f'\n--- POST TEXT ---\n{text}\n---\n')

        if dry_run:
            self.stdout.write('Dry run — not posting.'); return

        platform = BlueskyPlatform()
        result   = platform.post(text, url=url)

        SocialPost.objects.create(
            platform    = SocialPost.PLATFORM_BLUESKY,
            post_type   = post_type,
            object_model = model_name,
            object_id   = obj.pk,
            text        = text,
            post_id     = result.post_id,
            post_url    = result.post_url,
            success     = result.success,
            error       = result.error,
        )

        if result.success:
            self.stdout.write(self.style.SUCCESS(f'Posted: {result.post_url}'))
        else:
            self.stderr.write(self.style.ERROR(f'Failed: {result.error}'))
