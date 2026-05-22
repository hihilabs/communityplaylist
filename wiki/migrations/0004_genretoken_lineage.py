from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('wiki', '0003_genretoken_top_tracks_youtube'),
    ]

    operations = [
        migrations.AddField(
            model_name='genretoken',
            name='origin_year',
            field=models.SmallIntegerField(
                blank=True, null=True,
                help_text='Year the genre emerged (filled by Wikipedia enrichment)',
            ),
        ),
        migrations.AddField(
            model_name='genretoken',
            name='derived_from',
            field=models.ForeignKey(
                blank=True, null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name='derivatives',
                to='wiki.genretoken',
                help_text='Parent genre this one split from (for chronological tree)',
            ),
        ),
    ]
