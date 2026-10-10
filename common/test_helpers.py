"""Small factories used by the test-suites of every app."""

import itertools

from documents.models import Document, DocumentVersion
from users.models import User
from workspaces.models import Workspace, WorkspaceMember

_counter = itertools.count(1)


def make_user(**overrides):
    n = next(_counter)
    values = {
        'first_name': 'User',
        'last_name': f'Number{n}',
        'email': f'user{n}@example.com',
        'phone': f'9{n:09d}',
    }
    return User.objects.create(**{**values, **overrides})


def make_workspace(owner=None, **overrides):
    """A workspace plus its owner as an admin member, exactly as the API creates it."""
    owner = owner or make_user()
    workspace = Workspace.objects.create(**{'name': 'Team space', 'owner': owner, **overrides})
    WorkspaceMember.objects.create(workspace=workspace, user=owner, role=WorkspaceMember.Role.ADMIN)
    return workspace


def make_document(workspace=None, created_by=None, **overrides):
    """A document with its first version. The post_save signal also writes the 'created' AuditLog."""
    created_by = created_by or make_user()
    workspace = workspace or make_workspace(owner=created_by)
    document = Document.objects.create(
        **{'title': 'Design notes', 'content': 'first draft', 'workspace': workspace,
           'created_by': created_by, **overrides}
    )
    DocumentVersion.objects.create(
        document=document, content=document.content, version_number=1, saved_by=created_by
    )
    return document
