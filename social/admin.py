from django.contrib import admin
from django.utils.html import format_html
from .models import SocialPost, FediverseSource, FediversePost


@admin.register(SocialPost)
class SocialPostAdmin(admin.ModelAdmin):
    list_display    = ('posted_at', 'platform', 'post_type', 'object_model', 'object_id', 'success', 'post_link')
    list_filter     = ('platform', 'post_type', 'success')
    readonly_fields = ('posted_at', 'post_link')
    ordering        = ('-posted_at',)

    @admin.display(description='Post')
    def post_link(self, obj):
        if obj.post_url:
            return format_html('<a href="{}" target="_blank">↗ view</a>', obj.post_url)
        return '—'


@admin.register(FediverseSource)
class FediverseSourceAdmin(admin.ModelAdmin):
    list_display    = ('name', 'instance_url', 'protocol', 'focus', 'geofence_badge', 'active', 'last_synced', 'post_count')
    list_filter     = ('protocol', 'focus', 'active', 'geofence_pdx')
    search_fields   = ('name', 'instance_url')
    readonly_fields = ('last_synced', 'post_count')
    fieldsets = (
        (None, {'fields': ('name', 'instance_url', 'protocol', 'focus', 'active')}),
        ('PDX Filter', {
            'description': 'When geofence is ON, only posts containing PDX/PNW terms are saved.',
            'fields': ('geofence_pdx', 'filter_tags'),
        }),
        ('Auth', {'fields': ('access_token',), 'classes': ('collapse',)}),
        ('Info', {'fields': ('last_synced', 'post_count', 'notes'), 'classes': ('collapse',)}),
    )
    actions = ['enable_geofence', 'disable_geofence', 'toggle_active']

    @admin.display(description='Geofence', boolean=True)
    def geofence_badge(self, obj):
        return obj.geofence_pdx

    @admin.display(description='Posts')
    def post_count(self, obj):
        return obj.posts.count()

    @admin.action(description='Enable PDX geofence on selected sources')
    def enable_geofence(self, request, queryset):
        queryset.update(geofence_pdx=True)

    @admin.action(description='Disable PDX geofence on selected sources')
    def disable_geofence(self, request, queryset):
        queryset.update(geofence_pdx=False)

    @admin.action(description='Toggle active on selected sources')
    def toggle_active(self, request, queryset):
        for src in queryset:
            src.active = not src.active
            src.save(update_fields=['active'])


@admin.register(FediversePost)
class FediversePostAdmin(admin.ModelAdmin):
    list_display    = ('account_username', 'source', 'published_at', 'pdx_badge', 'post_link', 'fetched_at')
    list_filter     = ('source', 'is_pdx_relevant', 'source__focus')
    search_fields   = ('account_username', 'content_text')
    readonly_fields = ('fetched_at', 'post_link')
    ordering        = ('-published_at',)

    @admin.display(description='PDX', boolean=True)
    def pdx_badge(self, obj):
        return obj.is_pdx_relevant

    @admin.display(description='Source post')
    def post_link(self, obj):
        if obj.url:
            return format_html('<a href="{}" target="_blank">↗ view</a>', obj.url)
        return '—'
