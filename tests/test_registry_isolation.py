from clonway_cockpit.registry import (
    CapabilitySpec,
    get_capability,
    register_capability,
)


def test_registered_capability_can_leak_without_registry_guard():
    register_capability(
        CapabilitySpec(
            key="phase-one-leak",
            shelf="A",
            title="Leak probe",
            summary="Registered without manual cleanup",
            equivalent_cli="x leak",
        )
    )

    assert get_capability("phase-one-leak") is not None


def test_next_test_sees_registry_without_previous_test_leak():
    assert get_capability("phase-one-leak") is None
