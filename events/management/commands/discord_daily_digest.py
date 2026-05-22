"""
management command: discord_daily_digest

Post a morning events digest to #cp-events via the Discord bot.
Pins the latest digest and auto-unpins yesterday's.

Schedule: daily at 8 AM via Unraid User Scripts or cron.
    python manage.py discord_daily_digest
    python manage.py discord_daily_digest --dry-run
"""
from django.core.management.base import BaseCommand
from django.utils import timezone
from datetime import timedelta

from events.models import Event


class Command(BaseCommand):
    help = 'Post morning events digest to #cp-events Discord channel'

    def add_arguments(self, parser):
        parser.add_argument('--dry-run', action='store_true', help='Print what would be posted without sending')

    def handle(self, *args, **options):
        now    = timezone.localtime(timezone.now())
        start  = now.replace(hour=0, minute=0, second=0, microsecond=0)
        end    = start + timedelta(days=1)

        qs = (Event.objects
              .filter(status='approved', start_date__gte=start, start_date__lt=end)
              .order_by('start_date')
              .prefetch_related('genres'))

        events_by_cat = {}
        for e in qs:
            cat = e.category or 'other'
            events_by_cat.setdefault(cat, []).append(e)

        total = sum(len(v) for v in events_by_cat.values())
        self.stdout.write(f'Found {total} events today ({len(events_by_cat)} categories)')

        if not total:
            self.stdout.write('Nothing to post.')
            return

        if options['dry_run']:
            for cat, evs in events_by_cat.items():
                self.stdout.write(f'\n  {cat.upper()} ({len(evs)})')
                for e in evs:
                    self.stdout.write(f'    {e.start_date:%H:%M}  {e.title[:60]}')
            return

        from events.discord_bot import post_daily_digest
        post_daily_digest(events_by_cat)
        self.stdout.write('Digest posted.')
