(installation)=

# Installation

The package is published on [PyPI](https://pypi.org/project/django-scim2-server/) and can be installed with `pip` (or any equivalent):

```bash
pip install django-scim2-server
```

Add the app to your `INSTALLED_APPS`:

```python
INSTALLED_APPS = [
    # ...
    "django_scim2_server",
]
```

Declare at least one SCIM configuration. A configuration names the adapters and the
access-control callable used by one SCIM surface; the empty dict below accepts all the
defaults:

```python
# settings.py
SCIM2_SERVER_CONFIGS = {
    "default": {},
}
```

Include the SCIM URL routes in your root URL configuration, mounting each configuration
under its own prefix:

```python
from django.urls import include, path

from django_scim2_server.urls import scim2_urls

urlpatterns = [
    # ...
    path("scim/v2/", include(scim2_urls("default"))),
]
```

Run migrations to create the SCIM database tables:

```bash
python manage.py migrate
```

Finally, confirm your configurations resolve — the app ships system checks that import
every adapter and access-control callable you referenced:

```bash
python manage.py check
```

Next, see the {ref}`section about usage <usage>` to learn how to configure and use the
app, or {doc}`multi-config` to serve several SCIM surfaces at once.
