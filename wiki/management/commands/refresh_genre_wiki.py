"""
refresh_genre_wiki — one-shot: sync library data then enrich from external sources.

Run nightly via cron or the ops panel button.
"""
from django.core.management import call_command
from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = 'Sync library genres then enrich tokens from Last.fm / MusicBrainz'

    def add_arguments(self, parser):
        parser.add_argument('--api-url', default='http://10.0.0.124:3001')
        parser.add_argument('--min-tracks', type=int, default=2)
        parser.add_argument('--skip-enrich', action='store_true')
        parser.add_argument('--dry-run', action='store_true')

    def handle(self, *args, **options):
        dry = options['dry_run']

        self.stdout.write('── Step 1: sync library ────────────────────────')
        call_command('sync_genre_wiki',
                     api_url=options['api_url'],
                     min_tracks=options['min_tracks'],
                     dry_run=dry)

        if not options['skip_enrich']:
            self.stdout.write('── Step 2: enrich tokens (Last.fm tracks) ──────')
            call_command('enrich_genre_tokens',
                         lastfm_tracks=True,
                         skip_mb=True,
                         dry_run=dry)

            self.stdout.write('── Step 3: enrich tokens (Wikipedia) ───────────')
            call_command('enrich_genre_tokens',
                         wikipedia=True,
                         skip_mb=True,
                         dry_run=dry)

            self.stdout.write('── Step 4: enrich compounds (Last.fm tracks) ───')
            call_command('enrich_genre_tokens',
                         compound_tracks=True,
                         skip_mb=True,
                         dry_run=dry)
