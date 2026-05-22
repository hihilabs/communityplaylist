from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('wiki', '0002_compoundgenre_track_count_genretoken_track_count'),
    ]

    operations = [
        migrations.AddField(
            model_name='genretoken',
            name='top_tracks_json',
            field=models.JSONField(
                blank=True,
                default=list,
                help_text='Top tracks from Last.fm: [{name, artist, playcount, lastfm_url}]',
            ),
        ),
        migrations.AddField(
            model_name='genretoken',
            name='youtube_video_id',
            field=models.CharField(
                blank=True,
                max_length=20,
                help_text='YouTube video ID for genre overview/mix (populated by enrichment)',
            ),
        ),
    ]
