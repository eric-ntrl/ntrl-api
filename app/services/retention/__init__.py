# app/services/retention/__init__.py
"""
Retention management services for NTRL data lifecycle.

Three-tier retention system:
- Tier 1 (Active): 0-7 days, full access
- Tier 2 (Compliance): 7d-12mo, archived content
- Tier 3 (Deleted): >12mo, permanent removal

Services:
- policy_service: Retention policy CRUD
- archive_service: Tier transition logic
- purge_service: Cascade-safe deletion
- scheduler: Daily cron orchestration
"""

from app.services.retention.archive_service import (
    ArchiveResult,
    archive_batch,
    archive_story,
    find_archivable_stories,
)
from app.services.retention.policy_service import (
    create_policy,
    ensure_default_policies,
    get_active_policy,
    get_policy_by_name,
    set_policy,
)
from app.services.retention.purge_service import (
    PurgeResult,
    dry_run_purge,
    purge_development_mode,
    purge_expired_content,
)

__all__ = [
    # Policy
    "get_active_policy",
    "set_policy",
    "create_policy",
    "get_policy_by_name",
    "ensure_default_policies",
    # Archive
    "find_archivable_stories",
    "archive_story",
    "archive_batch",
    "ArchiveResult",
    # Purge
    "purge_expired_content",
    "purge_development_mode",
    "dry_run_purge",
    "PurgeResult",
]
