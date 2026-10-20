import uuid

from django.db import models


class Blog(models.Model):
    name = models.CharField(max_length=50)


class Author(models.Model):
    full_name = models.CharField(max_length=50)


class Post(models.Model):
    blog = models.ForeignKey(
        Blog,
        on_delete=models.CASCADE,
        related_name="posts",
    )
    author = models.ForeignKey(
        Author,
        on_delete=models.CASCADE,
        related_name="posts",
    )
    title = models.CharField(max_length=50)
    content = models.TextField()


class Organisation(models.Model):
    name = models.CharField(max_length=50)
    scim_token = models.CharField(max_length=64, unique=True)


class Member(models.Model):
    uuid = models.UUIDField(unique=True, default=uuid.uuid4, editable=False)
    organisation = models.ForeignKey(
        Organisation,
        on_delete=models.CASCADE,
        related_name="members",
    )
    email = models.EmailField()
    given_name = models.CharField(max_length=50, blank=True)
    family_name = models.CharField(max_length=50, blank=True)
    department = models.CharField(max_length=50, blank=True)
    active = models.BooleanField(default=True)

    class Meta:  # noqa: D106
        constraints = [  # noqa: RUF012
            models.UniqueConstraint(
                fields=["organisation", "email"],
                name="unique_member_email_per_organisation",
            ),
        ]
