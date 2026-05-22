from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('events', '0100_videotrack_yt_embeddable'),
    ]

    operations = [
        # rss_feed on Artist
        migrations.AddField(
            model_name='artist',
            name='rss_feed',
            field=models.URLField(blank=True, help_text='External RSS feed URL (blog, Substack, etc.) — items pulled and shown on profile'),
        ),
        # rss_feed on Venue
        migrations.AddField(
            model_name='venue',
            name='rss_feed',
            field=models.URLField(blank=True, help_text='External RSS feed URL — items pulled and shown on profile'),
        ),
        # rss_feed on CommunitySpace
        migrations.AddField(
            model_name='communityspace',
            name='rss_feed',
            field=models.URLField(blank=True, help_text='External RSS feed URL (blog, Substack, etc.) — new items auto-posted to CP Bluesky tagging this space'),
        ),
        # ExternalFeedItem table
        migrations.CreateModel(
            name='ExternalFeedItem',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('title', models.CharField(max_length=500)),
                ('link', models.URLField(max_length=1000)),
                ('description', models.TextField(blank=True)),
                ('published', models.DateTimeField(blank=True, null=True)),
                ('guid', models.CharField(max_length=1000)),
                ('bsky_posted', models.BooleanField(default=False)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('community_space', models.ForeignKey(
                    blank=True, null=True, on_delete=django.db.models.deletion.CASCADE,
                    related_name='feed_items', to='events.communityspace',
                )),
                ('artist', models.ForeignKey(
                    blank=True, null=True, on_delete=django.db.models.deletion.CASCADE,
                    related_name='feed_items', to='events.artist',
                )),
                ('venue', models.ForeignKey(
                    blank=True, null=True, on_delete=django.db.models.deletion.CASCADE,
                    related_name='feed_items', to='events.venue',
                )),
            ],
            options={'ordering': ['-published', '-created_at']},
        ),
    ]
