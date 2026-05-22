from django.views.debug import SafeExceptionReporterFilter
from django.conf import settings


class MaskedExceptionReporterFilter(SafeExceptionReporterFilter):
    """Extends Django's default filter to also mask webhook and internal URLs."""

    def get_safe_settings(self):
        safe = super().get_safe_settings()
        for name in getattr(settings, 'SENSITIVE_SETTINGS_EXTRA', []):
            if name in safe:
                safe[name] = self.cleansed_substitute
        return safe
