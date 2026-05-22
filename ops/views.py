"""
ops/views.py — Staff-only ops dashboard.

Drop-in for any Django project. Wire with:
    path('ops/', include('ops.urls')),
Protect at the URL level via staff_member_required (already applied here).
"""
import os
import sys
import signal
import subprocess
import re
from datetime import timedelta

import django
from django.conf import settings
from django.contrib.admin.views.decorators import staff_member_required
from django.http import JsonResponse
from django.shortcuts import render, redirect, get_object_or_404
from django.utils import timezone
from django.views.decorators.http import require_POST
from django.contrib import messages

from .models import Ticket, OpsEvent

# ── Config ────────────────────────────────────────────────────────────────────

PROJECT_ROOT = getattr(settings, 'BASE_DIR', os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
PROJECT_NAME = getattr(settings, 'OPS_PROJECT_NAME', settings.ROOT_URLCONF.split('.')[0])

# Commands are whitelisted — never pass raw user input to the shell
_MANAGE = str(PROJECT_ROOT / 'manage.py') if hasattr(PROJECT_ROOT, '__truediv__') else os.path.join(str(PROJECT_ROOT), 'manage.py')

_COMMANDS = {
    'git_status':      ['git', '-C', str(PROJECT_ROOT), 'status', '--short'],
    'git_log':         ['git', '-C', str(PROJECT_ROOT), 'log', '--oneline', '-15', '--decorate'],
    'git_pull':        ['git', '-C', str(PROJECT_ROOT), 'pull'],
    'git_diff':        ['git', '-C', str(PROJECT_ROOT), 'diff', '--stat', 'HEAD~1'],
    'collectstatic':   [sys.executable, _MANAGE, 'collectstatic', '--noinput', '--clear'],
    'sync_genre_wiki':    [sys.executable, _MANAGE, 'sync_genre_wiki',    '--api-url', 'http://10.0.0.124:3001'],
    'refresh_genre_wiki': [sys.executable, _MANAGE, 'refresh_genre_wiki', '--api-url', 'http://10.0.0.124:3001'],
}


def _run(cmd_key, user=None):
    """Run a whitelisted command, log it, return (success, output)."""
    cmd = _COMMANDS.get(cmd_key)
    if not cmd:
        return False, 'Unknown command'
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=120, cwd=str(PROJECT_ROOT))
        output = (result.stdout + result.stderr).strip()
        success = result.returncode == 0
    except subprocess.TimeoutExpired:
        output = 'Command timed out after 120s'
        success = False
    except Exception as e:
        output = str(e)
        success = False

    OpsEvent.objects.create(action=cmd_key, triggered_by=user, output=output, success=success)
    return success, output


def _reload_gunicorn(user=None):
    """Send HUP to gunicorn master. Tries pidfile first, then /proc scan."""
    pid = None
    pidfile = getattr(settings, 'GUNICORN_PID_FILE', '/tmp/gunicorn.pid')
    try:
        with open(pidfile) as f:
            pid = int(f.read().strip())
    except (OSError, ValueError):
        pass

    if not pid:
        try:
            for entry in os.scandir('/proc'):
                if not entry.name.isdigit():
                    continue
                try:
                    with open(f'/proc/{entry.name}/cmdline') as f:
                        cmdline = f.read()
                    if 'gunicorn' in cmdline and PROJECT_NAME.replace('-', '_') in cmdline:
                        pid = int(entry.name)
                        break
                except (OSError, ValueError):
                    continue
        except OSError:
            pass

    if pid:
        try:
            os.kill(pid, signal.SIGHUP)
            output = f'Sent HUP to gunicorn master PID {pid}'
            success = True
        except ProcessLookupError:
            output = f'PID {pid} not found — may already be gone'
            success = False
        except PermissionError:
            output = f'No permission to signal PID {pid}'
            success = False
    else:
        output = 'Could not locate gunicorn master PID'
        success = False

    OpsEvent.objects.create(action='reload', triggered_by=user, output=output, success=success)
    return success, output


# ── Stats helpers ─────────────────────────────────────────────────────────────

