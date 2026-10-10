# CollabDocs — Project Requirements

> Single source of truth for what we are building. Summarised from the official Airtribe brief.
> If something here conflicts with the brief, **the brief wins** — fix this file.

---

## 1. Overview

**CollabDocs** is the backend API for a simplified Notion / Google Docs. Users can:

- create **workspaces** and invite collaborators with roles (admin / editor / viewer)
- write **documents** that keep a full **version history**
- leave **threaded comments**
- **tag** documents
- have every document change recorded in an **audit log**

**Scope:** API only — no frontend. Postman is the client.

**Stack:** Python · Django · Django REST Framework · PostgreSQL

---

## 2. Data Models (8)

**Every primary key:** `id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)`
**Every enum:** `models.TextChoices` — no raw strings.
Extra fields beyond these are allowed.

### 2.1 User

| Field | Type | Notes |
|---|---|---|
| id | UUIDField (PK) | uuid4, editable=False |
| first_name | CharField(50) | |
| last_name | CharField(50) | |
| email | CharField(254) | `unique=True` — **CharField, not EmailField** |
| phone | CharField(15) | `unique=True` |
| created_at | DateTimeField | `auto_now_add=True` |

### 2.2 Workspace

| Field | Type | Notes |
|---|---|---|
| id | UUIDField (PK) | |
| name | CharField(255) | |
| owner | FK → User | `on_delete=CASCADE` |
| is_active | BooleanField | `default=True` |
| created_at | DateTimeField | `auto_now_add=True` |

> ⚠ When a workspace is created, the owner **must also be added as a WorkspaceMember with role = admin**, inside a single `transaction.atomic()`.

### 2.3 WorkspaceMember

| Field | Type | Notes |
|---|---|---|
| id | UUIDField (PK) | |
| workspace | FK → Workspace | `on_delete=CASCADE` |
| user | FK → User | `on_delete=CASCADE` |
| role | CharField | TextChoices: `admin`, `editor`, `viewer` |
| joined_at | DateTimeField | `auto_now_add=True` |

```python
class Meta:
    constraints = [
        models.UniqueConstraint(fields=['workspace', 'user'], name='unique_workspace_member')
    ]
```

### 2.4 Document

| Field | Type | Notes |
|---|---|---|
| id | UUIDField (PK) | |
| title | CharField(255) | |
| content | TextField | |
| workspace | FK → Workspace | `on_delete=CASCADE` |
| created_by | FK → User | `on_delete=SET_NULL, null=True` |
| status | CharField | TextChoices: `draft`, `published`, `archived` |
| updated_at | DateTimeField | `auto_now=True` |

> ⚠ **Every save must create a new DocumentVersion inside the same `transaction.atomic()` block.**

### 2.5 DocumentVersion

| Field | Type | Notes |
|---|---|---|
| id | UUIDField (PK) | |
| document | FK → Document | `on_delete=CASCADE`, `related_name='versions'` |
| content | TextField | Snapshot of content at save time |
| version_number | PositiveIntegerField | Per-document auto-increment (see below) |
| saved_by | FK → User | `on_delete=SET_NULL, null=True` |
| saved_at | DateTimeField | `auto_now_add=True` |

> ⚠ Compute `version_number = document.versions.count() + 1` **inside the atomic block**, before saving. No global counter.

### 2.6 Comment

| Field | Type | Notes |
|---|---|---|
| id | UUIDField (PK) | |
| document | FK → Document | `on_delete=CASCADE` |
| author | FK → User | `on_delete=SET_NULL, null=True` |
| content | TextField | |
| parent | FK → self | `null=True, blank=True, on_delete=SET_NULL, related_name='replies'` |
| created_at | DateTimeField | `auto_now_add=True` |

> A comment with `parent = None` is a **top-level** comment; otherwise it is a reply.

### 2.7 Tag

| Field | Type | Notes |
|---|---|---|
| id | UUIDField (PK) | |
| name | CharField(100) | `unique=True` |
| documents | ManyToManyField(Document) | `related_name='tags', blank=True` — **declared on Tag, not Document** |

Usage: `doc.tags.add(tag)` / `tag.documents.add(doc)` / `Document.objects.filter(tags__name='python')`

### 2.8 AuditLog

| Field | Type | Notes |
|---|---|---|
| id | UUIDField (PK) | |
| actor | FK → User | `on_delete=SET_NULL, null=True` |
| action | CharField(50) | e.g. `'created'`, `'updated'` |
| model_name | CharField(100) | e.g. `'Document'` |
| object_id | CharField(100) | UUID as string |
| timestamp | DateTimeField | `auto_now_add=True` |

> ⚠ Written **automatically by a `post_save` signal on Document** — never by the view directly.

### 2.9 Relationship map

```
User ──< Workspace (owner)
User ──< WorkspaceMember >── Workspace        unique (workspace, user)
Workspace ──< Document ──< DocumentVersion
User ──< Document (created_by) / DocumentVersion (saved_by)
Document ──< Comment ──< Comment (parent → replies)
Tag >──< Document                            (M2M declared on Tag)
User ──< AuditLog (actor)
```

