"""Deterministic class -> role mapping."""

from backend.config import role_for_class


def test_object_to_role_mapping():
    assert role_for_class("book") == "barrier"
    assert role_for_class("bottle") == "defense_tower"
    assert role_for_class("cup") == "defense_tower"
    assert role_for_class("box") == "heavy_fortification"
    assert role_for_class("pencil holder") == "support_tower"
    assert role_for_class("unknown object") == "custom"
    assert role_for_class("Wine Glass") == "defense_tower"
