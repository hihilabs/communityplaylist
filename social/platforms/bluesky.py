"""
Bluesky poster via AT Protocol.
Docs: https://atproto.com/lexicons/com-atproto-repo
"""
import datetime
import requests
from django.conf import settings
from .base import BasePlatform, PostResult

BSKY_HOST = 'https://bsky.social'


class BlueskyPlatform(BasePlatform):
    platform_key = 'bluesky'

    def __init__(self):
        self.handle   = getattr(settings, 'BLUESKY_HANDLE', '')
        self.password = getattr(settings, 'BLUESKY_APP_PASSWORD', '')
        self._session = None

    def _authenticate(self):
        resp = requests.post(
            f'{BSKY_HOST}/xrpc/com.atproto.server.createSession',
            json={'identifier': self.handle, 'password': self.password},
            timeout=15,
        )
        resp.raise_for_status()
        data = resp.json()
        self._session = {'did': data['did'], 'accessJwt': data['accessJwt']}

    def _auth_headers(self):
        if not self._session:
            self._authenticate()
        return {'Authorization': f'Bearer {self._session["accessJwt"]}'}

    def post(self, text: str, url: str = '', image_url: str = '') -> PostResult:
        if not self.handle or not self.password:
            return PostResult(success=False, error='BLUESKY_HANDLE / BLUESKY_APP_PASSWORD not configured')

        try:
            self._authenticate()

            links  = [(url, url)] if url and url in text else []
            facets = self._build_facets(text, links)

            record: dict = {
                '$type':     'app.bsky.feed.post',
                'text':      text,
                'createdAt': datetime.datetime.utcnow().strftime('%Y-%m-%dT%H:%M:%S.000Z'),
                'langs':     ['en-US'],
            }
            if facets:
                record['facets'] = facets

            resp = requests.post(
                f'{BSKY_HOST}/xrpc/com.atproto.repo.createRecord',
                headers=self._auth_headers(),
                json={
                    'repo':       self._session['did'],
                    'collection': 'app.bsky.feed.post',
                    'record':     record,
                },
                timeout=15,
            )
            resp.raise_for_status()
            data     = resp.json()
            post_id  = data.get('uri', '')
            rkey     = post_id.split('/')[-1] if post_id else ''
            post_url = f'https://bsky.app/profile/{self.handle}/post/{rkey}' if rkey else ''
            return PostResult(success=True, post_id=post_id, post_url=post_url)

        except Exception as exc:
            return PostResult(success=False, error=str(exc))
