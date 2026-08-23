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
