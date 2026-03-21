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

Include the SCIM URL routes in your root URL configuration:

```python
from django.urls import include, path

urlpatterns = [
    # ...
    path("scim/v2/", include("django_scim2_server.urls")),
]
```

Run migrations to create the SCIM database tables:

```bash
python manage.py migrate
```

Next, see the {ref}`section about usage <usage>` to learn how to configure and use the app.
