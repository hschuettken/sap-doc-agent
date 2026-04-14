"""Tests for migration database CRUD — validates module structure and function signatures."""

from __future__ import annotations

import inspect

from sap_doc_agent.migration import db as migration_db


def test_db_module_has_project_functions():
    assert callable(migration_db.create_project)
    assert callable(migration_db.get_project)
    assert callable(migration_db.list_projects)
    assert callable(migration_db.update_project_status)
    assert callable(migration_db.delete_project)


def test_db_module_has_intent_card_functions():
    assert callable(migration_db.upsert_intent_card)
    assert callable(migration_db.get_intent_card)
    assert callable(migration_db.list_intent_cards)
    assert callable(migration_db.review_intent_card)


def test_db_module_has_classification_functions():
    assert callable(migration_db.upsert_classification)
    assert callable(migration_db.list_classifications)
    assert callable(migration_db.review_classification)


def test_db_module_has_target_view_functions():
    assert callable(migration_db.upsert_target_view)
    assert callable(migration_db.list_target_views)


def test_all_db_functions_are_async():
    """All public functions in migration/db.py should be async."""
    for name, fn in inspect.getmembers(migration_db, inspect.isfunction):
        if name.startswith("_"):
            continue
        assert inspect.iscoroutinefunction(fn), f"{name} should be async"


def test_migration_002_revision():
    import importlib

    m = importlib.import_module("migrations.versions.002_migration_accelerator")
    assert m.revision == "002"
    assert m.down_revision == "001"
