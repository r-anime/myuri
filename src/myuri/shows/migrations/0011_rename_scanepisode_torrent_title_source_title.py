from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ("shows", "0010_showlink_url_charfield"),
    ]

    operations = [
        migrations.RenameField(
            model_name="scanepisode",
            old_name="torrent_title",
            new_name="source_title",
        ),
    ]
