from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    initial = True

    dependencies = []

    operations = [
        migrations.CreateModel(
            name='FediverseSource',
            fields=[
                ('id',           models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('name',         models.CharField(max_length=100)),
                ('instance_url', models.URLField(help_text='e.g. https://pdx.sh')),
                ('protocol',     models.CharField(
                    choices=[('mastodon', 'Mastodon / ActivityPub'), ('pixelfed', 'Pixelfed'), ('funkwhale', 'Funkwhale')],
                    default='mastodon', max_length=20,
                )),
                ('focus', models.CharField(
                    choices=[('regional', 'Regional (PDX / PNW)'), ('music', 'Music & Audio'),
                             ('art', 'Visual Art & Design'), ('writers', 'Writers & Creatives'), ('general', 'General')],
                    default='general', max_length=20,
                )),
                ('filter_tags',  models.TextField(blank=True, help_text='Comma-separated tags to filter for (e.g. "pdx,portland,pnw"). Empty = accept all.')),
                ('geofence_pdx', models.BooleanField(default=True)),
                ('access_token', models.CharField(blank=True, help_text='OAuth token for non-public instances', max_length=300)),
                ('active',       models.BooleanField(default=True)),
                ('last_synced',  models.DateTimeField(blank=True, null=True)),
                ('notes',        models.TextField(blank=True)),
            ],
            options={'ordering': ['focus', 'name'], 'verbose_name': 'Fediverse Source'},
        ),
        migrations.CreateModel(
            name='SocialPost',
            fields=[
                ('id',           models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('platform',     models.CharField(
                    choices=[('bluesky', 'Bluesky'), ('mastodon', 'Mastodon')], max_length=20,
                )),
                ('post_type',    models.CharField(
                    choices=[('record', 'Record for Sale'), ('profile', 'Artist / Crew Profile'), ('zine', 'Zine / Board Post')],
                    max_length=20,
                )),
                ('object_model', models.CharField(max_length=50)),
                ('object_id',    models.PositiveIntegerField()),
                ('text',         models.TextField(blank=True)),
                ('post_id',      models.CharField(blank=True, max_length=300)),
                ('post_url',     models.URLField(blank=True)),
                ('success',      models.BooleanField(default=True)),
                ('error',        models.TextField(blank=True)),
                ('posted_at',    models.DateTimeField(auto_now_add=True)),
            ],
            options={'ordering': ['-posted_at']},
        ),
        migrations.CreateModel(
            name='FediversePost',
            fields=[
                ('id',               models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('source',           models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='posts', to='social.fediversesource')),
                ('remote_id',        models.CharField(max_length=300)),
                ('account_url',      models.URLField(blank=True)),
                ('account_username', models.CharField(max_length=150)),
                ('content_html',     models.TextField()),
                ('content_text',     models.TextField(blank=True)),
                ('url',              models.URLField()),
                ('tags',             models.JSONField(default=list)),
                ('media_urls',       models.JSONField(default=list)),
                ('published_at',     models.DateTimeField()),
                ('fetched_at',       models.DateTimeField(auto_now_add=True)),
                ('is_pdx_relevant',  models.BooleanField(db_index=True, default=False)),
            ],
            options={'ordering': ['-published_at']},
        ),
        migrations.AddConstraint(
            model_name='fediversepost',
            constraint=models.UniqueConstraint(fields=['source', 'remote_id'], name='unique_source_remote_id'),
        ),
    ]
