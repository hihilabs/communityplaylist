"""
management command: blast_verified_profiles

Drip-posts verified promoter profiles to Bluesky, Discord, and Buffer
one at a time, prioritising profiles that have never been promoted or
were promoted longest ago (30-day rotation).

When all profiles have been promoted within the last 30 days, posts a
"Your Name Here" CTA card instead — keeps the feed active and recruits
new artists/crews to register and get verified.

Respects BUFFER_DAILY_PROMOTER_LIMIT (default 2) — if the quota is
already hit for today the command exits cleanly.

Run daily via cron:
    0 14 * * * docker exec cp-local-cp-local-1 python manage.py blast_verified_profiles
"""
import datetime

from django.core.management.base import BaseCommand
from django.utils import timezone

RECENCY_DAYS = 30  # treat a profile as "due again" after this many days


class Command(BaseCommand):
    help = 'Blast the next verified promoter profile (or CTA card) to social media'

    def add_arguments(self, parser):
        parser.add_argument('--dry-run', action='store_true',
                            help='Show what would be posted without actually posting')
        parser.add_argument('--slug', type=str, default='',
                            help='Force a specific promoter slug (bypasses queue order)')
        parser.add_argument('--all', action='store_true',
                            help='Blast ALL due profiles (still respects daily limit)')
        parser.add_argument('--cta', action='store_true',
                            help='Force-post the CTA card regardless of queue state')

    def handle(self, *args, **options):
        from django.db.models import Q
        from events.models import PromoterProfile
        from board.social import post_promoter

        dry_run    = options['dry_run']
        force_slug = options['slug'].strip()
        blast_all  = options['all']
        force_cta  = options['cta']

        cutoff = timezone.now() - datetime.timedelta(days=RECENCY_DAYS)

        qs = PromoterProfile.objects.filter(is_verified=True, photo__gt='').order_by(
            'last_promoted_at'  # NULLs first in SQLite
        )

        if force_slug:
            qs = qs.filter(slug=force_slug)
            if not qs.exists():
                self.stdout.write(f'No verified promoter with photo found for slug: {force_slug}')
                return

        # Filter to profiles not promoted recently
        if not force_slug:
            due = qs.filter(
                Q(last_promoted_at__isnull=True) |
                Q(last_promoted_at__lt=cutoff)
            )
        else:
            due = qs

        if force_cta or (not due.exists() and not force_slug):
            self._blast_cta(dry_run)
            return

        targets = list(due) if blast_all else [due.first()]

        for promoter in targets:
            promoted_str = (
                promoter.last_promoted_at.strftime('%Y-%m-%d') if promoter.last_promoted_at
                else 'never'
            )
            if dry_run:
                self.stdout.write(
                    f'[DRY] would blast: {promoter.name} ({promoter.slug}) '
                    f'— last promoted: {promoted_str}'
                )
                continue

            self.stdout.write(f'Blasting {promoter.name} (last: {promoted_str}) …')
            bsky_ok, discord_ok, buffer_ok = post_promoter(promoter)
            self.stdout.write(
                f'  ✓ {promoter.slug} — bsky:{bsky_ok} discord:{discord_ok} buffer:{buffer_ok}'
            )

            if not buffer_ok and not bsky_ok and not discord_ok:
                self.stdout.write('  → daily limit likely reached, stopping.')
                break

    def _blast_cta(self, dry_run):
        """Post the 'Your Name Here' CTA card — all profiles promoted recently."""
        self.stdout.write(f'All profiles promoted within {RECENCY_DAYS}d — posting CTA card.')
        if dry_run:
            self.stdout.write('[DRY] would post CTA card to Buffer + Bluesky')
            return

        from board.social_cards import generate_cta_card
        from board.social import _buffer_send, _bsky_post_text

        try:
            cta_url = generate_cta_card()
        except Exception as e:
            self.stdout.write(f'CTA card generation failed: {e}')
            return

        text = (
            'Artists and crews — get your profile on Community Playlist '
            'and we\'ll blast you to the whole community.\n\n'
            'Register → communityplaylist.com/promoters/register/\n\n'
            '#PDX #Portland #CommunityPlaylist #UndergroundMusic'
        )

        buf_ok = _buffer_send(text, image_urls=[cta_url])
        self.stdout.write(f'  CTA — buffer:{buf_ok}')

        hashtags = ('#PDX', '#Portland', '#CommunityPlaylist', '#UndergroundMusic')
        bsky_ok = _bsky_post_text(text, hashtags=hashtags)
        self.stdout.write(f'  CTA — bsky:{bsky_ok}')
