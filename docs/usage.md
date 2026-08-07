(usage)=

# Usage

After {ref}`installing <installation>` the app, your Django project exposes a SCIM 2.0 API (RFC 7643/7644) that identity providers like Okta, Azure AD, or OneLogin can use to provision and deprovision users and groups.

## Endpoints

The following endpoints are available under the URL prefix you chose (e.g. `/scim/v2/`):

| Endpoint                 | Methods                 | Description                        |
| ------------------------ | ----------------------- | ---------------------------------- |
| `/ServiceProviderConfig` | GET                     | SCIM service provider capabilities |
| `/ResourceTypes`         | GET                     | Available resource types           |
| `/Schemas`               | GET                     | Schema definitions                 |
| `/Users`                 | GET, POST               | List/create users                  |
| `/Users/<id>`            | GET, PUT, PATCH, DELETE | Retrieve/update/deactivate a user  |
| `/Groups`                | GET, POST               | List/create groups                 |
| `/Groups/<id>`           | GET, PUT, PATCH, DELETE | Retrieve/update/delete a group     |

## How it works

The app creates two models, `SCIMUser` and `SCIMGroup`, each linked via a `ForeignKey` to Django's built-in `auth.User` and `auth.Group` models respectively. These hold SCIM-specific metadata (UUID, `externalId`, timestamps) while leaving your existing user and group data untouched.

When a SCIM client sends a `POST /Users` request, the app creates both a Django user **and** a `SCIMUser` record. On `DELETE /Users/<id>`, the user is **deactivated** (not deleted) by setting `is_active=False`, which is the behavior most identity providers expect.

## Configurations

Everything is configured per **configuration**: a named profile declared in
`SCIM2_SERVER_CONFIGS` and mounted at its own URL prefix. A project needs at least one:

```python
# settings.py
SCIM2_SERVER_CONFIGS = {
    "default": {},
}
```

```python
# urls.py
from django.urls import include, path

from django_scim2_server.urls import scim2_urls

urlpatterns = [
    path("scim/v2/", include(scim2_urls("default"))),
]
```

The configuration name is the URL namespace, so resources are reversed as
`default:users-list`, `default:users-detail`, and so on.

Several configurations can be declared and mounted alongside each other — see
{doc}`multi-config`.

(configuration-keys)=

### Configuration keys

| Key                       | Default                                            | Description                                       |
| ------------------------- | -------------------------------------------------- | ------------------------------------------------- |
| `USER_ADAPTER`            | `django_scim2_server.adapters.DefaultUserAdapter`  | Dotted path to the user adapter class             |
| `GROUP_ADAPTER`           | `django_scim2_server.adapters.DefaultGroupAdapter` | Dotted path to the group adapter class            |
| `AUTH_CHECK`              | `django_scim2_server.auth.is_superuser`            | Dotted path to the access-control callable         |
| `SCOPE_URL_KWARG`         | `None`                                             | URL keyword argument carrying the tenant key      |
| `SERVICE_PROVIDER_CONFIG` | the built-in document                              | Dotted path to a `ServiceProviderConfig` instance |

Unknown keys, dotted paths that cannot be imported, and adapters that do not derive from
the base classes all raise `ImproperlyConfigured`. The app registers system checks for
this, so `manage.py check` reports the problem before any request is served.

## Access control

By default, only **superusers** can access the SCIM endpoints. Point `AUTH_CHECK` at a
different callable to change that:

```python
# settings.py
SCIM2_SERVER_CONFIGS = {
    "default": {
        # Allow any authenticated user (less restrictive):
        "AUTH_CHECK": "django_scim2_server.auth.is_authenticated",
    },
}
```

You can also write your own check. It must be a callable that takes an `HttpRequest` and returns a `bool`:

```python
# myapp/scim_auth.py
def check_scim_token(request):
    """Only allow requests with a valid Bearer token."""
    expected = "my-secret-scim-token"
    auth_header = request.META.get("HTTP_AUTHORIZATION", "")
    return auth_header == f"Bearer {expected}"
```

```python
# settings.py
SCIM2_SERVER_CONFIGS = {
    "default": {"AUTH_CHECK": "myapp.scim_auth.check_scim_token"},
}
```

The check runs after the configuration has been resolved, so it can read which
configuration and tenant the request is addressed to — see {doc}`multi-config`.

## Filtering and pagination

The `GET /Users` and `GET /Groups` endpoints support SCIM filtering and pagination:

```
GET /scim/v2/Users?filter=userName eq "john"&startIndex=1&count=10
```

Supported filter operators: `eq`, `ne`, `co`, `sw`, `ew`, `gt`, `ge`, `lt`, `le`, `pr`, combined with `and`, `or`, `not`, and parentheses.

## Custom adapters

Adapters control how SCIM JSON maps to and from your Django models. The defaults work with `django.contrib.auth.User` and `Group`, but you can subclass them to support custom user models or additional attributes.

An adapter is instantiated per request with a `SCIMContext`, available as `self.context`.
It tells the adapter which configuration is serving the request (`self.config_name`) and
which tenant (`self.scope`).

### Example: mapping a custom user model

```python
# myapp/adapters.py
from django_scim2_server.adapters import DefaultUserAdapter


class MyUserAdapter(DefaultUserAdapter):
    filter_map = {
        **DefaultUserAdapter.filter_map,
        "title": "user__profile__title",
    }

    def to_scim(self, scim_obj, request):
        data = super().to_scim(scim_obj, request)
        data["title"] = getattr(scim_obj.user, "title", "")
        return data

    def from_scim(self, data, scim_obj=None):
        scim_obj = super().from_scim(data, scim_obj)
        if "title" in data:
            scim_obj.user.title = data["title"]
            scim_obj.user.save(update_fields=["title"])
        return scim_obj
```

Then point the configuration at your adapter:

```python
# settings.py
SCIM2_SERVER_CONFIGS = {
    "default": {"USER_ADAPTER": "myapp.adapters.MyUserAdapter"},
}
```

### Extending PATCH support

`PATCH` operations are dispatched to the adapter one at a time, so an adapter can
support extra SCIM paths by overriding `apply_patch_operation`:

```python
# myapp/patch_adapters.py
from django_scim2_server.adapters import DefaultUserAdapter


class TitleAwareUserAdapter(DefaultUserAdapter):
    def apply_patch_operation(self, scim_obj, op, path, value):
        if path == "title" and op in ("add", "replace"):
            scim_obj.user.title = value
            return
        super().apply_patch_operation(scim_obj, op, path, value)
```

Changes are persisted once at the end of the operation run, by `save_patched`.

## Settings reference

There is a single setting, `SCIM2_SERVER_CONFIGS`, described by the
{ref}`configuration keys <configuration-keys>` table above. See {doc}`configuration` for
the resolved configuration object.
