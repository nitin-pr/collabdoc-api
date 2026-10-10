"""
Audit trail for documents.

Every Document save writes one AuditLog row. The row is created by these signal
receivers, never by a view, and because post_save fires inside the same
transaction.atomic() block as the save itself, the log is rolled back together
with the document if anything later in that block fails.
"""

from django.db.models.signals import post_save, pre_save
from django.dispatch import receiver

from documents.models import Document

from .models import AuditLog


@receiver(pre_save, sender=Document)
def remember_if_document_is_new(sender, instance, **kwargs):
    # `_state.adding` is True only until the first save completes, so by the time
    # post_save runs it is already False. Capture it here, while it is still accurate.
    instance._audit_action = 'created' if instance._state.adding else 'updated'


@receiver(post_save, sender=Document)
def write_document_audit_log(sender, instance, created, **kwargs):
    action = getattr(instance, '_audit_action', 'created' if created else 'updated')
    AuditLog.objects.create(
        actor=instance.created_by,
        action=action,
        model_name='Document',
        object_id=str(instance.id),
    )
