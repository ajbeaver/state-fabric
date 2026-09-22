"""State values, retained authenticated nodes, and derived witness invariants."""

import json
from pathlib import Path

import pytest

from modules.canonical_history import current_commit, current_object
from modules.commitment import ToyMerkleBackend
from modules.content_store import content_path
from modules.merkle import commit_state
from modules.peers import initialize_peers, mutate_peer_state
from modules.state_values import (
    account_value_bytes,
    account_state_key,
    load_state_value,
    read_account_value,
    state_value_id,
    store_state_value,
)
from modules.storage import create_offer


def test_identical_values_share_id_but_witnesses_bind_distinct_keys(tmp_path):
    reference_dir = tmp_path / "reference"
    backend = ToyMerkleBackend(reference_dir)
    alice_key = b"alice"
    bob_key = b"bob"
    value = account_value_bytes(balance=42, nonce=7)

    alice_value_id = store_state_value(value, reference_dir)
    bob_value_id = store_state_value(value, reference_dir)
    assert alice_value_id == bob_value_id == state_value_id(value)
    assert len(list((reference_dir / "state_values").glob("*.bin"))) == 1

    root = backend.commit([(alice_key, value), (bob_key, value)])
    alice_witness = backend.build_witness(root, alice_key, value)
    bob_witness = backend.build_witness(root, bob_key, value)
    assert backend.verify_witness(alice_key, value, alice_witness, root)
    assert backend.verify_witness(bob_key, value, bob_witness, root)
    assert not backend.verify_witness(bob_key, value, alice_witness, root)
    assert not backend.verify_witness(alice_key, value, bob_witness, root)
    assert alice_witness["state_value_id"] == bob_witness["state_value_id"]
    assert alice_witness["siblings"] != bob_witness["siblings"]


def test_stable_values_and_regenerable_witnesses(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    initialize_peers(7)
    peers = sorted(Path("data/peers").iterdir(), key=lambda path: path.name.lower())
    alice, bob = peers[:2]
    key = account_state_key(alice.name)
    backend = ToyMerkleBackend()

    root_n = commit_state()
    value_n = read_account_value(alice)
    value_id = state_value_id(value_n)
    assert load_state_value(value_id) == value_n
    witness_n = backend.build_witness(root_n, key, value_n)
    assert backend.verify_witness(key, value_n, witness_n, root_n)
    last_key = account_state_key(peers[-1].name)
    last_value = read_account_value(peers[-1])
    assert backend.verify_witness(
        last_key, last_value,
        backend.build_witness(root_n, last_key, last_value), root_n,
    )

    bob_nonce = bob / "cache" / "self" / "nonce"
    mutate_peer_state(bob.name, nonce=int(bob_nonce.read_text().strip()) + 1)
    root_next = commit_state()
    assert root_next != root_n
    assert read_account_value(alice) == value_n
    assert state_value_id(read_account_value(alice)) == value_id

    # Neither generated witness nor legacy proof cache is needed for regeneration.
    witness_next = backend.build_witness(root_next, key, value_n)
    expected_witness = json.dumps(witness_next, sort_keys=True)
    del witness_next
    del witness_n
    for peer in peers:
        (peer / "cache" / "self" / "proof.json").unlink()
    retained_value = load_state_value(value_id)
    witness = backend.build_witness(root_next, key, retained_value)
    assert json.dumps(witness, sort_keys=True) == expected_witness
    assert backend.verify_witness(key, retained_value, witness, root_next)
    assert backend.verify_witness(
        key, retained_value,
        backend.build_witness(root_n, key, retained_value), root_n,
    )
    assert not backend.verify_witness(key, retained_value, witness, root_n)
    assert not backend.verify_witness(key, retained_value + b"tampered", witness, root_next)
    assert not backend.verify_witness(account_state_key(bob.name), retained_value,
                                      witness, root_next)
    bob_value = read_account_value(bob)
    bob_witness = backend.build_witness(root_next, account_state_key(bob.name), bob_value)
    assert not backend.verify_witness(key, retained_value, bob_witness, root_next)

    sibling_path = content_path(backend.nodes_dir, witness["siblings"][0]["hash"])
    sibling_bytes = sibling_path.read_bytes()
    sibling_path.unlink()
    with pytest.raises(FileNotFoundError):
        backend.build_witness(root_next, key, retained_value)
    sibling_path.write_bytes(sibling_bytes + b"tampered")
    with pytest.raises(ValueError, match="Content hash mismatch"):
        backend.build_witness(root_next, key, retained_value)
    sibling_path.write_bytes(sibling_bytes)
    assert backend.verify_witness(
        key, retained_value, backend.build_witness(root_next, key, retained_value), root_next,
    )

    alice_nonce = alice / "cache" / "self" / "nonce"
    mutate_peer_state(alice.name, nonce=int(alice_nonce.read_text().strip()) + 1)
    changed_root = commit_state()
    changed_value = read_account_value(alice)
    assert changed_root != root_next
    assert state_value_id(changed_value) != value_id
    assert backend.verify_witness(
        key, changed_value, backend.build_witness(changed_root, key, changed_value), changed_root,
    )


def test_sparse_legacy_offers_still_resolve_without_new_witness_objects(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    initialize_peers(3)
    alice, bob = sorted(path.name for path in Path("data/peers").iterdir())[:2]
    commit_state()
    x = create_offer(alice)["object_id"]
    nonce_path = Path("data/peers") / bob / "cache" / "self" / "nonce"
    mutate_peer_state(bob, nonce=int(nonce_path.read_text().strip()) + 1)
    commit_state()
    assert current_commit()["height"] == 1
    assert current_object(alice) == x
