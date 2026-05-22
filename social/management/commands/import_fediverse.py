"""
management command: python manage.py import_fediverse

Fetches posts from all active FediverseSource records and saves new ones
to FediversePost. Applies PDX geofence filter when source.geofence_pdx=True.

Run daily:
  0 4 * * *  python manage.py import_fediverse
"""
from django.core.management.base import BaseCommand
from django.utils import timezone

from social.models import FediverseSource, FediversePost
from social.importers.mastodon  import MastodonImporter
from social.importers.pixelfed  import PixelfedImporter
from social.importers.funkwhale import FunkwhaleImporter
from social.profile_builder import find_or_stub

IMPORTER_MAP = {
    FediverseSource.PROTOCOL_MASTODON:  MastodonImporter,
    FediverseSource.PROTOCOL_PIXELFED:  PixelfedImporter,
    FediverseSource.PROTOCOL_FUNKWHALE: FunkwhaleImporter,
}


class Command(BaseCommand):
    help = 'Import posts from all active Fediverse sources'

    def add_arguments(self, parser):
        parser.add_argument('--source', type=int, help='Import only this FediverseSource ID')
        parser.add_argument('--dry-run', action='store_true', help='Fetch and count without saving')

    def handle(self, *args, **options):
        qs = FediverseSource.objects.filter(active=True)
        if options['source']:
            qs = qs.filter(pk=options['source'])

        dry_run = options['dry_run']
        total_new = 0

        for source in qs:
            cls = IMPORTER_MAP.get(source.protocol)
            if not cls:
                self.stderr.write(f'No importer for protocol "{source.protocol}" — skipping {source}')
                continue

            self.stdout.write(f'Fetching {source} …')
            importer = cls(source)

            # Resume from the most recent post we have for this source
            latest = FediversePost.objects.filter(source=source).order_by('-published_at').first()
            since_id = latest.remote_id if latest else ''

            raw_posts = importer.fetch(since_id=since_id)
            self.stdout.write(f'  got {len(raw_posts)} posts')

            new_count    = 0
            stub_count   = 0
            matched_count = 0

            for rp in raw_posts:
                if FediversePost.objects.filter(source=source, remote_id=rp.remote_id).exists():
                    continue

                pdx_relevant = importer.is_pdx_relevant(rp) if source.geofence_pdx else True

                # Profile matching / stub creation
                status = 'skip'
                if rp.account and not dry_run:
                    status, profile_obj = find_or_stub(rp.account, source=source)
                    if status == 'created':
                        stub_count += 1
                        self.stdout.write(
                            f'    + stub: {profile_obj.name} '
                            f'({rp.account.url})'
                        )
                    elif status == 'existing':
                        matched_count += 1

                if not dry_run:
                    FediversePost.objects.create(
                        source           = source,
                        remote_id        = rp.remote_id,
                        account_url      = rp.account_url,
                        account_username = rp.account_username,
                        content_html     = rp.content_html,
                        content_text     = rp.content_text,
                        url              = rp.url,
                        tags             = rp.tags,
                        media_urls       = rp.media_urls,
                        published_at     = rp.published_at or timezone.now(),
                        is_pdx_relevant  = pdx_relevant,
                    )
                new_count += 1

            total_new += new_count
            self.stdout.write(
                f'  saved {new_count} posts '
                f'| matched {matched_count} profiles '
                f'| {stub_count} stubs created'
            )

            if not dry_run:
                source.last_synced = timezone.now()
                source.save(update_fields=['last_synced'])

        label = 'would save' if dry_run else 'saved'
        self.stdout.write(self.style.SUCCESS(f'Done — {label} {total_new} new posts total'))
