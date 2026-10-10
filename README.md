# CollabDocs API

Backend API for **CollabDocs**, a simplified Notion / Google Docs. Users create workspaces, invite collaborators with roles (admin / editor / viewer), write documents that keep a full version history, leave threaded comments and tag documents. Every document change is recorded in an audit log.

Built with **Django 5.2**, **Django REST Framework** and **PostgreSQL 16**. API only: Postman is the client.

- Full requirements and the decisions behind them: [PROJECT_REQUIREMENTS.md](PROJECT_REQUIREMENTS.md)
- Postman collection (all 17 endpoints): [CollabDocs.postman_collection.json](CollabDocs.postman_collection.json)
- Demo video: _link to be added after recording_

---

## Prerequisites

- Python 3.10+
- **Docker Desktop** (runs PostgreSQL 16), or your own PostgreSQL 14+ install
- Postman

## Setup

```bash
# 1. Create and activate a virtual environment
python -m venv .venv
# Windows (PowerShell)
.venv\Scripts\Activate.ps1
# macOS / Linux
source .venv/bin/activate

# 2. Install dependencies
pip install -r requirements.txt

# 3. Configure environment variables
cp .env.example .env        # Windows: copy .env.example .env
# then set DJANGO_SECRET_KEY in .env (the DB values already match the Docker database)
python -c "from django.core.management.utils import get_random_secret_key; print(get_random_secret_key())"
```

## Start the database (Docker)

```bash
docker compose up -d        # PostgreSQL 16 on localhost:5434, database created from .env
docker compose ps           # wait until STATUS shows "healthy"
```

| Task | Command |
|---|---|
| Stop the database (data kept) | `docker compose stop` |
| Reset to an empty database | `docker compose down -v && docker compose up -d` |
| SQL prompt | `docker compose exec db psql -U collabdocs -d collabdocs` |
| Database logs | `docker compose logs -f db` |

<details>
<summary>Without Docker (local PostgreSQL install)</summary>

Create the database and a user, then put those values in `.env` with `DB_PORT=5432`:

```sql
CREATE USER collabdocs WITH PASSWORD 'collabdocs' CREATEDB;
CREATE DATABASE collabdocs OWNER collabdocs;
```

</details>

## Apply migrations

```bash
python manage.py migrate
```

All migrations are committed and apply cleanly on an empty database.

## Run the server

```bash
python manage.py runserver
```

The API root is at <http://127.0.0.1:8000/api/>. Every request is also printed in the terminal by the logging middleware:

```
[API] POST /api/documents/ -> 201 (42.17 ms)
```

## Run the tests

```bash
python manage.py test
```

153 tests covering every endpoint's success and error paths, the transactions and rollbacks, the audit-log signal, the middleware and query counts. Django builds a separate `test_collabdocs` database for them and removes it afterwards, so your data is untouched.

## Postman

1. Import `CollabDocs.postman_collection.json` (repository root).
2. Start the server, then run the collection top to bottom (**Run collection**). Folders: **Users, Workspaces, Documents, Comments, Tags, Audit Logs**.
3. Collection variables (`{{base_url}}`, `{{user_id}}`, `{{workspace_id}}`, `{{document_id}}`, ...) are filled in automatically by each request's test script, so the whole run is self-contained. Every POST and PUT has a sample body, and the error cases (400 / 404 / 409) sit next to the request they exercise.

## API endpoints

| # | Area | Method | Endpoint | Notes |
|---|---|---|---|---|
| 1 | Users | POST | `/api/users/` | 400 invalid email / phone, 409 duplicate |
| 2 | | GET | `/api/users/{id}/` | 404 unknown or malformed id |
| 3 | Workspaces | POST | `/api/workspaces/` | creates the workspace and adds the owner as admin in one `atomic()` block |
| 4 | | GET | `/api/workspaces/{id}/` | includes `member_count` (annotate + Count) |
| 5 | | POST | `/api/workspaces/{id}/members/` | `{user, role}`; 409 if already a member, 404 unknown user |
| 6 | | GET | `/api/workspaces/{id}/members/` | members with nested users; optional `?role=editor,viewer` |
| 7 | | GET | `/api/workspaces/{id}/summary/` | document / member / comment totals (aggregate + Count) |
| 8 | Documents | POST | `/api/documents/` | document + version 1 + audit log in one `atomic()` block |
| 9 | | PUT | `/api/documents/{id}/` | updates content and saves the next version, also atomically |
| 10 | | GET | `/api/documents/` | filters `?workspace=&status=&tag=&search=` (see below) |
| 11 | | GET | `/api/documents/{id}/versions/` | all versions, oldest first |
| 12 | | GET | `/api/documents/{id}/stats/` | version, comment, contributor (and tag) counts |
| 13 | | POST | `/api/documents/{id}/tags/` | `{"tags": ["python", "<tag id>"]}`; 404 for an unknown tag |
| 14 | Comments | POST | `/api/comments/` | top-level, or a reply when `parent` is set |
| 15 | | GET | `/api/comments/?document={id}` | threaded: replies nested under their parent |
| 16 | Tags | POST | `/api/tags/` | names are lower-cased and unique, 409 on duplicate |
| 17 | Audit Logs | GET | `/api/audit-logs/?actor=&from=&to=` | dates as `YYYY-MM-DD` (whole days, `to` inclusive) or ISO 8601 |

