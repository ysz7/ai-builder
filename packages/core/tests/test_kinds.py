"""The kind registry is an API surface, so it is checked like one."""

from __future__ import annotations

from aibuilder_core.kinds import REGISTRY, CarrierType, is_registered, lookup


def test_every_entry_is_reachable_under_its_own_name() -> None:
    for name, kind in REGISTRY.items():
        assert kind.name == name
        assert lookup(name) is kind


def test_an_unregistered_kind_is_simply_unknown() -> None:
    """No fallback, no inference. An unknown kind must reach the gate as unknown (§5.6)."""
    assert lookup("fastapi.invented") is None
    assert not is_registered("fastapi.invented")


def test_only_groups_may_stand_at_the_top_level() -> None:
    """The Q4 decision, held in the registry rather than only in prose."""
    for kind in REGISTRY.values():
        if kind.top_level:
            assert kind.carriers == {CarrierType.GROUP}


def test_every_kind_declares_an_observable_check() -> None:
    """A kind with no check could only ever be green on parseability -- the I-5 failure."""
    for kind in REGISTRY.values():
        assert kind.check
        assert kind.description
