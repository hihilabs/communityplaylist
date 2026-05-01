"""
fetch_profile_feeds — pull external RSS feeds from artist/venue/space profiles.

For each entity with an rss_feed URL:
  1. Parse the feed with feedparser
  2. Upsert new items into ExternalFeedItem (dedup by guid)
  3. For each genuinely new item, post to CP's Bluesky tagging the entity

Cron: 0 */4 * * * (every 4 hours)
"""
import feedparser
from django.core.management.base import BaseCommand
from django.utils import timezone


class Command(BaseCommand):
    help = 'Fetch external RSS feeds from profiles and post new items to Bluesky'

    def add_arguments(self, parser):
        parser.add_argument('--dry-run', action='store_true')
        parser.add_argument('--limit', type=int, default=20, help='Max new items per feed to process')

    def handle(self, *args, **options):
        from events.models import Artist, Venue, CommunitySpace, ExternalFeedItem
        dry = options['dry_run']
        limit = options['limit']

        total_new = 0

        for kind, qs, bsky_attr in [
            ('space',  CommunitySpace.objects.filter(rss_feed__gt='', is_public=True), 'bluesky'),
            ('artist', Artist.objects.filter(rss_feed__gt=''),                          'bluesky'),
            ('venue',  Venue.objects.filter(rss_feed__gt=''),                            'bluesky'),
        ]:
            for obj in qs:
                new = self._process(obj, kind, bsky_attr, dry, limit)
                total_new += new

        self.stdout.write(f'fetch_profile_feeds: {total_new} new items total')

    def _process(self, obj, kind, bsky_attr, dry, limit):
        from events.models import ExternalFeedItem
        try:
            parsed = feedparser.parse(obj.rss_feed, agent='CommunityPlaylistBot/1.0')
        except Exception as e:
            self.stderr.write(f'[{kind}:{obj}] fetch error: {e}')
            return 0

        new_count = 0
        for entry in parsed.entries[:limit]:
            guid  = entry.get('id') or entry.get('link') or entry.get('title', '')
            if not guid:
                continue

            fk = {f'community_space' if kind == 'space' else kind: obj}

            exists = ExternalFeedItem.objects.filter(guid=guid, **fk).exists()
            if exists:
                continue

            title = entry.get('title', '(untitled)')[:500]
            link  = entry.get('link', '')[:1000]
            desc  = (entry.get('summary') or entry.get('content', [{}])[0].get('value', ''))[:2000]

            pub = None
            if hasattr(entry, 'published_parsed') and entry.published_parsed:
                import time, datetime
                pub = timezone.make_aware(
                    datetime.datetime(*entry.published_parsed[:6]),
                    timezone.utc,
                ) if entry.published_parsed else None

            if dry:
                self.stdout.write(f'[DRY] {kind}:{obj} — {title[:60]}')
                new_count += 1
                continue

            item = ExternalFeedItem.objects.create(
                **fk,
                title=title,
                link=link,
                description=desc,
                published=pub,
                guid=guid,
            )
            new_count += 1

            # Post to CP Bluesky tagging the entity
            bsky_handle = getattr(obj, bsky_attr, '')
            posted = self._bsky_shoutout(obj, kind, item, bsky_handle)
            if posted:
                item.bsky_posted = True
                item.save(update_fields=['bsky_posted'])

        return new_count

    def _bsky_shoutout(self, obj, kind, item, bsky_handle):
        try:
            from board.social import _bsky_session, _bsky_create, _bsky_facets
        except ImportError:
            return False
        try:
            token, did = _bsky_session()
            if not token:
                return False

            name = getattr(obj, 'name', str(obj))
            tag  = f'@{bsky_handle}' if bsky_handle else name
            text = f'📡 New post from {tag}:\n"{item.title[:120]}"\n\n{item.link}'
            text = text[:300]

            links = [item.link] if item.link else []
            hashtags = ['#PDX', '#Portland']
            if bsky_handle:
                links.insert(0, f'https://bsky.app/profile/{bsky_handle}')

            facets = _bsky_facets(text, links=links, hashtags=hashtags)
            _bsky_create(token, did, text, facets=facets)
            return True
        except Exception as e:
            self.stderr.write(f'Bluesky post error for {obj}: {e}')
            return False
