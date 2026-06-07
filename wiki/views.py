import json
import re
import urllib.request
import urllib.parse

from django.conf import settings
from django.core.cache import cache
from django.shortcuts import get_object_or_404, render
from django.db.models import Q, Count
from django.http import JsonResponse
from django.views.decorators.cache import never_cache
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST
from .models import GenreToken, CompoundGenre, TokenAlias, LibraryReport


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


@never_cache
def genre_graph(request):
    from django.urls import reverse
    token_url_base = reverse('wiki:token_detail', args=['PLACEHOLDER']).replace('PLACEHOLDER/', '')
    return render(request, 'wiki/genre_graph.html', {'token_url_base': token_url_base})


@never_cache
def genre_tree(request):
    from django.urls import reverse
    token_url_base = reverse('wiki:token_detail', args=['PLACEHOLDER']).replace('PLACEHOLDER/', '')
    return render(request, 'wiki/genre_tree.html', {'token_url_base': token_url_base})


@never_cache
def genre_blob(request):
    from django.urls import reverse
    token_url_base = reverse('wiki:token_detail', args=['PLACEHOLDER']).replace('PLACEHOLDER/', '')
    return render(request, 'wiki/genre_blob.html', {'token_url_base': token_url_base})


@never_cache
def genre_orbital(request):
    from django.urls import reverse
    token_url_base = reverse('wiki:token_detail', args=['PLACEHOLDER']).replace('PLACEHOLDER/', '')
    return render(request, 'wiki/genre_orbital.html', {'token_url_base': token_url_base})


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
        .values('slug', 'name', 'track_count', 'bpm_min', 'bpm_max', 'energy',
                'origin_year', 'derived_from__slug', 'derived_from__name')
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


def _yt_search_scrape(q):
    """Find the first YouTube video ID for a query — no API key, no quota."""
    url = 'https://www.youtube.com/results?' + urllib.parse.urlencode({'search_query': q})
    req = urllib.request.Request(url, headers={
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36',
        'Accept-Language': 'en-US,en;q=0.9',
    })
    with urllib.request.urlopen(req, timeout=10) as r:
        html = r.read().decode('utf-8', errors='replace')
    m = re.search(r'"videoId":"([A-Za-z0-9_-]{11})"', html)
    return m.group(1) if m else None


def api_yt_search(request):
    """Proxy a YouTube video search, server-side cached so we don't burn quota on repeats."""
    q = request.GET.get('q', '').strip()
    if not q:
        return JsonResponse({'error': 'no query'}, status=400)

    cache_key = f'wiki_yt2_{urllib.parse.quote(q[:100])}'
    cached = cache.get(cache_key)
    if cached:
        return JsonResponse(cached)

    try:
        video_id = _yt_search_scrape(q)
    except Exception as e:
        return JsonResponse({'error': str(e)}, status=502)

    if not video_id:
        return JsonResponse({'error': 'no results'}, status=404)

    result = {'id': video_id}
    cache.set(cache_key, result, 60 * 60 * 24 * 30)  # 30-day cache
    return JsonResponse(result)


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


# Max sizes accepted from a single report — keeps ingest cheap and bounds abuse
_REPORT_MAX_TOKENS = 5000
_REPORT_MAX_PAIRS  = 50000
_REPORT_THROTTLE_SECONDS = 60 * 5


def _valid_count_list(items, key_fields, max_len):
    if not isinstance(items, list) or len(items) > max_len:
        return False
    for item in items:
        if not isinstance(item, dict):
            return False
        if not all(field in item for field in key_fields):
            return False
        if not isinstance(item.get('count'), int) or item['count'] < 0:
            return False
    return True


@csrf_exempt
@require_POST
def api_report(request):
    """Ingest an anonymized genre-stat snapshot from an opted-in edit.music install.
    Body: {install_id, tokens: [{name, count}], cooccurrence: [{a, b, count}]}
    No file paths, file names, or other personal data are accepted or stored —
    just aggregated token/pair counts (see edit.music's reporting module).
    """
    try:
        body = json.loads(request.body)
    except (ValueError, TypeError):
        return JsonResponse({'error': 'invalid JSON body'}, status=400)

    install_id = body.get('install_id')
    tokens = body.get('tokens', [])
    cooccurrence = body.get('cooccurrence', [])

    if not isinstance(install_id, str) or not (8 <= len(install_id) <= 64):
        return JsonResponse({'error': 'install_id required (8-64 chars)'}, status=400)
    if not _valid_count_list(tokens, ('name', 'count'), _REPORT_MAX_TOKENS):
        return JsonResponse({'error': 'tokens must be a list of {name, count} (max %d)' % _REPORT_MAX_TOKENS}, status=400)
    if not _valid_count_list(cooccurrence, ('a', 'b', 'count'), _REPORT_MAX_PAIRS):
        return JsonResponse({'error': 'cooccurrence must be a list of {a, b, count} (max %d)' % _REPORT_MAX_PAIRS}, status=400)

    throttle_key = f'report_throttle:{install_id}'
    if cache.get(throttle_key):
        return JsonResponse({'ok': True, 'throttled': True})
    cache.set(throttle_key, True, _REPORT_THROTTLE_SECONDS)

    LibraryReport.objects.update_or_create(
        install_id=install_id,
        defaults={'tokens_json': tokens, 'cooccurrence_json': cooccurrence},
    )
    return JsonResponse({'ok': True})
