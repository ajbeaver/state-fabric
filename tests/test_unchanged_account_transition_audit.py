"""Diagnostic: global commits can advance while an account value stays unchanged."""

from pathlib import Path

import pytest

from modules.canonical_history import (
    canonical_source,
    current_commit,
    current_object,
    latest_object_at_or_before,
    object_at_height,
    object_at_root,
)
from modules.custody import request_custody
from modules.merkle import commit_state
from modules.peers import initialize_peers, mutate_peer_state
from modules.retention import protection_for_object
from modules.storage import (
    build_state_package,
    create_offer,
    get_object_id,
    parse_state_package,
    verify_state_package,
)


def test_unchanged_alice_across_other_account_commits(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    initialize_peers(7)
    addresses = sorted(path.name for path in Path("data/peers").iterdir())
    alice, others = addresses[0], addresses[1:4]
    custodians = addresses[1:6]

    root_n = f"0x{commit_state().hex()}"
    manifest_x = create_offer(alice)
    x = manifest_x["object_id"]
    for custodian in custodians:
        request_custody(alice, custodian, x)
    package_x = build_state_package(alice)
    state_x = parse_state_package(package_x)
    assert current_commit()["height"] == 0
    assert object_at_height(alice, 0) == x
    assert object_at_root(alice, root_n) == x
    assert latest_object_at_or_before(alice, 0) == x
    with pytest.raises(ValueError, match="at or before height -1"):
        latest_object_at_or_before(alice, -1)
    assert verify_state_package(package_x)
    print(f"N height=0 root={root_n} Alice balance={state_x['balance']} nonce={state_x['nonce']} X={x} custody=5/5")

    for height, other in enumerate(others, start=1):
        nonce_path = Path("data/peers") / other / "cache" / "self" / "nonce"
        mutate_peer_state(other, nonce=int(nonce_path.read_text().strip()) + 1)
        root = f"0x{commit_state().hex()}"
        current_package = build_state_package(alice)
        current_state = parse_state_package(current_package)
        assert (current_state["balance"], current_state["nonce"]) == (
            state_x["balance"], state_x["nonce"]
        )
        assert root != root_n
        assert current_state["state_root"] == root
        if height == 1:
            assert current_state["proof"] != state_x["proof"]
        assert get_object_id(current_package) != x
        assert verify_state_package(current_package)
        assert not verify_state_package(package_x)
        assert verify_state_package(package_x, canonical_height=0)
        assert current_object(alice) == x
        assert latest_object_at_or_before(alice, height) == x
        with pytest.raises(ValueError, match=f"No object for .* at height {height}"):
            object_at_height(alice, height)
        with pytest.raises(ValueError, match=f"No object for .* at height {height}"):
            object_at_root(alice, root)
        assert [version["sequence"] for version in canonical_source().versions(alice)] == [0]
        assert protection_for_object(x).role == "current"
        print(
            f"N+{height} height={height} root={root} Alice value=unchanged "
            f"current_object=X exact_root_object=missing X_current_verify=no X_height0_verify=yes "
            f"retention_X=current would_be_object={get_object_id(current_package)}"
        )

    alice_nonce_path = Path("data/peers") / alice / "cache" / "self" / "nonce"
    mutate_peer_state(alice, nonce=int(alice_nonce_path.read_text().strip()) + 1)
    root_next = f"0x{commit_state().hex()}"
    y = create_offer(alice)["object_id"]
    for custodian in custodians:
        request_custody(alice, custodian, y)
    assert current_commit()["height"] == 4
    assert current_object(alice) == y
    assert [latest_object_at_or_before(alice, height) for height in range(5)] == [x, x, x, x, y]
    assert object_at_root(alice, root_next) == y
    assert [version["sequence"] for version in canonical_source().versions(alice)] == [0, 4]
    assert protection_for_object(x).role == "fallback"
    assert protection_for_object(y).role == "current"
    assert verify_state_package(package_x, canonical_height=0)
    print(f"N+4 height=4 root={root_next} Alice nonce={state_x['nonce'] + 1} Y={y} custody=5/5")
    print("Alice registered heights=[0, 4]; X=fallback; Y=current; no Alice offers at heights 1-3")
