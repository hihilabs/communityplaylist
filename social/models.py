from django.db import models


class SocialPost(models.Model):
    PLATFORM_BLUESKY  = 'bluesky'
    PLATFORM_MASTODON = 'mastodon'
    PLATFORM_CHOICES  = [
        (PLATFORM_BLUESKY,  'Bluesky'),
        (PLATFORM_MASTODON, 'Mastodon'),
    ]

    TYPE_RECORD  = 'record'
    TYPE_PROFILE = 'profile'
    TYPE_ZINE    = 'zine'
    TYPE_CHOICES = [
        (TYPE_RECORD,  'Record for Sale'),
        (TYPE_PROFILE, 'Artist / Crew Profile'),
        (TYPE_ZINE,    'Zine / Board Post'),
    ]

    platform     = models.CharField(max_length=20, choices=PLATFORM_CHOICES)
    post_type    = models.CharField(max_length=20, choices=TYPE_CHOICES)
    object_model = models.CharField(max_length=50)   # 'RecordListing', 'Artist', etc.
    object_id    = models.PositiveIntegerField()
    text         = models.TextField(blank=True)
    post_id      = models.CharField(max_length=300, blank=True)   # platform-native ID / URI
    post_url     = models.URLField(blank=True)
    success      = models.BooleanField(default=True)
    error        = models.TextField(blank=True)
    posted_at    = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-posted_at']

    def __str__(self):
        return f'[{self.platform}] {self.post_type} #{self.object_id} — {self.posted_at:%Y-%m-%d}'


class FediverseSource(models.Model):
    PROTOCOL_MASTODON  = 'mastodon'
    PROTOCOL_PIXELFED  = 'pixelfed'
    PROTOCOL_FUNKWHALE = 'funkwhale'
    PROTOCOL_CHOICES   = [
        (PROTOCOL_MASTODON,  'Mastodon / ActivityPub'),
        (PROTOCOL_PIXELFED,  'Pixelfed'),
        (PROTOCOL_FUNKWHALE, 'Funkwhale'),
    ]

    FOCUS_REGIONAL = 'regional'
    FOCUS_MUSIC    = 'music'
    FOCUS_ART      = 'art'
    FOCUS_WRITERS  = 'writers'
    FOCUS_GENERAL  = 'general'
    FOCUS_CHOICES  = [
        (FOCUS_REGIONAL, 'Regional (PDX / PNW)'),
        (FOCUS_MUSIC,    'Music & Audio'),
        (FOCUS_ART,      'Visual Art & Design'),
        (FOCUS_WRITERS,  'Writers & Creatives'),
        (FOCUS_GENERAL,  'General'),
    ]

    name         = models.CharField(max_length=100)
    instance_url = models.URLField(help_text='e.g. https://pdx.sh')
    protocol     = models.CharField(max_length=20, choices=PROTOCOL_CHOICES, default=PROTOCOL_MASTODON)
    focus        = models.CharField(max_length=20, choices=FOCUS_CHOICES, default=FOCUS_GENERAL)
    # Comma-separated hashtags to look for (no #). Empty = accept all.
    filter_tags  = models.TextField(
        blank=True,
        help_text='Comma-separated tags to filter for (e.g. "pdx,portland,pnw"). Empty = accept all.',
    )
    # True = only keep posts that look PDX/PNW-relevant
    geofence_pdx = models.BooleanField(default=True)
    access_token = models.CharField(max_length=300, blank=True, help_text='OAuth token for non-public instances')
    active       = models.BooleanField(default=True)
    last_synced  = models.DateTimeField(null=True, blank=True)
    notes        = models.TextField(blank=True)

    class Meta:
        ordering = ['focus', 'name']
        verbose_name = 'Fediverse Source'

    def __str__(self):
        return f'{self.name} ({self.instance_url})'

    def get_filter_tags(self):
        return [t.strip().lower() for t in self.filter_tags.split(',') if t.strip()]


class FediversePost(models.Model):
    source           = models.ForeignKey(FediverseSource, on_delete=models.CASCADE, related_name='posts')
    remote_id        = models.CharField(max_length=300)
    account_url      = models.URLField(blank=True)
    account_username = models.CharField(max_length=150)
    content_html     = models.TextField()
    content_text     = models.TextField(blank=True)
    url              = models.URLField()
    tags             = models.JSONField(default=list)
    media_urls       = models.JSONField(default=list)
    published_at     = models.DateTimeField()
    fetched_at       = models.DateTimeField(auto_now_add=True)
    is_pdx_relevant  = models.BooleanField(default=False, db_index=True)

    class Meta:
        unique_together = [('source', 'remote_id')]
        ordering = ['-published_at']

    def __str__(self):
        return f'@{self.account_username}@{self.source.instance_url} — {self.published_at:%Y-%m-%d}'