**Document list filters:** `workspace` (id), `status` (one or comma-separated), `tag` (name, one or comma-separated, matches any), `search` (case-insensitive match on title **or** content), `created_by` (id). They combine. Bad values return 400, never 500.

**Error codes:** 400 invalid input, 404 not found, 409 duplicate / conflict. Errors are JSON such as `{"detail": "User is already a member of this workspace."}`.

## How the assignment requirements are met

| Requirement | Where |
|---|---|
| 8 models, UUID primary keys, `TextChoices` for every enum | `users/`, `workspaces/`, `documents/`, `collaboration/` `models.py` |
| `UniqueConstraint` on WorkspaceMember, M2M on `Tag`, self-referential `Comment.parent` | `workspaces/models.py`, `collaboration/models.py` |
| `ModelViewSet`-family viewsets, `@action`, one `DefaultRouter` | each app's `views.py` / `routes.py`, `config/urls.py` |
| `SerializerMethodField` (6 uses) and custom validation (6 serializers) | `owner_name`, `tag_names`, `saved_by_name`, `author_name`, `replies`, `actor_name`; `validate_*` methods |
| `select_related`, `Q` objects, `__icontains` / `__gte` / `__lte` / `__in`, `values_list` | `documents/views.py`, `collaboration/views.py`, `workspaces/views.py` |
| `aggregate()` / `annotate()` with `Count` | workspace detail, workspace summary, document stats |
| `transaction.atomic()` for workspace and document flows, audit log in the same block | `workspaces/views.py`, `documents/views.py` |
| `DoesNotExist` and `IntegrityError` handled explicitly (duplicate member -> 409) | `workspaces/views.py`, `users/views.py`, `collaboration/views.py` |
| Request logging middleware | `common/middleware.py`, registered in `config/settings.py` |
| `post_save` signal writing the AuditLog, connected in `AppConfig.ready()` | `collaboration/signals.py`, `collaboration/apps.py` |
| Credentials in `.env`, `.env.example`, pinned `requirements.txt` | project root |

## Demo walkthrough (for the video)

Run the Postman collection step by step with the server terminal visible beside it:

1. **Middleware**: the terminal prints an `[API] ...` line for every request.
2. Create two users, a workspace (owner auto-added as admin, `member_count` is 1), add a member, then add the same member again to see **409**.
3. **Aggregation**: `GET /workspaces/{id}/summary/` and `GET /documents/{id}/stats/`.
4. Create a document, update it with `PUT`, then `GET .../versions/` shows v1 and v2.
5. **Signal**: `GET /audit-logs/?object_id={{document_id}}` shows `created` then `updated`, written by the `post_save` receiver and never by a view.
6. **Atomic transaction with rollback**: send *Create document - rollback demo*. The request fails with 400 after the document, its first version and its audit log were written. `GET /documents/` and `GET /audit-logs/` then show that nothing was kept.

`simulate_failure` is a demo switch: it is only honoured while `DJANGO_DEBUG=True` (the default in `.env.example`) and is refused otherwise, so it can never fire in production.

## Design notes

- **No authentication** (per the brief): the caller is identified by a user id in the request body (`owner`, `created_by`, `author`, `saved_by`). `WorkspaceMember.role` is stored data and is not enforced.
- **Version numbers** are per document: `document.versions.count() + 1`, computed inside the atomic block with the document row locked (`select_for_update`). A `UniqueConstraint(document, version_number)` backs it up.
- **Audit log** actor is the document's `created_by`. The signal captures `instance._state.adding` in a `pre_save` receiver, because it is already `False` by the time `post_save` runs.
- **Contributors** (document stats) are the distinct users who saved at least one version.
- **Tags** are lower-cased and trimmed, so `Python` and `python` are the same tag. Attaching a tag to a document does not create it: create it first with `POST /api/tags/`.
- **Threaded comments** are built from a single query and assembled in memory, so loading a whole thread costs two queries however deep it is.

## Project structure

```
collabdocs-api/
├── config/          # settings, root urls (single DefaultRouter), wsgi/asgi
├── common/          # request logging middleware, query-param helpers, test factories
├── users/           # User
├── workspaces/      # Workspace, WorkspaceMember
├── documents/       # Document, DocumentVersion
├── collaboration/   # Comment, Tag, AuditLog + post_save signal
├── CollabDocs.postman_collection.json
├── docker-compose.yml  # PostgreSQL 16 for local development
└── manage.py
```

Each app registers its endpoints in its own `routes.py`; `config/urls.py` collects them into one `DefaultRouter` under `/api/`.
