"""
Import edit.music genre-map.json into the wiki.

Usage:
    python manage.py import_genre_map /path/to/genre-map.json

Each mapping  variant → canonical  becomes:
  - A GenreToken for each word in the canonical (if not already present)
  - A CompoundGenre for the canonical (if multi-token)
  - A TokenAlias linking the variant back to the canonical token(s)
  - A TokenSource record crediting edit.music library data
"""
import json
from pathlib import Path
from django.core.management.base import BaseCommand, CommandError
from django.utils.text import slugify
from wiki.models import GenreToken, TokenAlias, TokenSource, CompoundGenre


PROTECTED_PHRASES = {'Drum & Bass', 'R&B', 'UK Garage', 'Trip Hop', 'Hip Hop'}


def tokenize(name: str) -> list[str]:
    """Split a canonical genre name into tokens (respects common phrases)."""
    # Treat comma-separated as already tokenized
    if ',' in name:
        return [t.strip() for t in name.split(',') if t.strip()]
    # Single word or protected phrase → one token
    return [name.strip()]


class Command(BaseCommand):
    help = 'Import edit.music genre-map.json into the Genre Wiki'

    def add_arguments(self, parser):
        parser.add_argument('path', type=str, help='Path to genre-map.json')
        parser.add_argument('--dry-run', action='store_true', help='Preview without saving')

    def handle(self, *args, **options):
        path = Path(options['path'])
        if not path.exists():
            raise CommandError(f'File not found: {path}')

        genre_map: dict = json.loads(path.read_text())
        dry = options['dry_run']

        tokens_created    = 0
        aliases_created   = 0
        compounds_created = 0
        sources_created   = 0

        for variant, canonical in genre_map.items():
            if not canonical:
                self.stdout.write(f'  skip (discard mapping): {variant}')
                continue

            token_names = tokenize(canonical)

            created_tokens = []
            for tname in token_names:
                slug = slugify(tname)
                if not dry:
                    tok, created = GenreToken.objects.get_or_create(
                        slug=slug,
                        defaults={'name': tname},
                    )
                    if created:
                        tokens_created += 1
                    created_tokens.append(tok)

                    # Attribution
                    _, src_created = TokenSource.objects.get_or_create(
                        token=tok,
                        source='editmusic',
                        defaults={
                            'source_name': canonical,
                            'confidence':  'derived',
                            'notes':       f'Imported from genre-map.json; variant: {variant}',
                        },
                    )
                    if src_created:
                        sources_created += 1

                    # Alias: map the variant → first token (close enough for search)
                    if tname == token_names[0]:
                        _, al_created = TokenAlias.objects.get_or_create(
                            token=tok,
                            alias=variant,
                        )
                        if al_created:
                            aliases_created += 1
                else:
                    self.stdout.write(f'  [dry] token: {tname!r}  alias: {variant!r} → canonical: {canonical!r}')

            # If multi-token canonical → create CompoundGenre
            if len(created_tokens) > 1 and not dry:
                cslug = slugify(canonical.replace(',', '').replace('&', 'and'))
                cg, cg_created = CompoundGenre.objects.get_or_create(
                    slug=cslug,
                    defaults={'name': canonical},
                )
                cg.tokens.set(created_tokens)
                if cg_created:
                    compounds_created += 1

        self.stdout.write(self.style.SUCCESS(
            f'\nDone{"(dry run)" if dry else ""}:\n'
            f'  {tokens_created} tokens\n'
            f'  {aliases_created} aliases\n'
            f'  {compounds_created} compound genres\n'
            f'  {sources_created} source records\n'
        ))
