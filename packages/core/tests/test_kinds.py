"""The kind registry is an API surface, so it is checked like one."""

from __future__ import annotations

from framestack_core.kinds import (
    REGISTRY,
    CarrierType,
    families,
    family_of,
    is_registered,
    lookup,
)


def test_every_entry_is_reachable_under_its_own_name() -> None:
    for name, kind in REGISTRY.items():
        assert kind.name == name
        assert lookup(name) is kind


def test_an_unregistered_kind_is_simply_unknown() -> None:
    """No fallback, no inference. An unknown kind must reach the gate as unknown (§5.6)."""
    assert lookup("fastapi.invented") is None
    assert not is_registered("fastapi.invented")


def test_only_groups_and_artifacts_may_stand_at_the_top_level() -> None:
    """The Q4 decision, held in the registry rather than only in prose -- and its amendment.

    Q4 is about the nodes projected *from code*: a subsystem is a group whether it holds one
    carrier or fifty. An artifact node is beside those, not one of them — it has no members,
    nothing claims it, and it could not be a group without inventing a manifest for a file
    that declares nothing (Q10, §5.7).
    """
    for kind in REGISTRY.values():
        if kind.top_level:
            assert kind.carriers in ({CarrierType.GROUP}, {CarrierType.FILE})


def test_only_an_artifact_kind_names_the_paths_that_carry_it() -> None:
    """Discovery is a registry entry. There is no "familiar filename" rule anywhere."""
    for kind in REGISTRY.values():
        if kind.artifact:
            assert kind.carriers == {CarrierType.FILE}
        if CarrierType.FILE in kind.carriers:
            assert kind.artifact, f"{kind.name} is file-carried but names no path"


def test_every_kind_declares_an_observable_check() -> None:
    """A kind with no check could only ever be green on parseability -- the I-5 failure."""
    for kind in REGISTRY.values():
        assert kind.check
        assert kind.description


def test_every_kind_belongs_to_a_family_the_registry_reports() -> None:
    """The library groups by family, so a family the registry does not report hides kinds.

    This is the P19 failure written as a test. The first version of that panel had its
    families spelled out in the front end, and two of them -- `db` and `vector` -- were
    simply not on the list, so four registered kinds appeared nowhere at all. A library
    exists to say what can be built; one that can silently omit a kind is worse than none.
    """
    for kind in REGISTRY:
        assert family_of(kind) in families(), f"{kind} is in no reported family"


def test_no_family_is_reported_that_no_kind_belongs_to() -> None:
    """Derived, never listed: a family exists **because a kind named it**."""
    named = {family_of(kind) for kind in REGISTRY}

    assert set(families()) == named


def test_the_families_come_back_in_the_registry_s_own_order() -> None:
    """Grouped by technology and ordered by the phase that added each one.

    Alphabetical would put `db` above `fastapi`, which tells a reader nothing; the order the
    registry is written in is the order the technologies arrived, and it is the more useful
    of the two. Asserted because it is a promise the payload makes to the panel.
    """
    first_seen = list(dict.fromkeys(family_of(kind) for kind in REGISTRY))

    assert list(families()) == first_seen
