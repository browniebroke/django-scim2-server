(multi-config)=

# Multiple configurations

A SaaS platform usually needs more than one SCIM surface. A typical setup has two:

- one for the platform's **own staff**, where the internal IT team connects the company
  identity provider;
- one **per customer tenant**, where each customer connects their own identity provider
  to provision users inside their own tenant.

Both can run side by side. Declare them as two configurations and mount each under its
own URL prefix.

## Two concepts

**A configuration** is a deployment profile: which adapters to use, which access-control
callable to run. It is declared in `SCIM2_SERVER_CONFIGS` and mounted in your URLconf.

**A scope** is a tenant key, read from the URL on every request. A configuration that
declares `SCOPE_URL_KWARG` is *scoped*: it serves many tenants from one profile, keeping
their data apart. A configuration without it serves a single, unscoped set of resources.

So `"staff"` below is one configuration with one implicit scope, and `"tenants"` is one
configuration with as many scopes as you have customers.

## Setting it up

```python
# settings.py
SCIM2_SERVER_CONFIGS = {
    "staff": {
        # Internal IT connects Okta here. Superusers only, the default.
    },
    "tenants": {
        "AUTH_CHECK": "myproject.scim.tenant_token_check",
        "SCOPE_URL_KWARG": "tenant",
    },
}
```

```python
# urls.py
from django.urls import include, path

from django_scim2_server.urls import scim2_urls

urlpatterns = [
    path("scim/v2/", include(scim2_urls("staff"))),
    path("t/<slug:tenant>/scim/v2/", include(scim2_urls("tenants"))),
]
```

The URL pattern for a scoped configuration **must** capture the keyword named by
`SCOPE_URL_KWARG` — `tenant` here. If it does not, the first request raises
`ImproperlyConfigured` rather than silently serving the wrong data.

Each tenant now has its own base URL to paste into its identity provider:

```
https://example.com/t/acme/scim/v2/
https://example.com/t/globex/scim/v2/
```

Because the configuration name is the URL namespace, reverse names are per mount:

```
reverse("staff:users-detail", kwargs={"scim_id": scim_id})
reverse("tenants:users-detail", kwargs={"tenant": "acme", "scim_id": scim_id})
```

`meta.location` in every SCIM response is built the same way, so each identity provider
sees URLs on its own mount.

(per-tenant-credentials)=

## Per-tenant credentials

Each tenant needs its own token. The access-control callable receives the request, and
the resolved configuration and scope are attached to it, so one callable can serve every
tenant:

```python
# myproject/scim.py
import hmac

from django_scim2_server.context import get_context


def tenant_token_check(request):
    """Accept the bearer token belonging to the tenant being addressed."""
    context = get_context(request)
    if context is None:
        # Not a SCIM request, so there is no tenant to check against.
        return False

    token = request.META.get("HTTP_AUTHORIZATION", "").removeprefix("Bearer ")
    if not token:
        return False

    expected = lookup_tenant_token(context.scope)
    if expected is None:
        return False
    return hmac.compare_digest(token, expected)
```

Where the tokens live is up to you — this app deliberately ships no credential model.
A small model on your side, with the secret hashed and a `last_used_at` timestamp, is
usually the right shape; `context.scope` is the tenant key to look it up by.

Use `hmac.compare_digest` rather than `==` so the comparison does not leak the token
through timing.

## How isolation works

Every `SCIMUser` and `SCIMGroup` row records the `config` and `scope` it was created
under, and adapters filter on that pair. In practice:

- The same `userName` can be provisioned into two tenants; they are separate records.
- A tenant listing only ever returns its own users and groups, filters included.
- Fetching, updating or deleting another tenant's resource id returns `404`, both across
  tenants and across configurations.
- Group member references that do not resolve within the current tenant are ignored, so
  a `PATCH` cannot pull a foreign user into a group.
- A group's member list never exposes another tenant's record, even when the same Django
  user is provisioned in both.

### Django's own unique constraints

`auth.User.username` and `auth.Group.name` are unique across the whole table, so two
tenants provisioning `alice` or `Admins` would collide no matter how the SCIM records are
partitioned. The default adapters therefore namespace the underlying Django object by
tenant: `alice` provisioned by tenant `acme` becomes the Django username `acme:alice`,
while the SCIM `userName` stays `alice`.

Override the hooks if you want a different mapping — for instance if your user model
drops the global uniqueness constraint, or you prefer a different separator:

```python
# myproject/adapters.py
from django_scim2_server.adapters import DefaultGroupAdapter, DefaultUserAdapter


class TenantUserAdapter(DefaultUserAdapter):
    def get_django_username(self, scim_username):
        return f"{self.scope}/{scim_username}" if self.scope else scim_username


class TenantGroupAdapter(DefaultGroupAdapter):
    def get_django_group_name(self, display_name):
        return f"{self.scope}/{display_name}" if self.scope else display_name
```

Unscoped configurations pass the value straight through, so the staff surface keeps
plain `alice` and `Admins`.

## Scoping your own models

If a tenant's users live in your own models rather than the built-in ones, override
`get_queryset` and read the tenant from `self.context`:

```python
# myproject/scoped_adapters.py
from django_scim2_server.adapters import DefaultUserAdapter


class OrganisationUserAdapter(DefaultUserAdapter):
    def get_queryset(self):
        return super().get_queryset().filter(user__organisation__slug=self.scope)
```

The group adapter resolves member references through the configuration's user adapter,
so a narrower user queryset automatically narrows who can be added to a group.

## Different capabilities per surface

A configuration can advertise its own `/ServiceProviderConfig` document, which is useful
when the staff and tenant surfaces authenticate differently:

```python
SCIM2_SERVER_CONFIGS = {
    "tenants": {
        "SERVICE_PROVIDER_CONFIG": "myproject.scim.TENANT_SERVICE_PROVIDER_CONFIG",
        "SCOPE_URL_KWARG": "tenant",
    },
}
```

The dotted path must point at a `scim2_models.ServiceProviderConfig` instance.
