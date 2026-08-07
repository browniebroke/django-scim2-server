import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):
    """
    Partition SCIM resources by configuration and tenant.

    Rows created before this migration are assigned to the configuration named
    "default". If your primary configuration is named something else, either rename it
    in ``SCIM2_SERVER_CONFIGS`` or run
    ``SCIMUser.objects.update(config="<name>")`` (and the same for ``SCIMGroup``)
    after migrating.
    """

    dependencies = [
        ("auth", "0012_alter_user_first_name_max_length"),
        ("django_scim2_server", "0001_initial"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.AddField(
            model_name="scimuser",
            name="config",
            field=models.CharField(db_index=True, default="default", max_length=100),
            preserve_default=False,
        ),
        migrations.AddField(
            model_name="scimgroup",
            name="config",
            field=models.CharField(db_index=True, default="default", max_length=100),
            preserve_default=False,
        ),
        migrations.AddField(
            model_name="scimuser",
            name="scope",
            field=models.CharField(
                blank=True, db_index=True, default="", max_length=255
            ),
        ),
        migrations.AddField(
            model_name="scimgroup",
            name="scope",
            field=models.CharField(
                blank=True, db_index=True, default="", max_length=255
            ),
        ),
        # Uniqueness moves from the whole table to within a (config, scope) pair.
        migrations.AlterField(
            model_name="scimuser",
            name="scim_username",
            field=models.CharField(max_length=255),
        ),
        # One Django user or group may now be provisioned by several configurations
        # or tenants, so the one-to-one relations become foreign keys.
        migrations.AlterField(
            model_name="scimuser",
            name="user",
            field=models.ForeignKey(
                on_delete=django.db.models.deletion.CASCADE,
                related_name="scim_records",
                to=settings.AUTH_USER_MODEL,
            ),
        ),
        migrations.AlterField(
            model_name="scimgroup",
            name="group",
            field=models.ForeignKey(
                on_delete=django.db.models.deletion.CASCADE,
                related_name="scim_records",
                to="auth.group",
            ),
        ),
        migrations.AddConstraint(
            model_name="scimuser",
            constraint=models.UniqueConstraint(
                fields=("config", "scope", "scim_username"),
                name="scim2_unique_username_per_scope",
            ),
        ),
        migrations.AddConstraint(
            model_name="scimuser",
            constraint=models.UniqueConstraint(
                fields=("config", "scope", "user"),
                name="scim2_unique_user_per_scope",
            ),
        ),
        migrations.AddConstraint(
            model_name="scimgroup",
            constraint=models.UniqueConstraint(
                fields=("config", "scope", "group"),
                name="scim2_unique_group_per_scope",
            ),
        ),
    ]
