class WikiHostMiddleware:
    """Serve wiki at / when the host is wiki.* — avoids double /wiki prefix from Traefik addprefix."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        host = request.get_host().split(':')[0]
        if host.startswith('wiki.'):
            request.urlconf = 'communityplaylist.wiki_root_urls'
        return self.get_response(request)
