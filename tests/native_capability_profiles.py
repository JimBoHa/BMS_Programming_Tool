"""Independent current/default and explicit legacy capability contract checks."""

import copy


def capability_profiles(service, request):
    current = service.capabilities(request)
    legacy = service.capabilities(
        {**request, "capability_profile": "native-backup-operation-capabilities/11"}
    )
    assert current["capability_profile"] == "native-backup-operation-capabilities/12"
    assert len(current["operations"]) == 24
    assert len({row["id"] for row in current["operations"]}) == 24
    assert legacy["capability_profile"] == "native-backup-operation-capabilities/11"
    assert len(legacy["operations"]) == 22
    assert len({row["id"] for row in legacy["operations"]}) == 22
    assert (
        service.capabilities(
            {**request, "capability_profile": "native-backup-operation-capabilities/12"}
        )
        == current
    )

    projected = copy.deepcopy(current)
    projected["capability_profile"] = "native-backup-operation-capabilities/11"
    additions = {"matching-connection-copy", "effective-connection-compile"}
    assert additions <= {row["id"] for row in projected["operations"]}
    projected["operations"] = [row for row in projected["operations"] if row["id"] not in additions]
    next(row for row in projected["operations"] if row["id"] == "general-logic")["basis"] = (
        "Installed native compilers cover typed identity, existing Real/Boolean defaults "
        "and a scoped existing-wire source archive copy, not arbitrary logic generation."
    )
    for key in (
        "archive_matching_connection",
        "archive_matching_connection_error",
        "effective_matching_connection",
        "effective_matching_connection_error",
    ):
        assert key not in legacy["qualification"]
        del projected["qualification"][key]
    assert projected == legacy
    return legacy, current
