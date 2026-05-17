"""
sync_genre_wiki — rebuild wiki tokens and compound genres from the live edit.music library.

Calls GET /api/genres/cooccurrence on the edit.music server, which returns:
  tokens:       [{ name, count }]   — genre tags as they appear in files
  cooccurrence: [{ a, b, count }]   — pairs that share the same file

Wiki-level tokenization is more aggressive than edit.music's file tagger:
  "Drum & Bass" → ["Drum", "Bass"]   (& splits even protected phrases)
  "Hip"         → ["Hip"]
  "G-Funk"      → ["G-Funk"]         (hyphens kept intact)

Compound genres are built from actual file tags — if a tag resolves to
more than one wiki token, that group of tokens forms a compound genre.
Co-occurrence pairs are wired as token.related edges.
"""
import re
import urllib.request
import json
from collections import defaultdict

from django.core.management.base import BaseCommand, CommandError
from django.utils.text import slugify

from wiki.models import GenreToken, CompoundGenre


_SEP = re.compile(r'\s*[&,;/|]\s*')


def wiki_tokenize(tag: str) -> list[str]:
    """Split an edit.music genre tag into atomic wiki tokens."""
    parts = _SEP.split(tag.strip())
    return [p.strip() for p in parts if p.strip()]


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

        # ── 3. Upsert GenreTokens ─────────────────────────────────────────
        self.stdout.write(f'  {len(wiki_token_counts)} wiki tokens')
        token_objs: dict[str, GenreToken] = {}
        for name, count in wiki_token_counts.items():
            if not name:
                continue
            sl = slugify(name)
            if not sl:
                continue
            if not dry:
                obj, _ = GenreToken.objects.update_or_create(
                    slug=sl,
                    defaults={'name': name, 'track_count': count},
                )
                token_objs[name] = obj
            else:
                self.stdout.write(f'    [dry] token: {name} ({count})')

        # ── 4. Build compound genres from multi-token tags ────────────────
        # A compound genre = a file tag that resolves to ≥2 wiki tokens,
        # with at least min_tracks files carrying that tag.
        compound_candidates: dict[frozenset[str], int] = defaultdict(int)
        for entry in raw_tokens:
            tag   = entry['name']
            count = entry['count']
            wtoks = tag_to_wiki.get(tag, [])
            if len(wtoks) >= 2:
                compound_candidates[frozenset(wtoks)] += count

        # Also promote co-occurring single-token pairs above threshold
        for pair in cooccurrence:
            a_toks = tag_to_wiki.get(pair['a'], wiki_tokenize(pair['a']))
            b_toks = tag_to_wiki.get(pair['b'], wiki_tokenize(pair['b']))
            combined = frozenset(a_toks + b_toks)
            if len(combined) >= 2:
                compound_candidates[combined] += pair['count']

        created = updated = skipped = 0
        for token_set, count in sorted(compound_candidates.items(), key=lambda x: -x[1]):
            if count < min_tracks:
                skipped += 1
                continue
            # Canonical name: tokens sorted alphabetically, joined with ", "
            sorted_names = sorted(token_set)
            name = ', '.join(sorted_names)
            sl   = slugify(name)
            if not sl:
                continue
            if dry:
                self.stdout.write(f'    [dry] compound: {name} ({count} tracks)')
                created += 1
                continue
            obj, is_new = CompoundGenre.objects.update_or_create(
                slug=sl,
                defaults={'name': name, 'track_count': count},
            )
            # Wire tokens
            toks_to_link = [
                token_objs[n] for n in sorted_names if n in token_objs
            ]
            if toks_to_link:
                obj.tokens.set(toks_to_link)
            if is_new:
                created += 1
            else:
                updated += 1

        # ── 5. Wire related edges from co-occurrence ──────────────────────
        if not dry:
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
