from django.shortcuts import get_object_or_404, render
from django.db.models import Q, Count
from django.http import JsonResponse
from .models import GenreToken, CompoundGenre, TokenAlias


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
    return render(request, 'wiki/token_list.html', {
        'tokens': tokens,
        'compounds': compounds,
        'q': q,
        'total_tokens': GenreToken.objects.count(),
        'total_compounds': CompoundGenre.objects.count(),
    })


def token_detail(request, slug):
    token = get_object_or_404(GenreToken.objects.prefetch_related(
        'aliases', 'sources', 'related', 'compound_genres'
    ), slug=slug)
    return render(request, 'wiki/token_detail.html', {'token': token})


def genre_detail(request, slug):
    genre = get_object_or_404(CompoundGenre.objects.prefetch_related('tokens__sources'), slug=slug)
    return render(request, 'wiki/genre_detail.html', {'genre': genre})


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
