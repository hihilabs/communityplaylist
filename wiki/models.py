from django.db import models
from django.utils.text import slugify
from django.core.validators import URLValidator

_safe_url = URLValidator(schemes=['http', 'https'])


class GenreToken(models.Model):
    """Atomic genre token — the building block of the taxonomy.
    'Hip', 'Hop', 'Drum', 'Bass', 'Deep', 'House' etc.
    Compound genres are made of one or more tokens joined together.
    """
    name        = models.CharField(max_length=100, unique=True)
    slug        = models.SlugField(max_length=120, unique=True)
    description = models.TextField(blank=True)

    # BPM range typical for tracks carrying this token
    bpm_min = models.PositiveSmallIntegerField(null=True, blank=True)
    bpm_max = models.PositiveSmallIntegerField(null=True, blank=True)

    ENERGY_CHOICES = [
        ('low',       'Low'),
        ('mid',       'Mid'),
        ('high',      'High'),
        ('very_high', 'Very High'),
    ]
    energy = models.CharField(max_length=10, choices=ENERGY_CHOICES, blank=True)
    mood   = models.CharField(max_length=300, blank=True, help_text='Comma-separated mood descriptors')

    # Peer tokens with shared sonic DNA (graph edges, undirected)
    related = models.ManyToManyField('self', blank=True, symmetrical=True,
                                     help_text='Tokens that share sonic or cultural DNA')

    track_count = models.PositiveIntegerField(default=0,
                                              help_text='Tracks in library carrying this token (updated by sync)')

    # Lineage — origin year + parent genre (for chronological tree)
    origin_year = models.SmallIntegerField(
        null=True, blank=True,
        help_text='Year the genre emerged (filled by Wikipedia enrichment)',
    )
    derived_from = models.ForeignKey(
        'self', null=True, blank=True, on_delete=models.SET_NULL,
        related_name='derivatives',
        help_text='Parent genre this one split from (for chronological tree)',
    )

    # Discovery content — populated by enrich_genre_tokens --lastfm-tracks --youtube
    top_tracks_json = models.JSONField(
        default=list, blank=True,
        help_text='Top tracks from Last.fm: [{name, artist, playcount, lastfm_url}]',
    )
    youtube_video_id = models.CharField(
        max_length=20, blank=True,
        help_text='YouTube video ID for genre overview/mix (populated by enrichment)',
    )

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['name']
        verbose_name = 'Genre Token'

    def save(self, *args, **kwargs):
        if not self.slug:
            self.slug = slugify(self.name)
        super().save(*args, **kwargs)

    def __str__(self):
        return self.name

    def get_absolute_url(self):
        from django.urls import reverse
        return reverse('wiki:token_detail', kwargs={'slug': self.slug})


class TokenAlias(models.Model):
    """Known variant spellings / synonyms for a token.
    Seeds the edit.music normalize map and powers fuzzy lookup.
    e.g.  'dnb', 'drum n bass', 'drum&bass', 'Drum N Bass'  →  GenreToken('Drum & Bass')
    """
    token = models.ForeignKey(GenreToken, on_delete=models.CASCADE, related_name='aliases')
    alias = models.CharField(max_length=200)
    notes = models.CharField(max_length=300, blank=True)

    class Meta:
        unique_together = [('token', 'alias')]
        verbose_name        = 'Token Alias'
        verbose_name_plural = 'Token Aliases'
        ordering = ['alias']

    def __str__(self):
        return f'{self.alias} → {self.token.name}'


SOURCE_CHOICES = [
    ('wikipedia',     'Wikipedia'),
    ('musicbrainz',   'MusicBrainz'),
    ('lastfm',        'Last.fm'),
    ('discogs',       'Discogs'),
    ('listenbrainz',  'ListenBrainz'),
    ('beatport',      'Beatport'),
    ('allmusic',      'AllMusic'),
    ('rateyourmusic', 'RateYourMusic'),
    ('community',     'Community'),
    ('editmusic',     'edit.music library'),
]

CONFIDENCE_CHOICES = [
    ('verified',  'Verified'),
    ('consensus', 'Community Consensus'),
    ('derived',   'Derived from data'),
    ('proposed',  'Proposed'),
]


class TokenSource(models.Model):
    """Attribution record — every data point traces back to a source.
    The wiki's homage to the services that built the knowledge before us.
    """
    token       = models.ForeignKey(GenreToken, on_delete=models.CASCADE, related_name='sources')
    source      = models.CharField(max_length=20, choices=SOURCE_CHOICES)
    source_name = models.CharField(max_length=200, blank=True,
                                   help_text='Name of the entry on the source (may differ from our token name)')
    source_url  = models.URLField(blank=True, validators=[_safe_url])
    confidence  = models.CharField(max_length=20, choices=CONFIDENCE_CHOICES, default='derived')
    listener_count = models.PositiveIntegerField(null=True, blank=True,
                                                  help_text='Last.fm listeners, Beatport chart position, etc.')
    notes       = models.TextField(blank=True)
    fetched_at  = models.DateTimeField(null=True, blank=True)

    class Meta:
        unique_together = [('token', 'source')]
        ordering = ['source']
        verbose_name = 'Token Source'

    def __str__(self):
        return f'{self.token.name} ← {self.get_source_display()}'


class CompoundGenre(models.Model):
    """A well-known compound genre composed of tokens.
    'Hip Hop' = tokens [Hip, Hop].  'Drum & Bass' = tokens [Drum, Bass].
    These are the canonical display names used in file tags.
    """
    name      = models.CharField(max_length=200, unique=True)
    slug      = models.SlugField(max_length=220, unique=True)
    tokens    = models.ManyToManyField(GenreToken, related_name='compound_genres')
    description = models.TextField(blank=True)
    track_count = models.PositiveIntegerField(default=0,
                                              help_text='Tracks in library with this exact compound (updated by sync)')

    # Platform-native equivalents (may differ from our canonical name)
    mb_id         = models.CharField(max_length=40, blank=True, verbose_name='MusicBrainz ID')
    lastfm_tag    = models.CharField(max_length=200, blank=True)
    discogs_style = models.CharField(max_length=200, blank=True)
    beatport_name = models.CharField(max_length=200, blank=True)
    wikipedia_url = models.URLField(blank=True, validators=[_safe_url])

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['name']
        verbose_name = 'Compound Genre'

    def save(self, *args, **kwargs):
        if not self.slug:
            self.slug = slugify(self.name)
        super().save(*args, **kwargs)

    def __str__(self):
        return self.name

    def get_absolute_url(self):
        from django.urls import reverse
        return reverse('wiki:genre_detail', kwargs={'slug': self.slug})
