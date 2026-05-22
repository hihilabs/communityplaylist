"""
Mastodon poster — hook / stub.
Swap self._instance_url and self._access_token per target instance.
API ref: https://docs.joinmastodon.org/methods/statuses/
"""
import requests
from .base import BasePlatform, PostResult


class MastodonPlatform(BasePlatform):
    platform_key = 'mastodon'

    def __init__(self, instance_url: str, access_token: str):
        self._instance_url = instance_url.rstrip('/')
        self._access_token = access_token

    def post(self, text: str, url: str = '', image_url: str = '') -> PostResult:
        if not self._access_token:
            return PostResult(success=False, error='Mastodon access_token not configured')

        try:
            resp = requests.post(
                f'{self._instance_url}/api/v1/statuses',
                headers={'Authorization': f'Bearer {self._access_token}'},
                json={'status': text, 'visibility': 'public'},
                timeout=15,
            )
            resp.raise_for_status()
            data = resp.json()
            return PostResult(
                success=True,
                post_id=data.get('id', ''),
                post_url=data.get('url', ''),
            )
        except Exception as exc:
            return PostResult(success=False, error=str(exc))
