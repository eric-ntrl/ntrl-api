# Data Retention System

3-tier retention system for compliance and clean development iteration.

## Retention Tiers

| Tier | Window | Description |
|------|--------|-------------|
| **Active** | 0-7 days | Full access, all features work |
| **Compliance** | 7d-12mo | Metadata + neutralized content retained |
| **Deleted** | >12mo | Permanent removal |

## Retention CLI

```bash
# Check current status
pipenv run python -m app.cli.retention status

# Preview what would be purged
pipenv run python -m app.cli.retention purge --dry-run

# Development mode purge (hard delete)
pipenv run python -m app.cli.retention purge --dev --days 3 --confirm

# Switch retention policy
pipenv run python -m app.cli.retention set-policy production
```

## Retention API Endpoints

| Endpoint | Method | Purpose |
|----------|--------|---------|
| `/v1/admin/retention/status` | GET | Current retention stats |
| `/v1/admin/retention/policy` | GET/PUT | View/update policy |
| `/v1/admin/retention/purge` | POST | Trigger purge (requires confirm) |
| `/v1/admin/retention/dry-run` | POST | Preview purge |

## Key Components

| Component | Location | Purpose |
|-----------|----------|---------|
| `RetentionPolicy` | `app/models.py` | Configurable retention windows |
| `ContentLifecycleEvent` | `app/models.py` | Immutable audit trail |
| `policy_service` | `app/services/retention/` | Policy CRUD |
| `archive_service` | `app/services/retention/` | Tier transitions |
| `purge_service` | `app/services/retention/` | FK-safe deletion |

## Safety Features

- **Brief protection**: Never deletes articles in current brief
- **Legal hold**: Stories with `legal_hold=True` cannot be deleted
- **Soft delete grace**: 24-hour window before hard delete
- **Dry run**: Preview before executing any purge
