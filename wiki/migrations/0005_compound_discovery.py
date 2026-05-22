from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('wiki', '0004_genretoken_lineage'),
    ]

    operations = [
        migrations.AddField(
            model_name='compoundgenre',
            name='top_tracks_json',
            field=models.JSONField(
                blank=True, default=list,
                help_text='Top tracks from Last.fm: [{name, artist, playcount, lastfm_url}]',
            ),
        ),
        migrations.AddField(
            model_name='compoundgenre',
            name='youtube_video_id',
            field=models.CharField(blank=True, max_length=20),
        ),
        migrations.AddField(
            model_name='compoundgenre',
            name='origin_year',
            field=models.SmallIntegerField(blank=True, null=True),
        ),
    ]
