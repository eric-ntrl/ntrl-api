# app/services/retention/policy_service.py
"""
Retention policy management service.

Handles CRUD operations for retention policies and ensures exactly
one policy is active at any time.
"""

import logging
import os
from typing import Optional

from sqlalchemy.orm import Session

from app.models import RetentionPolicy

logger = logging.getLogger(__name__)


# Default policy configurations
DEFAULT_POLICIES = {
    "development": {
        "active_days": 7,
        "compliance_days": 30,
        "auto_archive": False,
        "hard_delete_mode": True,  # No Glacier, just delete
    },
    "production": {
        "active_days": 7,
        "compliance_days": 365,
        "auto_archive": True,
        "hard_delete_mode": False,  # Archive to Glacier
    },
}


def get_active_policy(db: Session) -> Optional[RetentionPolicy]:
    """
    Get the currently active retention policy.

    If no policy is active, returns None. Callers should use
    ensure_default_policies() at startup to guarantee a policy exists.
    """
    return (
        db.query(RetentionPolicy)
        .filter(RetentionPolicy.is_active == True)
        .first()
    )


def get_policy_by_name(db: Session, name: str) -> Optional[RetentionPolicy]:
    """Get a retention policy by name."""
    return (
        db.query(RetentionPolicy)
        .filter(RetentionPolicy.name == name)
        .first()
    )


def set_policy(db: Session, name: str) -> RetentionPolicy:
    """
    Switch the active retention policy.

    Deactivates any currently active policy and activates the named one.
    Raises ValueError if the named policy doesn't exist.
    """
    policy = get_policy_by_name(db, name)
    if not policy:
        raise ValueError(f"Retention policy '{name}' not found")

    # Deactivate all policies
    db.query(RetentionPolicy).filter(
        RetentionPolicy.is_active == True
    ).update({"is_active": False})

    # Activate the requested policy
    policy.is_active = True
    db.add(policy)
    db.commit()
    db.refresh(policy)

    logger.info(f"Activated retention policy: {name}")
    return policy


def create_policy(
    db: Session,
    name: str,
    active_days: int = 7,
    compliance_days: int = 365,
    auto_archive: bool = True,
    hard_delete_mode: bool = False,
    activate: bool = False,
) -> RetentionPolicy:
    """
    Create a new retention policy.

    Args:
        db: Database session
        name: Unique policy name
        active_days: Days in Tier 1 (active)
        compliance_days: Days in Tier 2 (compliance archive)
        auto_archive: Enable automatic archival
        hard_delete_mode: Skip archival, go straight to delete
        activate: Make this the active policy

    Returns:
        The created RetentionPolicy
    """
    existing = get_policy_by_name(db, name)
    if existing:
        raise ValueError(f"Retention policy '{name}' already exists")

    if activate:
        # Deactivate all policies first
        db.query(RetentionPolicy).filter(
            RetentionPolicy.is_active == True
        ).update({"is_active": False})

    policy = RetentionPolicy(
        name=name,
        active_days=active_days,
        compliance_days=compliance_days,
        auto_archive=auto_archive,
        hard_delete_mode=hard_delete_mode,
        is_active=activate,
    )

    db.add(policy)
    db.commit()
    db.refresh(policy)

    logger.info(f"Created retention policy: {name} (active={activate})")
    return policy


def ensure_default_policies(db: Session) -> RetentionPolicy:
    """
    Ensure default retention policies exist and one is active.

    Creates 'development' and 'production' policies if they don't exist.
    Activates the appropriate one based on ENVIRONMENT env var.

    Returns the active policy.
    """
    environment = os.getenv("ENVIRONMENT", "development").lower()

    # Create default policies if needed
    for name, config in DEFAULT_POLICIES.items():
        existing = get_policy_by_name(db, name)
        if not existing:
            create_policy(
                db,
                name=name,
                active_days=config["active_days"],
                compliance_days=config["compliance_days"],
                auto_archive=config["auto_archive"],
                hard_delete_mode=config["hard_delete_mode"],
                activate=False,
            )
            logger.info(f"Created default retention policy: {name}")

    # Ensure one is active
    active = get_active_policy(db)
    if not active:
        # Activate based on environment
        default_name = "production" if environment == "production" else "development"
        active = set_policy(db, default_name)
        logger.info(f"Activated default retention policy: {default_name}")

    return active


def update_policy(
    db: Session,
    name: str,
    active_days: Optional[int] = None,
    compliance_days: Optional[int] = None,
    auto_archive: Optional[bool] = None,
    hard_delete_mode: Optional[bool] = None,
) -> RetentionPolicy:
    """
    Update an existing retention policy.

    Only updates fields that are explicitly provided (not None).
    """
    policy = get_policy_by_name(db, name)
    if not policy:
        raise ValueError(f"Retention policy '{name}' not found")

    if active_days is not None:
        policy.active_days = active_days
    if compliance_days is not None:
        policy.compliance_days = compliance_days
    if auto_archive is not None:
        policy.auto_archive = auto_archive
    if hard_delete_mode is not None:
        policy.hard_delete_mode = hard_delete_mode

    db.add(policy)
    db.commit()
    db.refresh(policy)

    logger.info(f"Updated retention policy: {name}")
    return policy


def list_policies(db: Session) -> list[RetentionPolicy]:
    """List all retention policies."""
    return db.query(RetentionPolicy).order_by(RetentionPolicy.name).all()


def get_retention_config(db: Session) -> dict:
    """
    Get current retention configuration as a dict.

    Useful for displaying in status endpoints and CLI.
    """
    active = get_active_policy(db)
    if not active:
        return {
            "active_policy": None,
            "active_days": 7,
            "compliance_days": 365,
            "auto_archive": True,
            "hard_delete_mode": False,
        }

    return {
        "active_policy": active.name,
        "active_days": active.active_days,
        "compliance_days": active.compliance_days,
        "auto_archive": active.auto_archive,
        "hard_delete_mode": active.hard_delete_mode,
    }
