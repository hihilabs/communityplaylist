from django.contrib import admin
from .models import Ticket, OpsEvent


@admin.register(Ticket)
class TicketAdmin(admin.ModelAdmin):
    list_display  = ('title', 'ticket_type', 'priority', 'status', 'project', 'created_by', 'created_at')
    list_filter   = ('ticket_type', 'status', 'priority', 'project')
    search_fields = ('title', 'description')
    readonly_fields = ('created_at', 'updated_at', 'resolved_at')
    list_editable = ('status', 'priority')


@admin.register(OpsEvent)
class OpsEventAdmin(admin.ModelAdmin):
    list_display  = ('action', 'success', 'triggered_by', 'created_at')
    list_filter   = ('action', 'success')
    readonly_fields = ('created_at',)
