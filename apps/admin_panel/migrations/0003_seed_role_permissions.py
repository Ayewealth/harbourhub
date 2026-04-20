from django.db import migrations


def seed_matrix(apps, schema_editor):
    RolePermission = apps.get_model("admin_panel", "RolePermission")
    from apps.admin_panel.constants import DEFAULT_ROLE_MATRIX

    for role, modules in DEFAULT_ROLE_MATRIX.items():
        r = role.value if hasattr(role, "value") else role
        for module, flags in modules.items():
            m = module.value if hasattr(module, "value") else module
            cv, cm = flags
            RolePermission.objects.update_or_create(
                role=r,
                module=m,
                defaults={"can_view": cv, "can_manage": cm},
            )


def noop_reverse(apps, schema_editor):
    pass


class Migration(migrations.Migration):

    dependencies = [
        ("admin_panel", "0002_rolepermission_adminprofile"),
    ]

    operations = [
        migrations.RunPython(seed_matrix, noop_reverse),
    ]