---

## 3. API Endpoints (17)

Use **`ModelViewSet`** for standard CRUD, **`@action`** for custom endpoints, routes registered via **`DefaultRouter`**.

### Users (2)

| # | Method | Endpoint | Does | Concept tested |
|---|---|---|---|---|
| 1 | POST | `/api/users/` | Create a user | ModelViewSet, ModelSerializer, validation |
| 2 | GET | `/api/users/{id}/` | Get user by ID | UUID PK, serializer response |

### Workspaces (5)

| # | Method | Endpoint | Does | Concept tested |
|---|---|---|---|---|
| 3 | POST | `/api/workspaces/` | Create workspace + auto-add owner as admin | `transaction.atomic()`, override `create()` |
| 4 | GET | `/api/workspaces/{id}/` | Workspace with member count | `annotate()`, `Count` |
| 5 | POST | `/api/workspaces/{id}/members/` | Add a member with a role | FK, UniqueConstraint handling → **409**, custom validation |
| 6 | GET | `/api/workspaces/{id}/members/` | List members with roles | `select_related`, nested serializer |
| 7 | GET | `/api/workspaces/{id}/summary/` | Doc count, member count, total comments | `@action`, `aggregate()`, `annotate()`, `Count` |

### Documents (6)

| # | Method | Endpoint | Does | Concept tested |
|---|---|---|---|---|
| 8 | POST | `/api/documents/` | Create document + first version (atomic) | `transaction.atomic()`, version_number logic |
| 9 | PUT | `/api/documents/{id}/` | Update content — saves a new version | `transaction.atomic()`, override `update()` |
| 10 | GET | `/api/documents/` | List — filter by workspace, status, tag name; search title | Q objects, query params, `filter()`, `__icontains` |
| 11 | GET | `/api/documents/{id}/versions/` | All versions in order | `filter()`, `order_by()`, reverse FK lookup |
| 12 | GET | `/api/documents/{id}/stats/` | Version count, comment count, contributor count | `@action`, `aggregate()`, `annotate()`, `Count` |
| 13 | POST | `/api/documents/{id}/tags/` | Add one or more tags | `@action`, M2M `.add()` |

### Comments (2)

| # | Method | Endpoint | Does | Concept tested |
|---|---|---|---|---|
| 14 | POST | `/api/comments/` | Add a top-level comment or a reply | Self-referential FK, SerializerMethodField, validation |
| 15 | GET | `/api/comments/?document={id}` | All comments for a document (threaded) | `filter()`, `select_related`, query params |

### Tags & Audit Logs (2)

| # | Method | Endpoint | Does | Concept tested |
|---|---|---|---|---|
| 16 | POST | `/api/tags/` | Create a tag | ModelSerializer, unique constraint handling |
| 17 | GET | `/api/audit-logs/` | Filter by actor ID and date range | `filter()`, `__gte`, `__lte`, query params |

---

## 4. Technical Requirements

### 4.1 Models & database
- [x] All PKs are `UUIDField(default=uuid.uuid4, editable=False)`
- [x] `TextChoices` for every enum (role, status)
- [x] `UniqueConstraint` on WorkspaceMember (workspace, user) in `Meta`
- [x] `ManyToManyField` between Tag and Document (declared on Tag)
- [x] Self-referential FK on Comment
- [x] All migrations committed and apply cleanly on an empty database

### 4.2 Serializers & views
- [x] `ModelViewSet` wherever CRUD is standard — no raw `APIView`
- [x] `@action` for all non-standard endpoints (members, summary, versions, stats, tags)
- [x] **≥ 2** `SerializerMethodField` uses across the project
- [x] Custom validation in **≥ 2** serializers
- [x] Every error has a meaningful message and the right status code: **400** bad input · **404** not found · **409** duplicate/conflict

### 4.3 QuerySets & filtering
- [x] `select_related` on every endpoint returning nested user / workspace / document data
- [x] `filter()` with lookups (`__gte`, `__lte`, `__in`, `__icontains`) on all filterable list endpoints
- [x] `Q` objects for OR filtering on the document list
- [x] `aggregate()` / `annotate()` with `Count` in **≥ 3** endpoints (workspace detail, summary, stats)
- [x] `values_list()` wherever only IDs are needed

### 4.4 Transactions & data integrity
- [x] Workspace creation + owner-as-admin in **one** `transaction.atomic()`
- [x] Document save + version creation in **one** `transaction.atomic()`
- [x] AuditLog written **inside the same atomic block** as the action it records
- [x] `DoesNotExist` and `IntegrityError` handled explicitly
- [x] `IntegrityError` on duplicate WorkspaceMember → **409 Conflict**

### 4.5 Middleware
- [x] Custom request-logging middleware class with `__init__(self, get_response)` and `__call__(self, request)`
- [x] Prints, for every request: **HTTP method · path · status code · time taken (ms)**
- [x] Registered in `settings.py` → `MIDDLEWARE`

