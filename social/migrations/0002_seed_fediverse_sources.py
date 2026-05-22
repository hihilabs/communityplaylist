from django.db import migrations

SOURCES = [
    # (name, instance_url, protocol, focus, filter_tags, geofence_pdx)
    # Regional instances — public timeline is already local/PDX, no tag filter needed
    ('pdx.sh',           'https://pdx.sh',             'mastodon',  'regional', '',                      False),
    ('pnw.zone',         'https://pnw.zone',           'mastodon',  'regional', '',                      False),
    # Themed instances — public timeline works; geofence filters by content
    ('mastodon.art',     'https://mastodon.art',       'mastodon',  'art',      '',                      True),
    ('pixelfed.social',  'https://pixelfed.social',    'pixelfed',  'art',      '',                      True),
    ('musician.social',  'https://musician.social',    'mastodon',  'music',    '',                      True),
    ('funkwhale.co.uk',  'https://funkwhale.co.uk',    'funkwhale', 'music',    '',                      True),
    ('drumstodon.net',   'https://drumstodon.net',     'mastodon',  'music',    '',                      True),
    ('ravenation.club',  'https://ravenation.club',    'mastodon',  'music',    '',                      True),
    ('zirk.us',          'https://zirk.us',            'mastodon',  'writers',  '',                      True),
    # Large instances — public timeline locked, hashtag fallback drives fetch
    ('mastodon.social',  'https://mastodon.social',    'mastodon',  'general',  'pdx,portland,pnw',      True),
]


def seed(apps, schema_editor):
    FediverseSource = apps.get_model('social', 'FediverseSource')
    for name, url, protocol, focus, tags, geofence in SOURCES:
        FediverseSource.objects.get_or_create(
            instance_url=url,
            defaults=dict(name=name, protocol=protocol, focus=focus,
                          filter_tags=tags, geofence_pdx=geofence, active=True),
        )


def unseed(apps, schema_editor):
    FediverseSource = apps.get_model('social', 'FediverseSource')
    FediverseSource.objects.filter(instance_url__in=[s[1] for s in SOURCES]).delete()


class Migration(migrations.Migration):
    dependencies = [('social', '0001_initial')]
    operations   = [migrations.RunPython(seed, unseed)]
