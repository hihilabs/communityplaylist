from django import template
from urllib.parse import urlparse

register = template.Library()

@register.filter
def safe_url(value):
    """Return the URL only if scheme is http or https — empty string otherwise."""
    if not value:
        return ''
    try:
        parsed = urlparse(str(value))
        if parsed.scheme in ('http', 'https'):
            return value
    except Exception:
        pass
    return ''
