import json
import shutil

import pytest

from modules.canonical_history import current_object
from modules.custody import reconstruct_from_network, repair_network, request_custody
from modules.merkle import commit_state
from modules.peers import mutate_peer_state
from modules.retention import (
    independently_recoverable,
    latest_safely_protected_predecessor,
    meets_protection_target,
    object_health,
    protection_for_object,
    protected_window_healthy,
    repair_required,
)
from modules.storage import create_offer


def publish_next(network):
    alice = network.publisher
    nonce_path = network.peers_dir / alice / "cache" / "self" / "nonce"
    mutate_peer_state(alice, nonce=int(nonce_path.read_text().strip()) + 1)
    commit_state()
    return create_offer(alice)["object_id"]


def test_protection_target_separates_reconstruction_from_full_custody(network):
    x = network.object_id
    y = publish_next(network)
    assert current_object(network.publisher) == y
    assert not independently_recoverable(y)
    assert not meets_protection_target(y)

    request_custody(network.publisher, network.custodians[0], y)
    assert object_health(y)[0] == 1
    assert not independently_recoverable(y)
    assert not meets_protection_target(y)
    assert protection_for_object(x).protected
    assert repair_required(y)

    request_custody(network.publisher, network.custodians[1], y)
    assert object_health(y)[0] == 2
    assert independently_recoverable(y)
    assert not meets_protection_target(y)
    assert reconstruct_from_network(y, network.custodians[0])
    assert protection_for_object(x).protected

    for custodian in network.custodians[2:]:
        request_custody(network.publisher, custodian, y)
    assert meets_protection_target(y)
    assert not repair_required(y)


@pytest.mark.parametrize("damage", ["corrupt", "missing"])
def test_multiple_incomplete_advances_keep_last_safe_predecessor(network, damage):
    x = network.object_id
    y = publish_next(network)
    request_custody(network.publisher, network.custodians[0], y)
    z = publish_next(network)
    for custodian in network.custodians[:2]:
        request_custody(network.publisher, custodian, z)

    assert current_object(network.publisher) == z
    assert independently_recoverable(z)
    assert not meets_protection_target(z)
    assert protection_for_object(x).protected
    assert latest_safely_protected_predecessor(network.publisher)["object_id"] == x

    fragment = network.peers_dir / network.custodians[0] / "data" / y / "000.bin"
    if damage == "corrupt":
        fragment.write_bytes(b"corrupt")
    else:
        fragment.unlink()
    custody_path = fragment.parent / "custody.json"
    assert len(json.loads(custody_path.read_text())) == 1
    assert object_health(y)[0] == 0
    assert not meets_protection_target(y)
    assert protection_for_object(x).protected

    for custodian in network.custodians[2:]:
        request_custody(network.publisher, custodian, z)
    assert meets_protection_target(z)
    assert protection_for_object(x).protected
    assert protection_for_object(y).role == "fallback"
    assert repair_required(y)
    assert latest_safely_protected_predecessor(network.publisher)["object_id"] == x

    original = network.peers_dir / network.publisher / "offers" / y / "fragments" / "000.bin"
    shutil.copyfile(original, fragment)
    for custodian in network.custodians[1:]:
        request_custody(network.publisher, custodian, y)
    assert meets_protection_target(y)
    assert protected_window_healthy(
        [
            {"object_id": x},
            {"object_id": y},
            {"object_id": z},
        ],
        meets_protection_target,
    )
    assert not protection_for_object(x).protected


def test_publisher_loss_and_failed_repair_preserve_health_truth(network):
    x = network.object_id
    y = publish_next(network)
    first = network.custodians[0]
    replacement = network.spare
    request_custody(network.publisher, first, y)
    shutil.move(
        str(network.peers_dir / network.publisher),
        str(network.peers_dir.parent / "offline_publisher"),
    )

    assert current_object(network.publisher) == y
    assert object_health(y)[0] == 1
    assert not independently_recoverable(y)
    assert not meets_protection_target(y)
    assert meets_protection_target(x)
    assert protection_for_object(x).protected
    assert repair_required(y)

    custody_path = network.peers_dir / first / "data" / y / "custody.json"
    before = custody_path.read_text()
    with pytest.raises(ValueError, match="Not enough valid active fragments"):
        repair_network(y, first, replacement)
    assert custody_path.read_text() == before
    assert not (network.peers_dir / replacement / "data" / y).exists()
    assert object_health(y)[0] == 1
    assert not meets_protection_target(y)
    assert protection_for_object(x).protected
