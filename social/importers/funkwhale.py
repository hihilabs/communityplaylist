"""
Funkwhale importer — stub.
Funkwhale exposes both ActivityPub and its own REST API.
API ref: https://docs.funkwhale.audio/api/index.html
"""
import requests
from .base import BaseImporter, RawPost

TIMEOUT = 20


class FunkwhaleImporter(BaseImporter):
    protocol = 'funkwhale'

    def fetch(self, since_id: str = '') -> list[RawPost]:
        # TODO: use /api/v1/tracks/ or /api/v1/listen/ endpoints
        # and map tracks to RawPost so they can surface in the fediverse feed.
        base = self.source.instance_url.rstrip('/')
        try:
            resp = requests.get(
                f'{base}/api/v1/tracks/',
                params={'ordering': '-creation_date', 'page_size': 40},
                timeout=TIMEOUT,
            )
            resp.raise_for_status()
            # TODO: parse resp.json()['results'] into RawPost list
        except Exception:
            pass
        return []
