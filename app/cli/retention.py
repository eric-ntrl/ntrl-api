# app/cli/retention.py
"""
CLI commands for retention management.

Usage:
    pipenv run python -m app.cli.retention status
    pipenv run python -m app.cli.retention purge --days 3 --dry-run
    pipenv run python -m app.cli.retention purge --days 3 --confirm
    pipenv run python -m app.cli.retention set-policy production
    pipenv run python -m app.cli.retention archive --batch-size 100
"""

import argparse

# Set up database URL before importing models
import sys

from dotenv import load_dotenv

load_dotenv()


def get_db_session():
    """Get a database session."""
    from app.database import SessionLocal

    return SessionLocal()


def cmd_status(args):
    """Show current retention status and statistics."""
    from app.services.retention.archive_service import get_retention_stats
    from app.services.retention.policy_service import ensure_default_policies, get_retention_config
    from app.services.retention.purge_service import get_purge_preview

    db = get_db_session()
    try:
        # Ensure policies exist
        ensure_default_policies(db)

        # Get stats
        stats = get_retention_stats(db)
        preview = get_purge_preview(db)
        config = get_retention_config(db)

        print("\n=== Retention Status ===\n")

        print(f"Active Policy: {config['active_policy']}")
        print(f"  Active window: {config['active_days']} days")
        print(f"  Compliance window: {config['compliance_days']} days")
        print(f"  Hard delete mode: {config['hard_delete_mode']}")
        print(f"  Auto archive: {config['auto_archive']}")

        print(f"\nTotal Stories: {stats['total']}")
        print("\nBy Retention Tier:")
        for tier, count in stats["by_tier"].items():
            print(f"  {tier}: {count}")

        print("\nPending Operations:")
        print(f"  Stories to soft delete: {preview['pending_soft_delete']}")
        print(f"  Stories to hard delete: {preview['pending_hard_delete']}")
        print(f"  Protected by brief: {preview['protected_by_brief']}")

        print()
    finally:
        db.close()


def cmd_set_policy(args):
    """Switch the active retention policy."""
    from app.services.retention.policy_service import ensure_default_policies, get_policy_by_name, set_policy

    db = get_db_session()
    try:
        ensure_default_policies(db)

        # Check if policy exists
        policy = get_policy_by_name(db, args.name)
        if not policy:
            print(f"Error: Policy '{args.name}' not found")
            print("Available policies: development, production")
            sys.exit(1)

        # Switch policy
        policy = set_policy(db, args.name)
        print(f"Activated retention policy: {policy.name}")
        print(f"  Active days: {policy.active_days}")
        print(f"  Compliance days: {policy.compliance_days}")
        print(f"  Hard delete mode: {policy.hard_delete_mode}")
    finally:
        db.close()


def cmd_archive(args):
    """Archive expired content to compliance tier."""
    from app.services.retention import archive_batch, ensure_default_policies

    db = get_db_session()
    try:
        ensure_default_policies(db)

        print(f"\n{'DRY RUN - ' if args.dry_run else ''}Archiving content...\n")

        result = archive_batch(
            db,
            batch_size=args.batch_size,
            initiated_by="cli",
            dry_run=args.dry_run,
        )

        print(f"Processed: {result.stories_processed}")
        print(f"Archived: {result.stories_archived}")
        print(f"Skipped: {result.stories_skipped}")
        print(f"Failed: {result.stories_failed}")

        if result.errors:
            print("\nErrors:")
            for error in result.errors:
                print(f"  - {error}")

        if not result.success:
            sys.exit(1)
    finally:
        db.close()


def cmd_purge(args):
    """Purge expired content."""
    from app.services.retention import ensure_default_policies, purge_development_mode, purge_expired_content

    db = get_db_session()
    try:
        ensure_default_policies(db)

        # Safety check
        if not args.dry_run and not args.confirm:
            print("Error: Purge requires --confirm flag for non-dry-run operations")
            print("Use --dry-run to preview what would be deleted")
            sys.exit(1)

        mode = "development" if args.dev else "production"
        print(f"\n{'DRY RUN - ' if args.dry_run else ''}Purging content ({mode} mode)...\n")

        if args.dev:
            result = purge_development_mode(
                db,
                days=args.days,
                batch_size=args.batch_size,
                initiated_by="cli",
                dry_run=args.dry_run,
            )
        else:
            result = purge_expired_content(
                db,
                batch_size=args.batch_size,
                initiated_by="cli",
                dry_run=args.dry_run,
            )

        print(f"Soft deleted: {result.stories_soft_deleted}")
        print(f"Hard deleted: {result.stories_hard_deleted}")
        print(f"Skipped: {result.stories_skipped}")
        print(f"Protected by brief: {result.protected_by_brief}")
        print(f"Protected by hold: {result.protected_by_hold}")

        if result.related_records_deleted:
            print("\nRelated records deleted:")
            for table, count in result.related_records_deleted.items():
                print(f"  {table}: {count}")

        if result.errors:
            print("\nErrors:")
            for error in result.errors:
                print(f"  - {error}")

        if not result.success:
            sys.exit(1)
    finally:
        db.close()


