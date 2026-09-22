import argparse
import json
import shutil
from pathlib import Path

from modules.custody import (
    get_valid_active_fragments,
    parse_time,
    renew_custody,
    repair_network,
    request_custody,
    reconstruct_from_network,
    utc_now,
)
from modules.canonical_history import (
    current_commit,
    current_object,
    object_at_height,
    object_at_root,
)
from modules.commitment import ToyMerkleBackend
from modules.content_store import content_path
from modules.merkle import commit_state, load_peer_dirs, load_state_root, verify_peer
from modules.peers import initialize_peers, mutate_peer_state
from modules.retention import (
    independently_recoverable,
    latest_safely_protected_predecessor,
    meets_protection_target,
    object_health,
    protection_for_object,
    repair_required,
)
from modules.storage import create_offer, get_object_id, reconstruct_offer, verify_state_package
from modules.state_values import (
    account_state_key,
    load_state_value,
    read_account_value,
    state_value_id,
)


PEERS_DIR = Path("data/peers")
EXPIRED_AT = "2000-01-01T00:00:00Z"


def require(condition: bool, message: str) -> None:
    if not condition:
        raise RuntimeError(message)


def initialize(count: int) -> int:
    data_dir = Path("data")
    if data_dir.exists():
        shutil.rmtree(data_dir)
    return initialize_peers(count)


def load_custody(peer: str, object_id: str) -> dict:
    path = PEERS_DIR / peer / "data" / object_id / "custody.json"
    return json.loads(path.read_text(encoding="utf-8"))


def active_claims(custody: dict) -> dict:
    now = utc_now()
    return {
        key: claim for key, claim in custody.items()
        if claim["status"] == "leased" and parse_time(claim["expires_at"]) > now
    }


def show_fragments(custody: dict) -> None:
    now = utc_now()
    for index, claim in sorted(custody.items(), key=lambda item: int(item[0])):
        status = "active" if claim["status"] == "leased" and parse_time(claim["expires_at"]) > now else "expired"
        print(f"  fragment {int(index):03d} -> {claim['custodian']} [{status}]")


def show_package(package: bytes, object_id: str, canonical_height: int | None = None) -> None:
    actual_id = get_object_id(package)
    canonical = verify_state_package(package, canonical_height=canonical_height)
    require(actual_id == object_id and canonical, "Reconstructed package failed verification")
    print(f"  Reconstructed bytes: {len(package)}")
    print(f"  Reconstructed object ID: {actual_id}")
    print("  Canonical verification: passed")


