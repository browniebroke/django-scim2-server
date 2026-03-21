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
