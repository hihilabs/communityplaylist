from dataclasses import dataclass, field
from typing import Optional


@dataclass
class PostResult:
    success:  bool
    post_id:  str = ''
    post_url: str = ''
    error:    str = ''


class BasePlatform:
    platform_key = ''

    def post(self, text: str, url: str = '', image_url: str = '') -> PostResult:
        raise NotImplementedError

    def _build_facets(self, text: str, links: list[tuple[str, str]]) -> list:
        """
        Build AT Protocol / Mastodon-compatible rich-text facets.
        links: list of (uri, display_text) — display_text must appear verbatim in text.
        Returns facets using UTF-8 byte offsets (required by AT Protocol).
        """
        facets = []
        text_bytes = text.encode('utf-8')
        for uri, display in links:
            display_bytes = display.encode('utf-8')
            start = text_bytes.find(display_bytes)
            if start < 0:
                continue
            facets.append({
                '$type': 'app.bsky.richtext.facet',
                'index': {
                    '$type': 'app.bsky.richtext.facet#byteSlice',
                    'byteStart': start,
                    'byteEnd': start + len(display_bytes),
                },
                'features': [{'$type': 'app.bsky.richtext.facet#link', 'uri': uri}],
            })
        return facets
