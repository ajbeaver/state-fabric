from pathlib import Path
import json

from modules.canonical_history import (
    current_commit,
    current_object,
    object_at_height,
    object_at_root,
)
from modules.custody import get_valid_active_fragments, reconstruct_from_network, request_custody
from modules.merkle import commit_state
from modules.peers import initialize_peers, mutate_peer_state
from modules.storage import create_offer, reconstruct_offer, verify_state_package


def test_mutation_creates_distinct_root_and_preserves_old_offer(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    initialize_peers(3)
    address = sorted(path.name for path in Path("data/peers").iterdir())[0]

    root_n = commit_state()
    object_x = create_offer(address)["object_id"]
    offers_dir = Path("data/peers") / address / "offers"
    old_dir = offers_dir / object_x

    nonce_path = Path("data/peers") / address / "cache" / "self" / "nonce"
    mutate_peer_state(address, nonce=int(nonce_path.read_text().strip()) + 1)
    root_next = commit_state()
    object_y = create_offer(address)["object_id"]
    new_dir = offers_dir / object_y

    assert root_n != root_next
    assert object_x != object_y
    assert old_dir.is_dir()
    assert new_dir.is_dir()
    assert verify_state_package(reconstruct_offer(new_dir))


def test_canonical_height_selects_y_even_when_x_has_better_custody(network):
    alice = network.publisher
    object_x = network.object_id
    root_n = network.manifest["state_root"]
    assert current_commit()["height"] == 0
    assert object_at_root(alice, root_n) == object_x
    assert object_at_height(alice, 0) == object_x

    nonce_path = network.peers_dir / alice / "cache" / "self" / "nonce"
    mutate_peer_state(alice, nonce=int(nonce_path.read_text().strip()) + 1)
    root_next = f"0x{commit_state().hex()}"
    manifest_y = create_offer(alice)
    object_y = manifest_y["object_id"]
    for custodian in network.custodians:
        request_custody(alice, custodian, object_y)

    assert current_commit()["height"] == 1
    assert root_n != root_next
    assert object_x != object_y
    assert object_at_root(alice, root_next) == object_y
    assert object_at_height(alice, 1) == object_y
    assert current_object(alice) == object_y
    assert all(network.object_dir(peer).is_dir() for peer in network.custodians)
    assert all((network.peers_dir / peer / "data" / object_y).is_dir()
               for peer in network.custodians)
    assert verify_state_package(reconstruct_from_network(
        object_x, network.custodians[0], canonical_height=0,
    ), canonical_height=0)
    assert verify_state_package(reconstruct_from_network(
        object_y, network.custodians[0],
    ))

    for custodian in network.custodians:
        path = network.peers_dir / custodian / "data" / object_y / "custody.json"
        custody = json.loads(path.read_text())
        custody["0"]["expires_at"] = "2000-01-01T00:00:00Z"
        path.write_text(json.dumps(custody) + "\n")
    x_custody = json.loads((network.object_dir(network.custodians[0]) /
                            "custody.json").read_text())
    y_custody = json.loads((network.peers_dir / network.custodians[0] /
                            "data" / object_y / "custody.json").read_text())
    assert len(get_valid_active_fragments(object_x, network.manifest,
                                          x_custody, network.peers_dir)) == 5
    assert len(get_valid_active_fragments(object_y, manifest_y,
                                          y_custody, network.peers_dir)) == 4
    assert current_object(alice) == object_y
