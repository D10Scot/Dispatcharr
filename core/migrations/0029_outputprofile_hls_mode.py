"""Mark HLS Output Profiles and seed the two locked ones (Phase 4a-1d, spec D12).

The reverse deletes only the rows whose ``hls_mode`` is non-blank. It does not
rename back an admin's row that the forward migration moved aside to make room
for a seeded name: that row keeps its "(custom)" name.
"""

from django.db import migrations, models

SEEDED = (
    ("HLS (Re-encode)", "transcode"),
    ("HLS (Automatic)", "automatic"),
)


def seed_hls_output_profiles(apps, schema_editor):
    OutputProfile = apps.get_model("core", "OutputProfile")
    for name, mode in SEEDED:
        # ``name`` is unique: an admin's row that already has the name moves aside.
        for row in OutputProfile.objects.filter(name=name):
            row.name = f"{name} (custom)"
            row.save(update_fields=["name"])
        OutputProfile.objects.create(
            name=name,
            command="ffmpeg",
            parameters="(built by the relay)",
            locked=True,
            is_active=True,
            hls_mode=mode,
        )


def remove_hls_output_profiles(apps, schema_editor):
    OutputProfile = apps.get_model("core", "OutputProfile")
    OutputProfile.objects.filter(hls_mode__in=["transcode", "automatic"]).delete()


class Migration(migrations.Migration):

    dependencies = [
        ("core", "0028_alter_streamprofile_parameters"),
    ]

    operations = [
        migrations.AddField(
            model_name="outputprofile",
            name="hls_mode",
            field=models.CharField(
                blank=True,
                choices=[
                    ("", "Not HLS"),
                    ("transcode", "HLS re-encode"),
                    ("automatic", "HLS automatic"),
                ],
                default="",
                help_text="Non-blank marks an HLS profile, built by the relay rather than from parameters",
                max_length=16,
            ),
        ),
        migrations.RunPython(seed_hls_output_profiles, remove_hls_output_profiles),
    ]