def expire_fragment_claim(object_id: str, index: int = 0) -> None:
    paths = list(PEERS_DIR.glob(f"*/data/{object_id}/custody.json"))
    require(bool(paths), f"No custody views for {object_id}")
    for path in paths:
        view = json.loads(path.read_text(encoding="utf-8"))
        view[str(index)]["expires_at"] = EXPIRED_AT
        path.write_text(json.dumps(view, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def verify_current() -> None:
    peers = load_peer_dirs()
    root = load_state_root()
    canonical = current_commit()
    require(canonical["state_root"] == f"0x{root.hex()}",
            "Trusted root and canonical history disagree")
    print(f"Canonical height: {canonical['height']}")
    print(f"Trusted root: 0x{root.hex()}")
    for peer in peers:
        require(verify_peer(peer.name), f"Peer verification failed: {peer.name}")
        print(f"  peer {peer.name}: proof valid")
    print(f"Peer proofs: {len(peers)}/{len(peers)} verified")

    objects = 0
    for peer in peers:
        offers_dir = peer / "offers"
        if not offers_dir.exists():
            continue
        for offer_dir in sorted(path for path in offers_dir.iterdir() if path.is_dir()):
            manifest = json.loads((offer_dir / "manifest.json").read_text(encoding="utf-8"))
            require(manifest["object_id"] == offer_dir.name, f"Object ID mismatch: {offer_dir}")
            if manifest["state_root"] == f"0x{root.hex()}":
                objects += 1
    print(f"Current offers: {objects}")

    network_objects: dict[str, list[str]] = {}
    for peer in peers:
        data_dir = peer / "data"
        if not data_dir.exists():
            continue
        for object_dir in data_dir.iterdir():
            if (object_dir / "manifest.json").is_file() and (object_dir / "custody.json").is_file():
                network_objects.setdefault(object_dir.name, []).append(peer.name)
    for object_id, custodians in sorted(network_objects.items()):
        # Pick a custody view for this fixed object ID; canonical history selects the version.
        custodian = max(
            custodians,
            key=lambda peer: len(active_claims(load_custody(peer, object_id))),
        )
        object_dir = PEERS_DIR / custodian / "data" / object_id
        manifest = json.loads((object_dir / "manifest.json").read_text(encoding="utf-8"))
        if manifest["state_root"] != f"0x{root.hex()}":
            continue
        require(current_object(manifest["address"]) == object_id,
                f"Canonical object mapping disagrees: {object_id}")
        custody = load_custody(custodian, object_id)
        valid = get_valid_active_fragments(object_id, manifest, custody, PEERS_DIR)
        require(len(valid) >= manifest["encoding"]["required_fragments"],
                f"Insufficient active fragments: {object_id}")
        package = reconstruct_from_network(object_id, custodian)
        require(get_object_id(package) == object_id and verify_state_package(package),
                f"Distributed object failed verification: {object_id}")
        print(f"Distributed object {object_id}: {len(valid)}/{manifest['encoding']['total_fragments']} active fragments, canonical verification passed")
        print(f"  Current by height {canonical['height']}: {object_id}")
        show_fragments(custody)
    current_network_objects = sum(
        json.loads((PEERS_DIR / custodians[0] / "data" / object_id / "manifest.json").read_text(encoding="utf-8"))["state_root"] == f"0x{root.hex()}"
        for object_id, custodians in network_objects.items()
    )
    print(f"Current distributed objects: {current_network_objects}")
    print("  Historical objects are excluded from current health")
    print("Current state verification: passed")


def run_experiment() -> None:
    print("[1/25] Initializing peers", flush=True)
    require(initialize(7) == 7, "Expected seven peers")
    addresses = [path.name for path in load_peer_dirs()]
    publisher, custodians, spare = addresses[0], addresses[1:6], addresses[6]
    for index, address in enumerate(addresses):
        role = "publisher" if address == publisher else "spare" if address == spare else "custodian"
        print(f"  peer {index}: {address} ({role})")

    print("[2/25] Committing Alice's original state", flush=True)
    root_n = commit_state()
    height_n = current_commit()["height"]
    require(height_n == 0, "Initial canonical height must be zero")
    print(f"  Height {height_n}; root N: 0x{root_n.hex()}")
    require(all(verify_peer(address) for address in addresses), "Initial peer proof failed")
    print(f"  Proofs verified: {len(addresses)}/{len(addresses)}")

    print("[3/25] Creating Alice object X", flush=True)
    offer_x = create_offer(publisher, encoding_type="erasure")
    object_x = offer_x["object_id"]
    offers_dir = PEERS_DIR / publisher / "offers"
    old_dir = offers_dir / object_x
    require(old_dir.is_dir(), "Object X offer is missing")
    require(offer_x["canonical_height"] == height_n, "X has wrong canonical height")
    require(object_at_root(publisher, f"0x{root_n.hex()}") == object_x,
            "Root N does not resolve to X")
    print(f"  Publisher: {publisher}")
    print(f"  Object X: {object_x}")
    print(f"  Height: {offer_x['canonical_height']}; root: {offer_x['state_root']}")
    print(f"  Encoding: {offer_x['encoding']['required_fragments']}-of-{offer_x['encoding']['total_fragments']}")

    print("[4/25] Distributing X before mutation", flush=True)
    for custodian in custodians:
        result = request_custody(publisher, custodian, object_x)
        print(f"  X fragment {result['fragment_index']:03d} ({result['fragment_size']} bytes) -> {custodian}")
    custody_x = load_custody(custodians[0], object_x)
    valid_x = get_valid_active_fragments(object_x, offer_x, custody_x, PEERS_DIR)
    require(len(valid_x) == 5, "X does not have five valid active fragments")
    require(all(load_custody(peer, object_x) == custody_x for peer in custodians),
            "X custody views differ")
    print("  X custody: 5/5 valid active fragments")

    print("[5/25] Reconstructing and verifying X at root N", flush=True)
    package_x = reconstruct_from_network(object_x, custodians[0])
    show_package(package_x, object_x)
    print(f"  Canonical height: {height_n}; trusted root: 0x{root_n.hex()}")
    print("  X healthy before mutation: yes")

    print("[6/25] Mutating Alice's local state", flush=True)
    nonce_path = PEERS_DIR / publisher / "cache" / "self" / "nonce"
    old_nonce = int(nonce_path.read_text(encoding="utf-8").strip())
    new_nonce = old_nonce + 1
    mutate_peer_state(publisher, nonce=new_nonce)
    require(int(nonce_path.read_text(encoding="utf-8").strip()) == new_nonce,
            "Nonce mutation was not stored")
    print(f"  Alice nonce: {old_nonce} -> {new_nonce}")

    print("[7/25] Committing Alice's mutated state", flush=True)
    root_next = commit_state()
    height_next = current_commit()["height"]
    require(height_next == height_n + 1, "Canonical height did not advance")
    require(root_n != root_next, "Mutation did not change the canonical root")
    print(f"  Height {height_next}; root N+1: 0x{root_next.hex()}")
    print("  Root changed: yes")

    print("[8/25] Creating current Alice object Y", flush=True)
    manifest = create_offer(publisher, encoding_type="erasure")
    object_id = manifest["object_id"]
    new_dir = offers_dir / object_id
    require(object_x != object_id, "Mutation did not change the object ID")
    require(old_dir.is_dir() and new_dir.is_dir(), "Both offers must remain on disk")
    require(manifest["canonical_height"] == height_next, "Y has wrong canonical height")
    require(object_at_height(publisher, height_n) == object_x,
            "Height zero no longer resolves to X")
    require(object_at_root(publisher, f"0x{root_next.hex()}") == object_id,
            "Root N+1 does not resolve to Y")
    require(current_object(publisher) == object_id, "Current canonical object is not Y")
    print(f"  Object Y: {object_id}")
    print(f"  Height: {manifest['canonical_height']}; root: {manifest['state_root']}")
    print("  X and Y are distinct: yes")
    print("  Current by canonical height: Y")
    require(verify_peer(publisher), "Alice's updated proof failed verification")
    print("  Alice's updated proof: passed")

    print("[9/25] Distributing current object Y", flush=True)
    for custodian in custodians:
        result = request_custody(publisher, custodian, object_id)
        print(f"  Y fragment {result['fragment_index']:03d} ({result['fragment_size']} bytes) -> {custodian}")
    custody = load_custody(custodians[0], object_id)
    valid = get_valid_active_fragments(object_id, manifest, custody, PEERS_DIR)
    require(len(valid) == 5, "Y does not have five valid active fragments")
    require(all(load_custody(peer, object_id) == custody for peer in custodians),
            "Y custody views differ")
    print("  Y custody: 5/5 valid active fragments")
    show_fragments(custody)

    print("[10/25] Reconstructing and verifying Y at root N+1", flush=True)
    package = reconstruct_from_network(object_id, custodians[0])
    show_package(package, object_id)
    print(f"  Canonical height: {height_next}; trusted root: 0x{root_next.hex()}")

    print("[11/25] Checking coexistence and canonical order", flush=True)
    require(all((PEERS_DIR / peer / "data" / object_x).is_dir() and
                (PEERS_DIR / peer / "data" / object_id).is_dir()
                for peer in custodians), "X and Y are not separately stored on every custodian")
    require(all(load_custody(peer, object_x) == custody_x for peer in custodians),
            "Distributing Y changed X custody")
    package_x = reconstruct_from_network(object_x, custodians[0],
                                         canonical_height=height_n)
    show_package(package_x, object_x, canonical_height=height_n)
    require(current_object(publisher) == object_id and height_next > height_n,
            "Canonical order does not select Y")
    print("  X and Y custody directories: distinct on all five custodians")
    print("  X still reconstructs against recorded height 0: yes")
    print("  Y current because canonical height 1 > 0, independent of custody health")
    print("Two-version distribution passed")

    print("[12/25] Mutating Alice again for Z", flush=True)
    second_nonce = new_nonce + 1
    mutate_peer_state(publisher, nonce=second_nonce)
    require(int(nonce_path.read_text(encoding="utf-8").strip()) == second_nonce,
            "Second nonce mutation was not stored")
    print(f"  Alice nonce: {new_nonce} -> {second_nonce}")

    print("[13/25] Committing the third canonical state", flush=True)
    root_z = commit_state()
    height_z = current_commit()["height"]
    require(height_z == height_next + 1 and root_z != root_next,
            "Third canonical commit did not advance")
    print(f"  Height {height_z}; root Z: 0x{root_z.hex()}")

    print("[14/25] Creating Alice object Z", flush=True)
    object_y = object_id
    manifest_y = manifest
    custody_y = custody
    manifest_z = create_offer(publisher, encoding_type="erasure")
    object_z = manifest_z["object_id"]
    require(len({object_x, object_y, object_z}) == 3, "Three distinct objects were not created")
    require(object_at_height(publisher, height_z) == object_z,
            "Height two does not resolve to Z")
    require(current_object(publisher) == object_z, "Z is not canonical current")
    pending = protection_for_object(object_x)
    require(pending.protected and pending.role == "awaiting-protected-window"
            and meets_protection_target(object_y),
            "X must remain protected until the full window is safe")
    print(f"  Object Z: {object_z}")
    print(f"  Height: {height_z}; root: {manifest_z['state_root']}")
    print("  Y is safe; X remains protected while Z is incomplete")

    print("[15/25] Distributing Z", flush=True)
    for custodian in custodians:
        result = request_custody(publisher, custodian, object_z)
        print(f"  Z fragment {result['fragment_index']:03d} ({result['fragment_size']} bytes) -> {custodian}")
    custody_z = load_custody(custodians[0], object_z)
    require(object_health(object_z)[0] == 5, "Z does not have five valid active fragments")
    print("  Z custody: 5/5 valid active fragments")

    print("[16/25] Reconstructing and verifying Z", flush=True)
    package_z = reconstruct_from_network(object_z, custodians[0])
    show_package(package_z, object_z)
    print(f"  Canonical height: {height_z}; trusted root: 0x{root_z.hex()}")
    print("  Z independently recoverable: yes")

    print("[17/25] Evaluating retention policy", flush=True)
    status_x = protection_for_object(object_x)
    status_y = protection_for_object(object_y)
    status_z = protection_for_object(object_z)
    require(not status_x.protected and status_x.role == "historical",
            "X should be historical and unprotected")
    require(status_y.protected and status_y.role == "fallback",
            "Y should remain protected fallback")
    require(status_z.protected and status_z.role == "current",
            "Z should be protected current")
    print(f"  X: {status_x.role}, protected={status_x.protected}")
    print(f"  Y: {status_y.role}, protected={status_y.protected}")
    print(f"  Z: {status_z.role}, protected={status_z.protected}")
    print("  Ordering came from canonical source; protection came from retention policy")

    print("[18/25] Taking Alice offline and reconstructing Z", flush=True)
    removed_dir = Path("data/removed_peers") / publisher
    removed_dir.parent.mkdir(parents=True, exist_ok=True)
    shutil.move(str(PEERS_DIR / publisher), str(removed_dir))
    require(not (PEERS_DIR / publisher).exists(), "Alice remains in the active peer set")
    print(f"  Alice moved to: {removed_dir}")
    package_z = reconstruct_from_network(object_z, custodians[0])
    show_package(package_z, object_z)
    print("  Publisher-independent reconstruction: passed")

    print("[19/25] Renewing current Z custody", flush=True)
    before = custody_z["2"]["expires_at"]
    renewed = renew_custody(object_z, custodians[2])
    custody_z = load_custody(custodians[0], object_z)
    require(renewed["custodian"] == custodians[2]
            and parse_time(custody_z["2"]["expires_at"]) > parse_time(before),
            "Z custody renewal did not extend the lease")
    require(all(load_custody(peer, object_x) == custody_x for peer in custodians),
            "Z renewal changed X custody")
    require(all(load_custody(peer, object_y) == custody_y for peer in custodians),
            "Z renewal changed Y custody")
    print(f"  Z fragment 002 renewed by: {custodians[2]}")
    print(f"  Previous expiry: {before}")
    print(f"  New expiry: {custody_z['2']['expires_at']}")

    print("[20/25] Degrading historical X", flush=True)
    expire_fragment_claim(object_x)
    count_x, _, x_peer = object_health(object_x)
    require(count_x == 4, "X should have four valid active fragments")
    require(not repair_required(object_x), "Historical X has a repair obligation")
    package_x = reconstruct_from_network(object_x, x_peer)
    show_package(package_x, object_x, canonical_height=height_n)
    print("  X active fragments: 4/5; mandatory repair: no")
    print("  X bytes retained and historically valid")

    print("[21/25] Degrading protected fallback Y", flush=True)
    expire_fragment_claim(object_y)
    count_y, _, _ = object_health(object_y)
    require(count_y == 4 and repair_required(object_y),
            "Fallback Y should require repair at 4/5")
    print("  Y active fragments: 4/5; mandatory repair: yes")

    print("[22/25] Repairing fallback Y", flush=True)
    y_view = load_custody(custodians[1], object_y)
    valid_y = get_valid_active_fragments(object_y, manifest_y, y_view, PEERS_DIR)
    executor_y = min({lease["custodian"] for _, lease, _, _ in valid_y}, key=str.lower)
    repair_y = repair_network(object_y, executor_y, spare)
    require(repair_y["fragment_index"] == 0 and object_health(object_y)[0] == 5,
            "Fallback Y repair did not restore 5/5")
    require(object_health(object_x)[0] == 4, "Repairing Y changed X redundancy")
    print(f"  Executor: {executor_y}; replacement: {spare}")
    print("  Y active fragments restored: 5/5")

    print("[23/25] Degrading protected current Z", flush=True)
    expire_fragment_claim(object_z)
    count_z, _, _ = object_health(object_z)
    require(count_z == 4 and repair_required(object_z),
            "Current Z should require repair at 4/5")
    print("  Z active fragments: 4/5; mandatory repair: yes")

    print("[24/25] Repairing current Z", flush=True)
    z_view = load_custody(custodians[1], object_z)
    valid_z = get_valid_active_fragments(object_z, manifest_z, z_view, PEERS_DIR)
    executor_z = min({lease["custodian"] for _, lease, _, _ in valid_z}, key=str.lower)
    repair_z = repair_network(object_z, executor_z, spare)
    require(repair_z["fragment_index"] == 0 and object_health(object_z)[0] == 5,
            "Current Z repair did not restore 5/5")
    require(object_health(object_x)[0] == 4 and object_health(object_y)[0] == 5,
            "Repairing Z changed another object's redundancy")
    print(f"  Executor: {executor_z}; replacement: {spare}")
    print("  Z active fragments restored: 5/5")

    print("[25/25] Final canonical and custody checks", flush=True)
    require(current_object(publisher) == object_z, "Canonical current object changed")
    require(all((removed_dir / "offers" / object_id).is_dir()
                for object_id in (object_x, object_y, object_z)),
            "An offer was deleted")
    for label, object_id, height, peer in (
        ("X", object_x, height_n, x_peer),
        ("Y", object_y, height_next, executor_y),
        ("Z", object_z, height_z, executor_z),
    ):
        package = reconstruct_from_network(object_id, peer)
        require(verify_state_package(package, canonical_height=height),
                f"{label} failed historical canonical verification")
        print(f"  {label}: object {object_id}, valid at height {height}, "
              f"{object_health(object_id)[0]}/5 active fragments")
    require(not repair_required(object_x)
            and not protection_for_object(object_x).protected,
            "X unexpectedly regained protection")
    print("  Canonical current: Z; protected fallback: Y; unprotected historical: X")
    print("  Retirement changed protection, not stored bytes")
    print("Happy-path lifecycle passed")
    run_failure_experiment()
    run_witness_experiment()
    print("Full run passed")


def run_failure_experiment() -> None:
    print("\n=== Phase 2 #12: transition failures ===")
    active = [path.name for path in load_peer_dirs()]
    publisher = active[0]
    custodians = active[1:]
    require(len(custodians) == 5, "Failure experiment needs five custodians")
    nonce_path = PEERS_DIR / publisher / "cache" / "self" / "nonce"

    def next_offer() -> dict:
        nonce = int(nonce_path.read_text(encoding="utf-8").strip())
        mutate_peer_state(publisher, nonce=nonce + 1)
        commit_state()
        return create_offer(publisher, encoding_type="erasure")

    print("[failure 1/8] Establishing a safely protected predecessor", flush=True)
    commit_state()
    first = create_offer(publisher, encoding_type="erasure")
    x = first["object_id"]
    for custodian in custodians:
        request_custody(publisher, custodian, x)
    require(meets_protection_target(x), "Failure baseline X is not safe")
    print(f"  Publisher: {publisher}")
    print(f"  X: {x}; verified health {object_health(x)[0]}/{first['encoding']['total_fragments']}")

    print("[failure 2/8] Advancing canonical Y with one fragment", flush=True)
    second = next_offer()
    y = second["object_id"]
    request_custody(publisher, custodians[0], y)
    require(current_object(publisher) == y, "Y is not canonical current")
    require(object_health(y)[0] == 1 and not independently_recoverable(y)
            and not meets_protection_target(y), "Y one-fragment state misreported")
    require(protection_for_object(x).protected, "Safe X lost protection")
    print("  canonical current: Y; verified health: 1/5")
    print("  reconstructable: no; protection target met: no")
    print("  latest safely protected predecessor: X")

    print("[failure 3/8] Advancing canonical Z at reconstruction threshold", flush=True)
    third = next_offer()
    z = third["object_id"]
    for custodian in custodians[:2]:
        request_custody(publisher, custodian, z)
    package = reconstruct_from_network(z, custodians[0])
    require(get_object_id(package) == z and independently_recoverable(z)
            and not meets_protection_target(z), "Z threshold state misreported")
    require(current_object(publisher) == z and protection_for_object(x).protected,
            "Canonical advance falsely retired X")
    predecessor = latest_safely_protected_predecessor(publisher)
    require(predecessor is not None and predecessor["object_id"] == x,
            "X should remain the latest safe predecessor")
    print("  canonical current: Z; verified health: 2/5")
    print("  reconstructable: yes; protection target met: no")
    print("  latest safely protected predecessor: X")

    print("[failure 4/8] Corrupting a claimed Y fragment", flush=True)
    (PEERS_DIR / custodians[0] / "data" / y / "000.bin").write_bytes(b"corrupt")
    claimed = len(load_custody(custodians[0], y))
    require(claimed == 1 and object_health(y)[0] == 0,
            "Invalid physical bytes counted as protected")
    require(protection_for_object(x).protected, "Corrupt metadata retired X")
    print("  Y custody claims: 1; verified valid fragments: 0")
    print("  X remains protected: yes")

    print("[failure 5/8] Completing Z's protection target", flush=True)
    for custodian in custodians[2:]:
        request_custody(publisher, custodian, z)
    require(meets_protection_target(z) and object_health(z)[0] ==
            third["encoding"]["total_fragments"], "Z did not reach target")
    require(protection_for_object(x).protected and repair_required(y),
            "Unhealthy fallback Y must keep X protected")
    print("  Z verified health: 5/5; protection target met: yes")
    print("  Y verified health: 0/5; X remains protected: yes")

    print("[failure 6/8] Restoring the required fallback window", flush=True)
    source_fragment = PEERS_DIR / publisher / "offers" / y / "fragments" / "000.bin"
    damaged_fragment = PEERS_DIR / custodians[0] / "data" / y / "000.bin"
    shutil.copyfile(source_fragment, damaged_fragment)
    for custodian in custodians[1:]:
        request_custody(publisher, custodian, y)
    require(meets_protection_target(y) and meets_protection_target(z),
            "Current and fallback must both meet their targets")
    require(not protection_for_object(x).protected,
            "X should retire only after the full window is healthy")
    print("  Z current: 5/5; Y fallback: 5/5")
    print("  X historical/unprotected: yes")

    print("[failure 7/8] Publisher disappears during another partial transition", flush=True)
    fourth = next_offer()
    w = fourth["object_id"]
    request_custody(publisher, custodians[0], w)
    removed_dir = Path("data/removed_peers") / publisher
    removed_dir.parent.mkdir(parents=True, exist_ok=True)
    shutil.move(str(PEERS_DIR / publisher), str(removed_dir))
    require(current_object(publisher) == w and object_health(w)[0] == 1
            and not independently_recoverable(w) and not meets_protection_target(w),
            "Offline partial W was misreported")
    require(meets_protection_target(z) and protection_for_object(z).protected,
            "Safe Z predecessor lost protection")
    predecessor = latest_safely_protected_predecessor(publisher)
    require(predecessor is not None and predecessor["object_id"] == z,
            "Z should be the latest safe predecessor")
    print("  canonical current: W; publisher offline; verified health: 1/5")
    print("  reconstructable: no; protection target met: no")
    print("  latest safely protected predecessor: Z")

    print("[failure 8/8] Failing a repair without publishing a claim", flush=True)
    custody_path = PEERS_DIR / custodians[0] / "data" / w / "custody.json"
    before = custody_path.read_text(encoding="utf-8")
    require(repair_required(w), "Under-protected current W needs repair")
    try:
        repair_network(w, custodians[0], custodians[1])
    except ValueError as error:
        require("Not enough valid active fragments" in str(error),
                f"Unexpected repair failure: {error}")
    else:
        raise RuntimeError("One-fragment W repair incorrectly succeeded")
    require(custody_path.read_text(encoding="utf-8") == before
            and not (PEERS_DIR / custodians[1] / "data" / w).exists(),
            "Failed repair published a false claim")
    require(object_health(w)[0] == 1 and not meets_protection_target(w)
            and meets_protection_target(z), "Repair failure changed health truth")
    print("  repair failed: below reconstruction threshold")
    print("  W remains 1/5; no new custody claim; Z remains safely protected")
    print("Transition failure checks passed")


def run_witness_experiment() -> None:
    print("\n=== Phase 2+ #15: regenerable witnesses ===")
    active = load_peer_dirs()
    alice, bob = active[:2]
    backend = ToyMerkleBackend()
    state_key = account_state_key(alice.name)
    root_before = commit_state()
    value_id = state_value_id(read_account_value(alice))
    print(f"  Alice value ID before: {value_id}")
    print(f"  Canonical root before: 0x{root_before.hex()}")

    bob_nonce = bob / "cache" / "self" / "nonce"
    mutate_peer_state(bob.name, nonce=int(bob_nonce.read_text(encoding="utf-8").strip()) + 1)
    root_after = commit_state()
    require(root_after != root_before, "Unrelated state mutation did not change the root")
    require(state_value_id(read_account_value(alice)) == value_id,
            "Unchanged Alice value bytes acquired a new value ID")
    print(f"  Canonical root after Bob mutation: 0x{root_after.hex()}")
    print(f"  Alice value ID after: {value_id}; value bytes unchanged: yes")

    value = load_state_value(value_id)
    witness = backend.build_witness(root_after, state_key, value)
    del witness
    cached_proofs = {
        peer / "cache" / "self" / "proof.json":
        (peer / "cache" / "self" / "proof.json").read_bytes()
        for peer in active
    }
    try:
        for path in cached_proofs:
            path.unlink()
        regenerated = backend.build_witness(root_after, state_key, value)
    finally:
        for path, proof_bytes in cached_proofs.items():
            path.write_bytes(proof_bytes)
    require(backend.verify_witness(state_key, value, regenerated, root_after),
            "Regenerated witness failed")
    require(not backend.verify_witness(state_key, value, regenerated, root_before),
            "Wrong root accepted")
    print("  Witness discarded; legacy proof caches temporarily deleted; regeneration verifies: yes")
    print("  Wrong-root verification: rejected")

    node_path = content_path(backend.nodes_dir, regenerated["siblings"][0]["hash"])
    original = node_path.read_bytes()
    try:
        node_path.write_bytes(original + b"tampered")
        try:
            backend.build_witness(root_after, state_key, value)
        except ValueError as error:
            require("Content hash mismatch" in str(error), f"Unexpected node error: {error}")
        else:
            raise RuntimeError("Tampered authenticated node was accepted")
    finally:
        node_path.write_bytes(original)
    print("  Tampered-node regeneration: rejected")
    print("Regenerable witness checks passed")

def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="State Fabric research simulator")
    commands = parser.add_subparsers(dest="command", required=True)
    init_parser = commands.add_parser("init", help="Reset and initialize deterministic peers")
    init_parser.add_argument("--peers", type=int, default=7, help="Number of peers (default: 7)")
    commands.add_parser("commit", help="Commit current peer state and generate proofs")
    commands.add_parser("verify", help="Verify current peer proofs and offer roots")
    commands.add_parser("run", help="Run Phase 1 and the Phase 2 state transition")
    return parser


def main() -> None:
    args = build_parser().parse_args()
    if args.command == "init":
        print(f"Initialized {initialize(args.peers)} peers in data/peers/")
    elif args.command == "commit":
        root = commit_state()
        print(f"Root: 0x{root.hex()}")
        print("Generated proofs for all peers")
    elif args.command == "verify":
        verify_current()
    elif args.command == "run":
        run_experiment()


if __name__ == "__main__":
    main()
