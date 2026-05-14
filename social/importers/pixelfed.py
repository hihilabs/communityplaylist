"""
Pixelfed importer — stub.
Pixelfed exposes a Mastodon-compatible API, so MastodonImporter works as-is.
This module exists as a named hook for Pixelfed-specific logic (e.g. album handling).
"""
from .mastodon import MastodonImporter


class PixelfedImporter(MastodonImporter):
    protocol = 'pixelfed'
