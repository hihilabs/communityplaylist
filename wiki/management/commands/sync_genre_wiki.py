"""
sync_genre_wiki — rebuild wiki tokens and compound genres from the live edit.music library.

Calls GET /api/genres/cooccurrence on the edit.music server, which returns:
  tokens:       [{ name, count }]   — genre tags as they appear in files
  cooccurrence: [{ a, b, count }]   — pairs that share the same file

Wiki-level tokenization is MORE aggressive than edit.music's file tagger.
edit.music keeps display-friendly tags; the wiki cares about atomic cross-search tokens.

Splitting rules (applied in order):
  1. Protected phrases stay whole:  "R&B", "J-R&B", "Lo-Fi", "G-Funk"
  2. Separators  & , ; / |  are word boundaries
  3. Spaces are word boundaries  →  "Gangsta Rap" → ["Gangsta", "Rap"]
  4. Hyphens are kept (not word boundaries) →  "Post-Rock" stays "Post-Rock"

Examples:
  "Drum & Bass"       → ["Drum", "Bass"]
  "Gangsta Rap"       → ["Gangsta", "Rap"]
  "Death Metal"       → ["Death", "Metal"]
  "Progressive Rock"  → ["Progressive", "Rock"]
  "R&B"               → ["R&B"]   (protected)
  "G-Funk"            → ["G-Funk"] (protected)
  "Lo-Fi"             → ["Lo-Fi"] (protected)
  "Hip"               → ["Hip"]
"""
import re
import urllib.request
import json
from collections import defaultdict

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils.text import slugify

from wiki.models import GenreToken, CompoundGenre


# Tags that must never be split — single-concept genre names containing separators
WIKI_PHRASES = {"R&B", "J-R&B", "Lo-Fi", "Hi-Fi", "G-Funk", "K-Pop", "J-Pop", "J-Rock"}

# Splits on & , ; / | and whitespace
_SEP = re.compile(r'[&,;/|\s]+')


def wiki_tokenize(tag: str) -> list[str]:
    """Split an edit.music genre tag into atomic wiki tokens."""
    tag = tag.strip()
    if tag in WIKI_PHRASES:
        return [tag]
    parts = _SEP.split(tag)
    result = []
    for p in parts:
        p = p.strip()
        if p:
            result.append(p)
    return result


class Command(BaseCommand):
    help = 'Sync wiki tokens and compound genres from the live edit.music library'

    def add_arguments(self, parser):
        parser.add_argument(
            '--api-url', default='http://10.0.0.124:3001',
            help='Base URL of the edit.music server'
        )
        parser.add_argument(
            '--min-tracks', type=int, default=2,
            help='Minimum file count to create a compound genre'
        )
        parser.add_argument('--dry-run', action='store_true')

    def handle(self, *args, **options):
        api_url   = options['api_url'].rstrip('/')
        min_tracks = options['min_tracks']
        dry       = options['dry_run']

        # ── 1. Fetch live data ────────────────────────────────────────────
        self.stdout.write(f'Fetching {api_url}/api/genres/cooccurrence …')
        try:
            with urllib.request.urlopen(f'{api_url}/api/genres/cooccurrence', timeout=30) as r:
                data = json.load(r)
        except Exception as e:
            raise CommandError(f'Could not reach edit.music API: {e}')

        raw_tokens   = data['tokens']       # [{ name, count }]
        cooccurrence = data['cooccurrence']  # [{ a, b, count }]

        self.stdout.write(f'  {len(raw_tokens)} genre tags, {len(cooccurrence)} co-occurrence pairs')

        # ── 2. Build wiki-token → track_count map ─────────────────────────
        # Each file tag may expand into multiple wiki tokens (e.g. "Drum & Bass" → Drum + Bass)
        wiki_token_counts: dict[str, int] = defaultdict(int)
        # tag → its wiki tokens (for compound detection)
        tag_to_wiki: dict[str, list[str]] = {}

        for entry in raw_tokens:
            tag   = entry['name']
            count = entry['count']
            wtoks = wiki_tokenize(tag)
            tag_to_wiki[tag] = wtoks
            for wt in wtoks:
                wiki_token_counts[wt] += count

        # ── 3–5. All DB writes in one transaction (avoids SQLite lock contention) ──
        self.stdout.write(f'  {len(wiki_token_counts)} wiki tokens')
        token_objs: dict[str, GenreToken] = {}

        # Build compound candidates in memory before touching the DB
        compound_candidates: dict[frozenset[str], int] = defaultdict(int)
        for entry in raw_tokens:
            wtoks = tag_to_wiki.get(entry['name'], [])
            if len(wtoks) >= 2:
                compound_candidates[frozenset(wtoks)] += entry['count']

        created = updated = skipped = 0

        if dry:
            for name, count in wiki_token_counts.items():
                if name and slugify(name):
                    self.stdout.write(f'    [dry] token: {name} ({count})')
            for token_set, count in sorted(compound_candidates.items(), key=lambda x: -x[1]):
                if count >= min_tracks:
                    self.stdout.write(f'    [dry] compound: {", ".join(sorted(token_set))} ({count} tracks)')
                    created += 1
        else:
            with transaction.atomic():
                # step 3: upsert tokens
                for name, count in wiki_token_counts.items():
                    if not name:
                        continue
                    sl = slugify(name)
                    if not sl:
                        continue
                    obj, _ = GenreToken.objects.update_or_create(
                        slug=sl,
                        defaults={'name': name, 'track_count': count},
                    )
                    token_objs[name] = obj

                # step 4: upsert compound genres
                for token_set, count in sorted(compound_candidates.items(), key=lambda x: -x[1]):
                    if count < min_tracks:
                        skipped += 1
                        continue
                    sorted_names = sorted(token_set)
                    name = ', '.join(sorted_names)
                    sl   = slugify(name)
                    if not sl:
                        continue
                    obj, is_new = CompoundGenre.objects.update_or_create(
                        slug=sl,
                        defaults={'name': name, 'track_count': count},
                    )
                    toks_to_link = [token_objs[n] for n in sorted_names if n in token_objs]
                    if toks_to_link:
                        obj.tokens.set(toks_to_link)
                    if is_new:
                        created += 1
                    else:
                        updated += 1

                # step 5: wire related edges from co-occurrence
                for pair in cooccurrence:
                    if pair['count'] < min_tracks:
                        continue
                    a_names = tag_to_wiki.get(pair['a'], [pair['a']])
                    b_names = tag_to_wiki.get(pair['b'], [pair['b']])
                    for an in a_names:
                        for bn in b_names:
                            if an == bn:
                                continue
                            ta = token_objs.get(an)
                            tb = token_objs.get(bn)
                            if ta and tb:
                                ta.related.add(tb)

        self.stdout.write(self.style.SUCCESS(
            f'Done — {len(wiki_token_counts)} tokens, '
            f'{created} compound genres created, {updated} updated, {skipped} below threshold'
        ))
