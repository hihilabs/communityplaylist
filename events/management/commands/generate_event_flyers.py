"""
management command: generate_event_flyers

Auto-generates gradient flyer images for approved upcoming events
that have no photo. One batch per cron run — gentle background fill.

The gradient preset is deterministically assigned from the event slug
(same hash as the browser flyer maker), so the card always matches what
the flyer page would show by default.

Run via cron (daily, staggered from other jobs):
    0 4 * * * docker exec cp-local-cp-local-1 python manage.py generate_event_flyers
"""
from django.core.management.base import BaseCommand
from django.utils import timezone


class Command(BaseCommand):
    help = 'Generate gradient flyer images for upcoming events with no photo'

    def add_arguments(self, parser):
        parser.add_argument('--limit', type=int, default=20,
                            help='Max events to process per run (default 20)')
        parser.add_argument('--dry-run', action='store_true',
                            help='Show which events would get flyers without writing files')
        parser.add_argument('--slug', type=str, default='',
                            help='Process a single event by slug')
        parser.add_argument('--overwrite', action='store_true',
                            help='Regenerate even if a photo already exists')

    def handle(self, *args, **options):
        from events.models import Event
        from board.flyer_gen import generate_event_flyer

        dry_run   = options['dry_run']
        limit     = options['limit']
        overwrite = options['overwrite']
        slug      = options['slug'].strip()

        qs = Event.objects.filter(status='approved', start_date__gte=timezone.now())

        if slug:
            qs = qs.filter(slug=slug)
        elif not overwrite:
            qs = qs.filter(photo='')   # only events without a photo

        qs = qs.order_by('start_date')[:limit]

        total = qs.count()
        if total == 0:
            self.stdout.write('No events need flyers.')
            return

        self.stdout.write(f'Generating flyers for {total} events (dry={dry_run}) …')
        done = failed = 0

        for event in qs:
            label = f'[{event.pk}] {event.title[:50]}'
            if dry_run:
                from board.flyer_gen import _slug_to_preset, PRESETS
                idx = _slug_to_preset(event.slug or str(event.pk))
                self.stdout.write(
                    f'  [DRY] {label} → preset {PRESETS[idx]["name"]}'
                )
                continue

            try:
                rel_path = generate_event_flyer(event)
                event.photo = rel_path
                event.save(update_fields=['photo'])
                self.stdout.write(f'  ✓ {label} → {rel_path}')
                done += 1
            except Exception as e:
                self.stdout.write(f'  ✗ {label}: {e}')
                failed += 1

        if not dry_run:
            self.stdout.write(f'\nDone — {done} generated, {failed} failed.')
