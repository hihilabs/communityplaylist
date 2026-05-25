"""
management command: blast_verified_profiles

Drip-posts verified promoter profiles to Bluesky, Discord, and Buffer
one at a time, prioritising profiles that have never been promoted or
were promoted longest ago.

Respects BUFFER_DAILY_PROMOTER_LIMIT (default 2) — if the quota is
already hit for today the command exits cleanly.

Run daily via cron:
    0 14 * * * docker exec cp-local-cp-local-1 python manage.py blast_verified_profiles
"""
from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = 'Blast the next verified promoter profile to social media'

    def add_arguments(self, parser):
        parser.add_argument('--dry-run', action='store_true',
                            help='Show which profile would be posted without actually posting')
        parser.add_argument('--slug', type=str, default='',
                            help='Force a specific promoter slug (bypasses queue order)')
        parser.add_argument('--all', action='store_true',
                            help='Blast ALL verified profiles (still respects daily limit)')

    def handle(self, *args, **options):
        from events.models import PromoterProfile
        from board.social import post_promoter

        dry_run   = options['dry_run']
        force_slug = options['slug'].strip()
        blast_all  = options['all']

        qs = PromoterProfile.objects.filter(is_verified=True, photo__gt='').order_by(
            'last_promoted_at'  # NULLs sort first in SQLite
        )

        if force_slug:
            qs = qs.filter(slug=force_slug)
            if not qs.exists():
                self.stdout.write(f'No verified promoter with photo found for slug: {force_slug}')
                return

        if not qs.exists():
            self.stdout.write('No verified promoters with photos found.')
            return

        targets = list(qs) if blast_all else [qs.first()]

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