def _site_stats():
    stats = {}
    # Try to import project models — gracefully skip if not present
    try:
        from events.models import Event, Artist
        now = timezone.now()
        stats['events_total']  = Event.objects.count()
        stats['events_week']   = Event.objects.filter(created_at__gte=now - timedelta(days=7)).count()
        stats['events_month']  = Event.objects.filter(created_at__gte=now - timedelta(days=30)).count()
        stats['artists_total'] = Artist.objects.count()
        stats['top_events']    = list(
            Event.objects.filter(view_count__gt=0).order_by('-view_count').values('title', 'slug', 'view_count')[:8]
        )
    except Exception:
        pass

    # Django admin log
    try:
        from django.contrib.admin.models import LogEntry
        stats['recent_admin'] = list(
            LogEntry.objects.select_related('user', 'content_type')
            .values('user__username', 'action_flag', 'object_repr', 'action_time', 'content_type__model')
            .order_by('-action_time')[:10]
        )
    except Exception:
        pass

    return stats


def _git_info():
    info = {}
    try:
        info['branch'] = subprocess.check_output(
            ['git', '-C', str(PROJECT_ROOT), 'rev-parse', '--abbrev-ref', 'HEAD'],
            stderr=subprocess.DEVNULL, text=True, timeout=5
        ).strip()
        info['commit'] = subprocess.check_output(
            ['git', '-C', str(PROJECT_ROOT), 'log', '-1', '--format=%h %s (%ar)', '--decorate'],
            stderr=subprocess.DEVNULL, text=True, timeout=5
        ).strip()
        info['log'] = subprocess.check_output(
            ['git', '-C', str(PROJECT_ROOT), 'log', '--oneline', '-10', '--decorate'],
            stderr=subprocess.DEVNULL, text=True, timeout=5
        ).strip()
        status_out = subprocess.check_output(
            ['git', '-C', str(PROJECT_ROOT), 'status', '--short'],
            stderr=subprocess.DEVNULL, text=True, timeout=5
        ).strip()
        info['dirty'] = bool(status_out)
        info['status'] = status_out or 'Clean working tree'
    except Exception as e:
        info['error'] = str(e)
    return info


def _server_info():
    info = {
        'python':  sys.version.split()[0],
        'django':  django.__version__,
        'debug':   settings.DEBUG,
        'project': PROJECT_NAME,
        'root':    str(PROJECT_ROOT),
    }
    try:
        import platform
        info['os'] = platform.platform()
    except Exception:
        pass
    return info


# ── Views ─────────────────────────────────────────────────────────────────────

@staff_member_required
def panel(request):
    ctx = {
        'project_name': PROJECT_NAME,
        'git':    _git_info(),
        'server': _server_info(),
        'stats':  _site_stats(),
        'tickets_open': Ticket.objects.filter(status__in=['open', 'in_progress']).order_by('-priority', '-created_at')[:20],
        'ops_log': OpsEvent.objects.all()[:20],
        'ticket_types':     Ticket.TYPE_CHOICES,
        'ticket_priorities': Ticket.PRIORITY_CHOICES,
    }
    return render(request, 'ops/panel.html', ctx)


@staff_member_required
@require_POST
def run_cmd(request):
    cmd = request.POST.get('cmd', '')
    if cmd == 'reload':
        success, output = _reload_gunicorn(user=request.user)
    elif cmd in _COMMANDS:
        success, output = _run(cmd, user=request.user)
    else:
        return JsonResponse({'success': False, 'output': 'Unknown command'}, status=400)

    if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
        return JsonResponse({'success': success, 'output': output})

    if success:
        messages.success(request, output)
    else:
        messages.error(request, output)
    return redirect('ops:panel')


@staff_member_required
@require_POST
def create_ticket(request):
    t = Ticket.objects.create(
        title=request.POST.get('title', 'Untitled')[:200],
        description=request.POST.get('description', ''),
        ticket_type=request.POST.get('ticket_type', 'task'),
        priority=request.POST.get('priority', 'medium'),
        project=request.POST.get('project', PROJECT_NAME),
        created_by=request.user,
    )
    OpsEvent.objects.create(action='ticket_create', triggered_by=request.user,
                            output=f'Created ticket #{t.pk}: {t.title}')
    if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
        return JsonResponse({'id': t.pk, 'title': t.title, 'status': t.status})
    messages.success(request, f'Ticket #{t.pk} created.')
    return redirect('ops:panel')


@staff_member_required
@require_POST
def update_ticket(request, pk):
    t = get_object_or_404(Ticket, pk=pk)
    new_status = request.POST.get('status')
    if new_status in dict(Ticket.STATUS_CHOICES):
        t.status = new_status
        if new_status == 'done':
            t.resolved_at = timezone.now()
        t.save(update_fields=['status', 'resolved_at', 'updated_at'])
    if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
        return JsonResponse({'ok': True, 'status': t.status})
    return redirect('ops:panel')
