from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('shows', '0011_rename_scanepisode_torrent_title_source_title'),
    ]

    operations = [
        migrations.AddField(
            model_name='show',
            name='disable_nyaa_trusted',
            field=models.BooleanField(default=False, help_text='Allow non-trusted uploaders when scanning Nyaa for this show (for shows only released by smaller/bespoke fansubs)'),
        ),
    ]
