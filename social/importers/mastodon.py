"""
Generic Mastodon / ActivityPub importer.
Works for: pdx.sh, pnw.zone, musician.social, mastodon.art,
           drumstodon.net, ravenation.club, zirk.us, mastodon.social

Strategy:
  1. Try the local public timeline (works on most instances).
  2. If that returns empty or 4xx, fall back to fetching each tag in
     filter_tags via the hashtag timeline — works on mastodon.social and
     instances that lock down the public feed.

Tag pre-filtering is intentionally NOT done here: geofence_pdx sources pass
ALL posts to is_pdx_relevant(), which checks content + tags. Filtering only
by hashtag at fetch time would drop posts that mention Portland in body text
but forgot to tag it.
"""
import datetime
import requests
from .base import BaseImporter, RawPost, AccountMeta

TIMEOUT    = 20
PAGE_LIMIT = 40


class MastodonImporter(BaseImporter):
    protocol = 'mastodon'

    # ------------------------------------------------------------------
    # Public entry point
    # ------------------------------------------------------------------

    def fetch(self, since_id: str = '') -> list[RawPost]:
        posts = self._fetch_public(since_id)
        if not posts and self.source.get_filter_tags():
            posts = self._fetch_by_tags(since_id)
        return posts

    # ------------------------------------------------------------------
    # Public timeline
    # ------------------------------------------------------------------

    def _fetch_public(self, since_id: str) -> list[RawPost]:
        base   = self.source.instance_url.rstrip('/')
        params = {'local': 'true', 'limit': PAGE_LIMIT}
        if since_id:
            params['since_id'] = since_id

        headers = {}
        if self.source.access_token:
            headers['Authorization'] = f'Bearer {self.source.access_token}'

        try:
            resp = requests.get(
                f'{base}/api/v1/timelines/public',
                params=params, headers=headers, timeout=TIMEOUT,
            )
            if resp.status_code in (401, 403, 422):
                return []
            resp.raise_for_status()
            ct = resp.headers.get('content-type', '')
            if 'json' not in ct:
                return []
            return self._parse(resp.json())
        except Exception:
            return []

    # ------------------------------------------------------------------
    # Hashtag timeline fallback (works on mastodon.social etc.)
    # ------------------------------------------------------------------

    def _fetch_by_tags(self, since_id: str) -> list[RawPost]:
        base    = self.source.instance_url.rstrip('/')
        headers = {}
        if self.source.access_token:
            headers['Authorization'] = f'Bearer {self.source.access_token}'

        seen   = set()
        posts  = []
        params = {'limit': PAGE_LIMIT}
        if since_id:
            params['since_id'] = since_id

        for tag in self.source.get_filter_tags():
            try:
                resp = requests.get(
                    f'{base}/api/v1/timelines/tag/{tag}',
                    params=params, headers=headers, timeout=TIMEOUT,
                )
                resp.raise_for_status()
                ct = resp.headers.get('content-type', '')
                if 'json' not in ct:
                    continue
                for rp in self._parse(resp.json()):
                    if rp.remote_id not in seen:
                        seen.add(rp.remote_id)
                        posts.append(rp)
            except Exception:
                continue

        return posts

    # ------------------------------------------------------------------
    # Parser
    # ------------------------------------------------------------------

    def _parse(self, statuses: list) -> list[RawPost]:
        posts = []
        for s in statuses:
            if s.get('visibility') != 'public':
                continue
            if s.get('reblog'):
                continue

            tags       = [t['name'].lower() for t in s.get('tags', [])]
            acct       = s.get('account', {})
            html       = s.get('content', '')
            text       = self._strip_html(html)
            media_urls = [a['url'] for a in s.get('media_attachments', []) if a.get('url')]

            try:
                published_at = datetime.datetime.fromisoformat(
                    s['created_at'].replace('Z', '+00:00')
                )
            except Exception:
                published_at = None

            fields      = acct.get('fields', [])
            extra       = {f['name']: self._strip_html(f.get('value', '')) for f in fields}
            website     = next(
                (self._strip_html(f.get('value', '')) for f in fields
                 if any(k in f.get('name', '').lower()
                        for k in ('website', 'web', 'url', 'link', 'home'))),
                '',
            )
            account_meta = AccountMeta(
                display_name = acct.get('display_name', '') or acct.get('username', ''),
                username     = acct.get('acct', ''),
                url          = acct.get('url', ''),
                bio_text     = self._strip_html(acct.get('note', '')),
                avatar_url   = acct.get('avatar', ''),
                website      = website,
                extra_fields = extra,
            )

            posts.append(RawPost(
                remote_id        = s['id'],
                account_url      = acct.get('url', ''),
                account_username = acct.get('acct', ''),
                content_html     = html,
                content_text     = text,
                url              = s.get('url', ''),
                tags             = tags,
                media_urls       = media_urls,
                published_at     = published_at,
                account          = account_meta,
            ))
        return posts
