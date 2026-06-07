from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('wiki', '0005_compound_discovery'),
    ]

    operations = [
        migrations.CreateModel(
            name='LibraryReport',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('install_id', models.CharField(help_text='Random per-install UUID — no personal data', max_length=64, unique=True)),
                ('tokens_json', models.JSONField(blank=True, default=list, help_text='[{name, count}] — genre token frequency in the reporting library')),
                ('cooccurrence_json', models.JSONField(blank=True, default=list, help_text='[{a, b, count}] — token co-occurrence pairs (which genres share files)')),
                ('reported_at', models.DateTimeField(auto_now=True)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
            ],
            options={
                'verbose_name': 'Library Report',
                'ordering': ['-reported_at'],
            },
        ),
    ]
