"""Mutation catalog — known safe and unsafe mutations per platform and object type."""

from __future__ import annotations

MUTATION_CATALOG: dict[str, dict[str, list[dict]]] = {
    "dsp": {
        "relational_view": [
            {"name": "add_field", "safe": True, "description": "Add a new field to the view"},
            {"name": "remove_field", "safe": True, "description": "Remove an existing field from the view"},
            {"name": "rename_field", "safe": True, "description": "Rename a field in the view"},
            {"name": "change_join", "safe": True, "description": "Modify an existing join condition"},
            {"name": "add_join", "safe": True, "description": "Add a new join to the view"},
            {"name": "change_calculation", "safe": True, "description": "Modify a calculated field expression"},
            {"name": "add_parameter", "safe": True, "description": "Add an input parameter to the view"},
            {"name": "change_label", "safe": True, "description": "Change the display label of a field"},
            {"name": "change_persistence", "safe": False, "description": "Change the persistence mode of the view"},
            {"name": "drop_table", "safe": False, "description": "Drop the underlying table (destructive)"},
        ],
        "fact_view": [
            {"name": "add_field", "safe": True, "description": "Add a new measure or attribute field"},
            {"name": "remove_field", "safe": True, "description": "Remove a field from the fact view"},
            {"name": "add_association", "safe": True, "description": "Add an association to another entity"},
            {
                "name": "change_aggregation",
                "safe": True,
                "description": "Change the aggregation function for a measure",
            },
            {"name": "drop_table", "safe": False, "description": "Drop the underlying table (destructive)"},
        ],
        "dimension_view": [
            {"name": "add_field", "safe": True, "description": "Add a new attribute field"},
            {"name": "remove_field", "safe": True, "description": "Remove an attribute field"},
            {"name": "add_hierarchy", "safe": True, "description": "Add a hierarchy definition"},
            {"name": "change_text", "safe": True, "description": "Change the text/description of the dimension"},
            {"name": "drop_table", "safe": False, "description": "Drop the underlying table (destructive)"},
        ],
    },
    "sac": {
        "story": [
            {"name": "add_page", "safe": True, "description": "Add a new page to the story"},
            {"name": "remove_page", "safe": True, "description": "Remove a page from the story"},
            {"name": "add_widget", "safe": True, "description": "Add a chart or table widget"},
            {"name": "remove_widget", "safe": True, "description": "Remove an existing widget"},
            {"name": "change_binding", "safe": True, "description": "Change the data binding of a widget"},
            {"name": "change_filter", "safe": True, "description": "Modify a story or page filter"},
            {"name": "change_style", "safe": True, "description": "Change visual styling of a widget or page"},
            {"name": "delete_story", "safe": False, "description": "Delete the entire story (destructive)"},
        ],
        "app": [
            {"name": "add_page", "safe": True, "description": "Add a new page to the app"},
            {"name": "add_widget", "safe": True, "description": "Add a widget to the app"},
            {"name": "add_script", "safe": True, "description": "Add a script/event handler"},
            {"name": "change_navigation", "safe": True, "description": "Modify navigation structure"},
            {"name": "delete_app", "safe": False, "description": "Delete the entire app (destructive)"},
        ],
    },
}


def get_mutations(platform: str, object_type: str) -> list[dict]:
    """Return the list of known mutations for a platform/object_type pair.

    Returns an empty list if the platform or object_type is not catalogued.
    """
    return MUTATION_CATALOG.get(platform, {}).get(object_type, [])


def is_safe_mutation(platform: str, object_type: str, mutation_name: str) -> bool:
    """Return True if the named mutation is marked safe for the given platform/object_type.

    Returns False for unknown platforms, object types, or mutation names.
    """
    mutations = get_mutations(platform, object_type)
    for m in mutations:
        if m["name"] == mutation_name:
            return m["safe"]
    return False
