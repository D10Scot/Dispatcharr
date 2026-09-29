"""Add Channel.hls_output_profile (Phase 4a-1d, spec D12)."""

import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("dispatcharr_channels", "0038_add_catchup_fields"),
        ("core", "0029_outputprofile_hls_mode"),
    ]

    operations = [
        migrations.AddField(
            model_name="channel",
            name="hls_output_profile",
            field=models.ForeignKey(
                blank=True,
                help_text="HLS Output Profile for this channel (null: the built-in re-encode).",
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="hls_channels",
                to="core.outputprofile",
            ),
        ),
    ]
