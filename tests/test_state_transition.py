from pathlib import Path

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