### 4.6 Signals
- [x] `post_save` receiver on Document in **`signals.py`**, connected in **`AppConfig.ready()`**
- [x] Uses `instance._state.adding` to detect create vs update
- [x] Writes AuditLog with: `actor=created_by`, `action='created'|'updated'`, `model_name='Document'`, `object_id=str(id)`

### 4.7 Project setup
- [x] PostgreSQL credentials from `.env` — **never hard-coded**
- [x] `.env.example` committed (real `.env` is git-ignored)
- [x] `requirements.txt` with **pinned** versions
- [x] `README.md`: setup, run server, apply migrations, demo-video link
- [x] Postman collection `.json` in the **repository root**

---

## 5. Marking Rubric (100)

| Area | What they look for | Marks |
|---|---|---|
| Models & migrations | Field types, UUID PKs, TextChoices, UniqueConstraint in Meta, M2M, self-FK, clean migrations | **20** |
| Serializers & validation | ModelSerializer, 2× SerializerMethodField, custom validators, messages, status codes | **15** |
| ViewSets & routing | ModelViewSet CRUD, `@action`, overridden `create()`/`update()`, DefaultRouter | **15** |
| QuerySets & filtering | `select_related`, `__` lookups incl. `__icontains`, Q objects, `values_list()`, query params | **15** |
| Aggregations | `aggregate()`/`annotate()` with Count in ≥ 3 endpoints (stats, summary, workspace detail) | **10** |
| Transactions & integrity | `atomic()` for workspace + document flows; AuditLog in same block; DoesNotExist & IntegrityError handled | **10** |
| Middleware & signals | Working logging middleware; post_save signal writing AuditLog; both registered correctly | **10** |
| Code quality & setup | README, `.env.example`, `requirements.txt`, clean structure, readable code | **5** |

---

## 6. Submission (all three required — incomplete = marked down)

### 6.1 GitHub repository
- [ ] **Public** repo with full source
- [x] `.env.example`, pinned `requirements.txt`, all migrations, `README.md`
- [x] Postman collection `.json` in the repo root

### 6.2 Postman collection
- [x] Covers **all 17 endpoints**
- [x] Sample request bodies for every POST and PUT
- [x] Folders: **Users · Workspaces · Documents · Comments · Tags · Audit Logs**

### 6.3 Demo video (5–10 min, screen + audio, via Postman)
- [ ] One complete atomic transaction **with rollback on failure**
- [ ] Middleware logs appearing in the console
- [ ] At least one aggregation endpoint (stats or summary)
- [ ] AuditLog written by the signal after a document update
- [ ] Uploaded to Loom / Google Drive, link in `README.md`

---

## 7. Interpretations & Team Decisions

The brief leaves a few things open. Unless we agree otherwise, we follow these:

| Topic | Decision | Reason |
|---|---|---|
| Role-based permissions | Treat `WorkspaceMember.role` as **data only**; no enforcement. Optional stretch goal. | Brief never requires enforcement; rubric awards no marks for it. |
| Authentication | **None.** Caller identity is passed as a user ID in the request body (`owner`, `created_by`, `author`, `saved_by`). | No auth in scope; Postman is the client. |
| User model | **Plain Django model**, not a replacement for `AUTH_USER_MODEL`. | Spec has no password/username; keeps it simple. |
| Rollback demo | Trigger a deliberate failure after the first write inside an atomic block (e.g. invalid data after the document row is saved) and show that **nothing** was persisted. | Required in the demo video. |
| Contributor count (stats) | Number of distinct users who saved a version of the document. | Most natural reading of "contributor". |
| Document list filters | `workspace`, `status` (comma list), `tag` (comma list, matches any) and `created_by`; `search` matches title **or** content (a `Q` OR). Bad values return 400. | Brief asks for Q-object OR filtering on the document list. |
| Tags | Names are trimmed and lower-cased; adding a tag to a document never creates it (unknown tag -> 404). | Keeps `Document.objects.filter(tags__name='python')` predictable. |
| Rollback demo | `simulate_failure` in the body of POST / PUT `/api/documents/`, honoured only when `DJANGO_DEBUG=True`. | Gives the demo video a deliberate failure inside the atomic block without risking production. |
| Audit-log dates | `from` / `to` accept `YYYY-MM-DD` (whole days, `to` inclusive) or ISO 8601. | `?to=2026-10-09` should include everything that happened on the 9th. |

---

## 8. Definition of Done (per feature)

A feature is done when:

1. Code committed to `main` with its tests passing (`python manage.py test`).
2. Migrations (if any) committed and `python manage.py migrate` works on an empty DB.
3. Happy path **and** error paths (400 / 404 / 409) return the correct status code and a clear message.
4. Its requests are in `CollabDocs.postman_collection.json` under the correct folder, with sample bodies.
5. The relevant boxes in §4 above are ticked.
