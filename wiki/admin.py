from django.contrib import admin
from .models import GenreToken, TokenAlias, TokenSource, CompoundGenre


class TokenAliasInline(admin.TabularInline):
    model = TokenAlias
    extra = 1


class TokenSourceInline(admin.TabularInline):
    model = TokenSource
    extra = 1


@admin.register(GenreToken)
class GenreTokenAdmin(admin.ModelAdmin):
    list_display  = ['name', 'bpm_min', 'bpm_max', 'energy', 'alias_count', 'compound_count']
    search_fields = ['name', 'aliases__alias']
    prepopulated_fields = {'slug': ('name',)}
    filter_horizontal = ['related']
    inlines = [TokenAliasInline, TokenSourceInline]

    def alias_count(self, obj):
        return obj.aliases.count()
    alias_count.short_description = 'Aliases'

    def compound_count(self, obj):
        return obj.compound_genres.count()
    compound_count.short_description = 'Compounds'


@admin.register(CompoundGenre)
class CompoundGenreAdmin(admin.ModelAdmin):
    list_display  = ['name', 'token_list', 'mb_id', 'lastfm_tag', 'discogs_style']
    search_fields = ['name', 'tokens__name']
    prepopulated_fields = {'slug': ('name',)}
    filter_horizontal = ['tokens']

    def token_list(self, obj):
        return ', '.join(t.name for t in obj.tokens.all())
    token_list.short_description = 'Tokens'


@admin.register(TokenAlias)
class TokenAliasAdmin(admin.ModelAdmin):
    list_display  = ['alias', 'token']
    search_fields = ['alias', 'token__name']
    list_select_related = ['token']


@admin.register(TokenSource)
class TokenSourceAdmin(admin.ModelAdmin):
    list_display  = ['token', 'source', 'confidence', 'source_name', 'listener_count']
    list_filter   = ['source', 'confidence']
    search_fields = ['token__name', 'source_name']
    list_select_related = ['token']
