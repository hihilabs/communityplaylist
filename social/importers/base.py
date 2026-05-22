from dataclasses import dataclass, field
from typing import Optional
import re


PDX_TERMS = {
    # Core PDX
    'pdx', 'portland', 'pnw', 'oregon', 'stumptown', 'rose city',
    'willamette valley', 'willamette',
    # Oregon inner-ring / bedroom communities
    'beaverton', 'hillsboro', 'tigard', 'tualatin', 'sherwood',
    'lake oswego', 'west linn', 'milwaukie', 'gresham', 'troutdale',
    'happy valley', 'oregon city', 'gladstone', 'canby', 'sandy',
    'forest grove', 'cornelius',
    # Clark County / SW Washington
    'clark county', 'vancouver wa', 'camas', 'washougal', 'battleground',
}


@dataclass
class AccountMeta:
    """Fediverse account details carried alongside each post."""
    display_name: str = ''
    username:     str = ''      # acct@instance
    url:          str = ''
    bio_text:     str = ''      # stripped of HTML
    avatar_url:   str = ''
    website:      str = ''      # first website field from account.fields
    extra_fields: dict = field(default_factory=dict)   # label → value


@dataclass
class RawPost:
    remote_id:        str
    account_url:      str
    account_username: str
    content_html:     str
    content_text:     str
    url:              str
    tags:             list = field(default_factory=list)
    media_urls:       list = field(default_factory=list)
    published_at:     Optional[object] = None
    account:          Optional[AccountMeta] = None


class BaseImporter:
    protocol = ''

    def __init__(self, source):
        self.source = source

    def fetch(self, since_id: str = '') -> list[RawPost]:
        raise NotImplementedError

    def is_pdx_relevant(self, post: RawPost) -> bool:
        haystack = ' '.join([
            post.content_text.lower(),
            ' '.join(post.tags).lower(),
            post.account_username.lower(),
        ])
        return any(term in haystack for term in PDX_TERMS)

    def _strip_html(self, html: str) -> str:
        text = re.sub(r'<br\s*/?>', '\n', html)
        text = re.sub(r'</p>', '\n', text)
        text = re.sub(r'<[^>]+>', '', text)
        return text.strip()
