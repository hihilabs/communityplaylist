from django.db import models
from django.contrib.auth import get_user_model

User = get_user_model()


class Ticket(models.Model):
    TYPE_CHOICES = [
        ('bug',     'Bug'),
        ('feature', 'Feature Request'),
        ('task',    'Task'),
        ('infra',   'Infrastructure'),
    ]
    STATUS_CHOICES = [
        ('open',       'Open'),
        ('in_progress','In Progress'),
        ('done',       'Done'),
        ('closed',     'Closed'),
    ]
    PRIORITY_CHOICES = [
        ('low',    'Low'),
        ('medium', 'Medium'),
        ('high',   'High'),
        ('urgent', 'Urgent'),
    ]

    title       = models.CharField(max_length=200)
    description = models.TextField(blank=True)
    ticket_type = models.CharField(max_length=20, choices=TYPE_CHOICES, default='task')
    status      = models.CharField(max_length=20, choices=STATUS_CHOICES, default='open')
    priority    = models.CharField(max_length=20, choices=PRIORITY_CHOICES, default='medium')
    project     = models.CharField(max_length=100, blank=True, help_text='Which project/module this belongs to')
    created_by  = models.ForeignKey(User, null=True, blank=True, on_delete=models.SET_NULL, related_name='ops_tickets')
    created_at  = models.DateTimeField(auto_now_add=True)
    updated_at  = models.DateTimeField(auto_now=True)
    resolved_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f'[{self.get_ticket_type_display()}] {self.title}'


class OpsEvent(models.Model):
    """Audit log for ops panel actions (git pull, reload, etc.)."""
    ACTION_CHOICES = [
        ('git_pull',        'Git Pull'),
        ('git_status',      'Git Status'),
        ('git_log',         'Git Log'),
        ('git_diff',        'Git Diff'),
        ('collectstatic',   'Collect Static'),
        ('sync_genre_wiki', 'Sync Genre Wiki'),
        ('reload',          'Gunicorn Reload'),
        ('ticket_create',   'Ticket Created'),
        ('other',           'Other'),
    ]

    action     = models.CharField(max_length=40, choices=ACTION_CHOICES)
    triggered_by = models.ForeignKey(User, null=True, blank=True, on_delete=models.SET_NULL)
    output     = models.TextField(blank=True)
    success    = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f'{self.action} @ {self.created_at:%Y-%m-%d %H:%M}'
