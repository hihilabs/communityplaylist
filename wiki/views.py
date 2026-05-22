import json
import urllib.request
import urllib.parse

from django.conf import settings
from django.core.cache import cache
from django.shortcuts import get_object_or_404, render
from django.db.models import Q, Count
from django.http import JsonResponse
from .models import GenreToken, CompoundGenre, TokenAlias


_SOURCE_LABELS = {
    'lastfm':       'Last.fm',
    'wikipedia':    'Wikipedia',
    'musicbrainz':  'MusicBrainz',
    'discogs':      'Discogs',
    'listenbrainz': 'ListenBrainz',
    'editmusic':    'edit.music',
    'beatport':     'Beatport',
    'allmusic':     'AllMusic',
}
_SOURCE_URLS = {
    'lastfm':       'https://www.last.fm',
    'wikipedia':    'https://en.wikipedia.org',
    'musicbrainz':  'https://musicbrainz.org',
    'discogs':      'https://www.discogs.com',
    'listenbrainz': 'https://listenbrainz.org',
    'editmusic':    'http://10.0.0.124:3001',
    'beatport':     'https://www.beatport.com',
    'allmusic':     'https://www.allmusic.com',
}


def token_list(request):
    q = request.GET.get('q', '').strip()
    tokens = GenreToken.objects.annotate(
        compound_count=Count('compound_genres', distinct=True),
        alias_count=Count('aliases', distinct=True),
    )
    if q:
        tokens = tokens.filter(
            Q(name__icontains=q) |
            Q(aliases__alias__icontains=q) |
            Q(compound_genres__name__icontains=q)
        ).distinct()
    tokens = tokens.order_by('name')
    compounds = CompoundGenre.objects.annotate(token_count=Count('tokens')).order_by('name')
    if q:
        compounds = compounds.filter(
            Q(name__icontains=q) | Q(tokens__name__icontains=q)
        ).distinct()

    # Build live source list — only show sources that actually have data
    from wiki.models import TokenSource
    live_sources = []
    for row in (TokenSource.objects
                .exclude(source='editmusic')   # library itself, not an external source
                .values('source')
                .annotate(n=Count('id'))
                .filter(n__gt=0)
                .order_by('-n')):
        src = row['source']
        live_sources.append({
            'label': _SOURCE_LABELS.get(src, src),
            'url':   _SOURCE_URLS.get(src, '#'),
        })

    return render(request, 'wiki/token_list.html', {
        'tokens':          tokens,
        'compounds':       compounds,
        'q':               q,
        'total_tokens':    GenreToken.objects.count(),
        'total_compounds': CompoundGenre.objects.count(),
        'live_sources':    live_sources,
    })


def token_detail(request, slug):
    token = get_object_or_404(GenreToken.objects.prefetch_related(
        'aliases', 'sources', 'related', 'compound_genres',
        'derived_from', 'derivatives',
    ), slug=slug)
    # When a token has no direct track data, surface its richest compound genres
    # so the template can guide the user toward actual audio examples.
    fallback_compounds = []
    if not token.top_tracks_json:
        fallback_compounds = list(
            token.compound_genres.order_by('-track_count')[:4]
        )
    return render(request, 'wiki/token_detail.html', {
        'token': token,
        'fallback_compounds': fallback_compounds,
    })


def genre_detail(request, slug):
    genre = get_object_or_404(CompoundGenre.objects.prefetch_related('tokens__sources'), slug=slug)
    return render(request, 'wiki/genre_detail.html', {'genre': genre})


def genre_graph(request):
    return render(request, 'wiki/genre_graph.html', {})


def genre_tree(request):
    return render(request, 'wiki/genre_tree.html', {})


def api_tree_data(request):
    """JSON payload for the chronological tree — nodes with origin_year + parent links."""
    cached = cache.get('wiki_tree_data_v1')
    if cached:
        return JsonResponse(cached)

    tokens = list(
        GenreToken.objects
        .filter(origin_year__isnull=False)
        .select_related('derived_from')
        .values('slug', 'name', 'track_count', 'origin_year',
                'derived_from__slug', 'derived_from__name')
    )
    nodes = []
    for t in tokens:
        nodes.append({
            'slug':        t['slug'],
            'name':        t['name'],
            'track_count': t['track_count'],
            'year':        t['origin_year'],
            'parent':      t['derived_from__slug'],
        })

    data = {'nodes': nodes}
    cache.set('wiki_tree_data_v1', data, 60 * 60)
    return JsonResponse(data)


def api_graph_data(request):
    """JSON payload for the D3.js force graph — nodes (tokens) + links (related edges)."""
    cached = cache.get('wiki_graph_data_v1')
    if cached:
        return JsonResponse(cached)

    tokens = list(
        GenreToken.objects
        .prefetch_related('related')
        .values('slug', 'name', 'track_count', 'bpm_min', 'bpm_max', 'energy')
    )
    slug_index = {t['slug']: t for t in tokens}

    # Build undirected edges from the symmetric related M2M
    seen = set()
    links = []
    for token_obj in GenreToken.objects.prefetch_related('related').only('slug'):
        for rel in token_obj.related.only('slug'):
            a, b = sorted([token_obj.slug, rel.slug])
            if (a, b) not in seen:
                seen.add((a, b))
                links.append({'source': a, 'target': b})

    data = {'nodes': tokens, 'links': links}
    cache.set('wiki_graph_data_v1', data, 60 * 60)
    return JsonResponse(data)


def api_yt_search(request):
    """Proxy a YouTube video search, server-side cached so we don't burn quota on repeats."""
    q = request.GET.get('q', '').strip()
    if not q:
        return JsonResponse({'error': 'no query'}, status=400)

    cache_key = f'wiki_yt_{urllib.parse.quote(q[:100])}'
    cached = cache.get(cache_key)
    if cached:
        return JsonResponse(cached)

    api_key = getattr(settings, 'YOUTUBE_API_KEY', '')
    if not api_key:
        return JsonResponse({'error': 'no key'}, status=503)

    params = urllib.parse.urlencode({
        'part': 'snippet', 'q': q, 'type': 'video',
        'videoCategoryId': '10', 'maxResults': 1, 'key': api_key,
    })
    try:
        req = urllib.request.Request(
            f'https://www.googleapis.com/youtube/v3/search?{params}',
            headers={'User-Agent': 'CommunityPlaylistWiki/1.0'},
        )
        with urllib.request.urlopen(req, timeout=8) as r:
            data = json.load(r)
        items = data.get('items', [])
        if not items:
            return JsonResponse({'error': 'no results'}, status=404)
        item = items[0]
        result = {
            'id':    item['id']['videoId'],
            'title': item['snippet']['title'],
            'thumb': item['snippet']['thumbnails'].get('default', {}).get('url', ''),
        }
        cache.set(cache_key, result, 60 * 60 * 24 * 30)  # 30-day cache
        return JsonResponse(result)
    except Exception as e:
        return JsonResponse({'error': str(e)}, status=502)


def api_search(request):
    """JSON search — used by edit.music and future integrations."""
    q = request.GET.get('q', '').strip()
    if not q or len(q) < 2:
        return JsonResponse({'tokens': [], 'compounds': []})

    tokens = list(GenreToken.objects.filter(
        Q(name__icontains=q) | Q(aliases__alias__icontains=q)
    ).distinct().values('name', 'slug', 'bpm_min', 'bpm_max', 'energy'))

    compounds = list(CompoundGenre.objects.filter(
        Q(name__icontains=q) | Q(tokens__name__icontains=q)
    ).distinct().values('name', 'slug'))

    return JsonResponse({'tokens': tokens, 'compounds': compounds})
