from django.db import models


class Contact(models.Model):
    """
    Contact entity model.
    """

    name = models.CharField(max_length=255)
    email = models.EmailField(unique=True, db_index=True)
    age = models.IntegerField(null=True, blank=True)
    status = models.CharField(max_length=50, default="active", db_index=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "contacts"
        ordering = ["id"]
        indexes = [
            models.Index(fields=["email"]),
            models.Index(fields=["status"]),
        ]

    def __str__(self) -> str:
        return f"{self.name} <{self.email}>"


class Lead(models.Model):
    """
    Lead entity model to demonstrate entity-agnostic architecture.
    """

    name = models.CharField(max_length=255)
    email = models.EmailField(unique=True, db_index=True)
    company = models.CharField(max_length=255, blank=True, default="")
    status = models.CharField(max_length=50, default="new", db_index=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "leads"
        ordering = ["id"]
        indexes = [
            models.Index(fields=["email"]),
            models.Index(fields=["status"]),
        ]

    def __str__(self) -> str:
        return f"Lead: {self.name} <{self.email}>"