def cmd_cleanup_orphans(args):
    """Clean up orphaned records."""
    from app.services.retention.purge_service import cleanup_orphaned_records

    db = get_db_session()
    try:
        print(f"\n{'DRY RUN - ' if args.dry_run else ''}Cleaning up orphaned records...\n")

        result = cleanup_orphaned_records(db, dry_run=args.dry_run)

        print("Orphaned records found:")
        for key, count in result.items():
            print(f"  {key}: {count}")
    finally:
        db.close()


def cmd_list_policies(args):
    """List all retention policies."""
    from app.services.retention.policy_service import ensure_default_policies, list_policies

    db = get_db_session()
    try:
        ensure_default_policies(db)
        policies = list_policies(db)

        print("\n=== Retention Policies ===\n")
        for policy in policies:
            status = "[ACTIVE]" if policy.is_active else ""
            print(f"{policy.name} {status}")
            print(f"  Active days: {policy.active_days}")
            print(f"  Compliance days: {policy.compliance_days}")
            print(f"  Hard delete mode: {policy.hard_delete_mode}")
            print(f"  Auto archive: {policy.auto_archive}")
            print()
    finally:
        db.close()


def main():
    parser = argparse.ArgumentParser(
        description="NTRL Retention Management CLI",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Check current status
  python -m app.cli.retention status

  # Preview what would be purged
  python -m app.cli.retention purge --dry-run

  # Purge in development mode (hard delete)
  python -m app.cli.retention purge --dev --days 3 --confirm

  # Switch to production policy
  python -m app.cli.retention set-policy production

  # Archive expired content
  python -m app.cli.retention archive --batch-size 50
        """,
    )

    subparsers = parser.add_subparsers(dest="command", required=True)

    # status command
    status_parser = subparsers.add_parser("status", help="Show retention status")
    status_parser.set_defaults(func=cmd_status)

    # set-policy command
    policy_parser = subparsers.add_parser("set-policy", help="Switch active policy")
    policy_parser.add_argument("name", choices=["development", "production"], help="Policy name to activate")
    policy_parser.set_defaults(func=cmd_set_policy)

    # list-policies command
    list_parser = subparsers.add_parser("list-policies", help="List all policies")
    list_parser.set_defaults(func=cmd_list_policies)

    # archive command
    archive_parser = subparsers.add_parser("archive", help="Archive expired content")
    archive_parser.add_argument("--batch-size", type=int, default=100, help="Max stories to archive (default: 100)")
    archive_parser.add_argument("--dry-run", action="store_true", help="Preview only, don't archive")
    archive_parser.set_defaults(func=cmd_archive)

    # purge command
    purge_parser = subparsers.add_parser("purge", help="Purge expired content")
    purge_parser.add_argument("--days", type=int, default=3, help="Days threshold for dev mode (default: 3)")
    purge_parser.add_argument("--batch-size", type=int, default=100, help="Max stories to purge (default: 100)")
    purge_parser.add_argument("--dev", action="store_true", help="Use development mode (hard delete)")
    purge_parser.add_argument("--dry-run", action="store_true", help="Preview only, don't purge")
    purge_parser.add_argument("--confirm", action="store_true", help="Confirm purge operation")
    purge_parser.set_defaults(func=cmd_purge)

    # cleanup-orphans command
    orphan_parser = subparsers.add_parser("cleanup-orphans", help="Clean up orphaned records")
    orphan_parser.add_argument("--dry-run", action="store_true", default=True, help="Preview only (default: true)")
    orphan_parser.add_argument("--execute", action="store_true", help="Actually delete orphaned records")
    orphan_parser.set_defaults(func=cmd_cleanup_orphans)

    args = parser.parse_args()

    # Handle --execute flag for cleanup-orphans
    if hasattr(args, "execute") and args.execute:
        args.dry_run = False

    args.func(args)


if __name__ == "__main__":
    main()
