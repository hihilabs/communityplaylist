"""
One-time backfill: re-evaluate is_pdx_relevant on existing FediversePost rows.

Run once after expanding PDX_TERMS:
  python manage.py backfill_pdx_relevance

Only touches posts from geofenced sources (non-geofenced sources are always
relevant and don't need re-scoring).
"""
from django.core.management.base import BaseCommand

from social.models import FediversePost
from social.importers.base import PDX_TERMS

BATCH = 500


class Command(BaseCommand):
    help = 'Re-score is_pdx_relevant on all geofenced FediversePost rows'

    def add_arguments(self, parser):
        parser.add_argument('--dry-run', action='store_true',
                            help='Report counts without writing')

    def handle(self, *args, **options):
        dry_run = options['dry_run']

        qs = FediversePost.objects.filter(
            source__geofence_pdx=True
        ).only(
            'id', 'content_text', 'tags', 'account_username', 'is_pdx_relevant'
        )

        total = qs.count()
        self.stdout.write(f'Evaluating {total} geofenced posts …')

        flipped_true  = 0
        flipped_false = 0
        to_update     = []

        for post in qs.iterator(chunk_size=BATCH):
            haystack = ' '.join([
                post.content_text.lower(),
                ' '.join(post.tags).lower(),
                post.account_username.lower(),
            ])
            relevant = any(term in haystack for term in PDX_TERMS)

            if relevant != post.is_pdx_relevant:
                post.is_pdx_relevant = relevant
                to_update.append(post)
                if relevant:
                    flipped_true  += 1
                else:
                    flipped_false += 1

            if not dry_run and len(to_update) >= BATCH:
                FediversePost.objects.bulk_update(to_update, ['is_pdx_relevant'])
                to_update = []

        if not dry_run and to_update:
            FediversePost.objects.bulk_update(to_update, ['is_pdx_relevant'])

        label = '[dry-run] ' if dry_run else ''
        self.stdout.write(
            self.style.SUCCESS(
                f'{label}Done — '
                f'{flipped_true} newly relevant, '
                f'{flipped_false} newly irrelevant, '
                f'{total - flipped_true - flipped_false} unchanged'
            )
        )
