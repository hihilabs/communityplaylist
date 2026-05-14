"""
management command: discord_happening_now

Post a "happening right now / starting soon" alert to #cp-events.
Finds events starting in the next 60 minutes or already underway (started < 30 min ago).

Schedule: hourly via Unraid User Scripts or cron.
    python manage.py discord_happening_now
    python manage.py discord_happening_now --dry-run
    python manage.py discord_happening_now --window 90   # widen to 90 min ahead
"""
from django.core.management.base import BaseCommand
from django.utils import timezone
from datetime import timedelta

from events.models import Event


class Command(BaseCommand):
    help = 'Post happening-now alert to #cp-events Discord channel'

    def add_arguments(self, parser):
        parser.add_argument('--window',  type=int, default=60, help='Minutes ahead to consider (default 60)')
        parser.add_argument('--dry-run', action='store_true',  help='Print without sending')

    def handle(self, *args, **options):
        now     = timezone.now()
        window  = options['window']
        cutoff  = now + timedelta(minutes=window)
        # Also catch events that started in the last 30 min (just kicked off)
        started = now - timedelta(minutes=30)

        events = list(
            Event.objects
            .filter(status='approved', start_date__gte=started, start_date__lte=cutoff)
            .order_by('start_date')[:8]
        )

        self.stdout.write(f'{len(events)} events happening now / starting soon')

        if not events:
            return

        if options['dry_run']:
            for e in events:
                self.stdout.write(f'  {e.start_date:%H:%M}  {e.title[:60]}')
            return

        from events.discord_bot import post_happening_now
        post_happening_now(events)
        self.stdout.write('Alert posted.')
