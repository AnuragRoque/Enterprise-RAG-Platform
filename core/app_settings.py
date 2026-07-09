"""Read/write helpers for the app_settings key-value table.

These are the global platform toggles the admin panel exposes. Values are JSON;
unknown keys are rejected by the admin API, and reads fall back to the defaults
below so the platform behaves sensibly before the first save.
"""
from typing import Any, Dict

from sqlalchemy.orm import Session

from core.models import AppSetting

# Single source of truth for which toggles exist and how the platform behaves
# before an admin ever touches them.
DEFAULT_SETTINGS: Dict[str, Any] = {
    # Merge the shared (company-scope) knowledge base into every project's answers.
    "global_project_enabled": True,
    # Let every project's retrieval also search all other projects' chunks.
    "cross_project_linking": False,
    # Reject browser calls to the chat API from origins not on the whitelist.
    "domain_whitelist_enforced": False,
}


def get_setting(db: Session, key: str) -> Any:
    row = db.query(AppSetting).filter(AppSetting.key == key).first()
    if row is not None:
        return row.value
    return DEFAULT_SETTINGS.get(key)


def get_all_settings(db: Session) -> Dict[str, Any]:
    merged = dict(DEFAULT_SETTINGS)
    for row in db.query(AppSetting).all():
        if row.key in merged:
            merged[row.key] = row.value
    return merged


def set_setting(db: Session, key: str, value: Any) -> None:
    if key not in DEFAULT_SETTINGS:
        raise ValueError(f"Unknown setting '{key}'")
    row = db.query(AppSetting).filter(AppSetting.key == key).first()
    if row is None:
        db.add(AppSetting(key=key, value=value))
    else:
        row.value = value
    db.commit()
