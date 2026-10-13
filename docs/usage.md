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

The app creates two models, `SCIMUser` and `SCIMGroup`, each linked via a `OneToOneField` to Django's built-in `auth.User` and `auth.Group` models respectively. These hold SCIM-specific metadata (UUID, `externalId`, timestamps) while leaving your existing user and group data untouched.

When a SCIM client sends a `POST /Users` request, the app creates both a Django user **and** a `SCIMUser` record. On `DELETE /Users/<id>`, the user is **deactivated** (not deleted) by setting `is_active=False`, which is the behavior most identity providers expect.

## Access control

By default, only **superusers** can access the SCIM endpoints. You can change this by pointing `SCIM2_SERVER_AUTH_CHECK` to a different callable:

```python
# settings.py

# Allow any authenticated user (less restrictive):
SCIM2_SERVER_AUTH_CHECK = "django_scim2_server.auth.is_authenticated"
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
SCIM2_SERVER_AUTH_CHECK = "myapp.scim_auth.check_scim_token"
```

## Filtering and pagination

The `GET /Users` and `GET /Groups` endpoints support SCIM filtering and pagination:

```
GET /scim/v2/Users?filter=userName eq "john"&startIndex=1&count=10
```

Supported filter operators: `eq`, `ne`, `co`, `sw`, `ew`, `gt`, `ge`, `lt`, `le`, `pr`, combined with `and`, `or`, `not`, and parentheses.

## Custom adapters

Adapters control how SCIM JSON maps to and from your Django models. The defaults work with `django.contrib.auth.User` and `Group`, but you can subclass them to support custom user models or additional attributes.

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

Then point the setting to your adapter:

```python
# settings.py
SCIM2_SERVER_USER_ADAPTER = "myapp.adapters.MyUserAdapter"
```

### PATCH support

Adapters inherit a generic `patch()` from `BaseUserAdapter` / `BaseGroupAdapter`: the resource is rendered with `to_scim()`, the operations are applied to that JSON document, and the result is passed back to `from_scim()` as a full replacement. A custom adapter therefore only implements the mapping once, in `to_scim()` and `from_scim()`.

The PATCH engine accepts the variations sent by Microsoft Entra ID and Okta: capitalised operations (`"Replace"`), booleans sent as strings (`"False"`), dotted or URN-prefixed keys in a path-less `value`, value filters such as `emails[type eq "work"].value`, and removing group members with a `value` list.

### Enterprise User extension

Adapters declare the schemas they support through `resource_type` and `schemas`; the discovery endpoints are built from them. To map the Enterprise User extension (`department`, `employeeNumber`, `manager`...), use the provided constants and read or write `resource[EnterpriseUser]`:

```python
from typing import ClassVar

from scim2_models import Schema

from django_scim2_server.adapters import BaseUserAdapter
from django_scim2_server.constants import (
    RESOURCE_TYPE_USER_WITH_ENTERPRISE,
    SCHEMA_ENTERPRISE_USER,
    SCHEMA_USER,
)


class EmployeeAdapter(BaseUserAdapter):
    resource_type = RESOURCE_TYPE_USER_WITH_ENTERPRISE
    schemas: ClassVar[list[Schema]] = [SCHEMA_USER, SCHEMA_ENTERPRISE_USER]
```

### Scoping and object lookup

An adapter is instantiated for each request and keeps it as `self.request`, so `get_queryset()` can restrict what a SCIM client sees, e.g. to the tenant its token belongs to. The SCIM `id` is looked up on `lookup_field` (`"id"` by default); set it to another unique field, such as a public UUID, if your primary key should not be exposed.

## Serving several SCIM endpoints

Use `get_urlpatterns()` to mount the SCIM views more than once, each mount with its own adapters and access control. Arguments left out fall back to the settings. Give each mount its own namespace: resource locations are built from it.

```python
from django.urls import include, path

from django_scim2_server.urls import get_urlpatterns


def tenant_token_auth(request):
    """Resolve the bearer token to a tenant and remember it for the adapters."""
    ...


urlpatterns = [
    # Uses the SCIM2_SERVER_* settings
    path("scim/v2/", include("django_scim2_server.urls")),
    path(
        "scim/v2/tenants/",
        include(
            (
                get_urlpatterns(
                    user_adapter="myapp.adapters.TenantUserAdapter",
                    group_adapter="myapp.adapters.TenantGroupAdapter",
                    auth_check=tenant_token_auth,
                ),
                "scim2",
            ),
            namespace="scim2-tenants",
        ),
    ),
]
```

`django_scim2_server.auth.get_bearer_token(request)` returns the token from an `Authorization: Bearer ...` header, or `None`, to help write such checks.

## Settings reference

All settings are prefixed with `SCIM2_SERVER_` and can be set in your Django settings module:

| Setting                      | Default                                            | Description                                |
| ---------------------------- | -------------------------------------------------- | ------------------------------------------ |
| `SCIM2_SERVER_USER_ADAPTER`  | `django_scim2_server.adapters.DefaultUserAdapter`  | Dotted path to the user adapter class      |
| `SCIM2_SERVER_GROUP_ADAPTER` | `django_scim2_server.adapters.DefaultGroupAdapter` | Dotted path to the group adapter class     |
| `SCIM2_SERVER_AUTH_CHECK`    | `django_scim2_server.auth.is_superuser`            | Dotted path to auth check callable         |
| `SCIM2_SERVER_USER_MODEL`    | `auth.User`                                        | Target user model (`app_label.ModelName`)  |
| `SCIM2_SERVER_GROUP_MODEL`   | `auth.Group`                                       | Target group model (`app_label.ModelName`) |

See {doc}`configuration` for details on how settings overrides work.
