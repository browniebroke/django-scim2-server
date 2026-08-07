(upgrading)=

# Upgrading from 1.x

Version 2.0 replaces the single process-wide configuration with named
{doc}`configurations <multi-config>`. A 1.x project maps onto one configuration, so the
migration is mechanical.

## 1. Move the settings into a configuration

The flat `SCIM2_SERVER_*` settings are gone. Wrap what you had in a configuration named
`default`:

```python
# before, 1.x
SCIM2_SERVER_USER_ADAPTER = "myapp.adapters.MyUserAdapter"
SCIM2_SERVER_GROUP_ADAPTER = "myapp.adapters.MyGroupAdapter"
SCIM2_SERVER_AUTH_CHECK = "myapp.scim_auth.check_scim_token"
```

```python
# after, 2.0
SCIM2_SERVER_CONFIGS = {
    "default": {
        "USER_ADAPTER": "myapp.adapters.MyUserAdapter",
        "GROUP_ADAPTER": "myapp.adapters.MyGroupAdapter",
        "AUTH_CHECK": "myapp.scim_auth.check_scim_token",
    },
}
```

`SCIM2_SERVER_USER_MODEL` and `SCIM2_SERVER_GROUP_MODEL` have been removed. They were
documented but never read by any code path, so nothing changes by dropping them.

The name `default` matters only in that the migration assigns pre-existing rows to it
(see step 5) — pick another name and adjust accordingly.

## 2. Switch the URLconf to the factory

<!--- skip: next --->

```python
# before, 1.x
urlpatterns = [
    path("scim/v2/", include("django_scim2_server.urls")),
]
```

```python
# after, 2.0
from django.urls import include, path

from django_scim2_server.urls import scim2_urls

urlpatterns = [
    path("scim/v2/", include(scim2_urls("default"))),
]
```

The module no longer exposes `urlpatterns` or `app_name`, so it can be mounted more than
once. Reverse names change from the fixed `scim2:` namespace to the configuration name:
`scim2:users-detail` becomes `default:users-detail`.

## 3. Update custom adapters

Adapters are now instantiated with a per-request context, and are the single place where
`PATCH` behaviour lives.

- **`__init__`** — if you override it, accept the context and pass it up:

  <!--- skip: next --->

  ```python
  def __init__(self, context):
      super().__init__(context)
      ...
  ```

  The context is available afterwards as `self.context`, with `self.config_name` and
  `self.scope` shortcuts.

- **`get_queryset`** — the base implementation now filters on the configuration and
  tenant. If you override it, call `super().get_queryset()` rather than starting from
  `SCIMUser.objects`, so the filtering is not lost.

- **Location URLs** — `_build_location()` is gone. `meta.location` is built by
  `self.build_location(request, scim_id)`, which reverses the mount's URL instead of
  assuming a `/scim/v2/` prefix. If you were relying on the old hardcoded prefix, your
  locations are now correct for wherever you actually mounted the app.

- **`PATCH`** — the module-level helpers in `django_scim2_server.patch` have been
  replaced by `apply_patch_operation(scim_obj, op, path, value)` and `save_patched()` on
  the adapters. `patch.apply_patch_operations` remains, and now just loops over the
  operations and delegates to the adapter.

## 4. Update reverse accessors

`SCIMUser.user` and `SCIMGroup.group` are now `ForeignKey` rather than `OneToOneField`,
so one Django user or group can be provisioned by several configurations or tenants. The
reverse accessors change accordingly:

<!--- skip: next --->

```python
# before, 1.x
user.scim.scim_username

# after, 2.0
user.scim_records.get(config="default").scim_username
```

Uniqueness has not been lost, it has moved: a Django user can appear at most once within
a given `(config, scope)` pair, enforced by a database constraint.

## 5. Run the migration

```bash
python manage.py migrate django_scim2_server
```

`0002_multi_config` adds the `config` and `scope` columns and assigns every existing row
to the configuration named `default`. If your configuration is called something else,
either rename it or reassign the rows afterwards:

<!--- skip: next --->

```python
SCIMUser.objects.filter(config="default").update(config="staff")
SCIMGroup.objects.filter(config="default").update(config="staff")
```

The same migration replaces the global unique constraint on `SCIMUser.scim_username`
with one scoped to `(config, scope, scim_username)`. Nothing that was valid before
becomes invalid.

## Summary of breaking changes

1. `SCIM2_SERVER_USER_ADAPTER`, `SCIM2_SERVER_GROUP_ADAPTER` and
   `SCIM2_SERVER_AUTH_CHECK` are replaced by entries in `SCIM2_SERVER_CONFIGS`.
2. `SCIM2_SERVER_USER_MODEL` and `SCIM2_SERVER_GROUP_MODEL` are removed.
3. `include("django_scim2_server.urls")` is replaced by `include(scim2_urls(name))`; the
   module no longer exposes `urlpatterns` or `app_name`.
4. Reverse names move from the `scim2` namespace to the configuration name.
5. Adapters are constructed with a `SCIMContext`.
6. `user.scim` and `group.scim` become `user.scim_records` and `group.scim_records`.
7. `SCIMUser.scim_username` is unique per `(config, scope)`, not globally.
8. `PATCH` handling moved from module-level functions in `django_scim2_server.patch` onto
   the adapters.
