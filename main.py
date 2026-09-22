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
from modules.merkle import commit_state, load_peer_dirs, load_state_root, verify_peer
from modules.peers import initialize_peers, mutate_peer_state
from modules.storage import create_offer, get_object_id, reconstruct_offer, verify_state_package


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
    print("[1/16] Initializing peers", flush=True)
    require(initialize(7) == 7, "Expected seven peers")
    addresses = [path.name for path in load_peer_dirs()]
    publisher, custodians, spare = addresses[0], addresses[1:6], addresses[6]
    for index, address in enumerate(addresses):
        role = "publisher" if address == publisher else "spare" if address == spare else "custodian"
        print(f"  peer {index}: {address} ({role})")

    print("[2/16] Committing Alice's original state", flush=True)
    root_n = commit_state()
    height_n = current_commit()["height"]
    require(height_n == 0, "Initial canonical height must be zero")
    print(f"  Height {height_n}; root N: 0x{root_n.hex()}")
    require(all(verify_peer(address) for address in addresses), "Initial peer proof failed")
    print(f"  Proofs verified: {len(addresses)}/{len(addresses)}")

    print("[3/16] Creating Alice object X", flush=True)
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

    print("[4/16] Distributing X before mutation", flush=True)
    for custodian in custodians:
        result = request_custody(publisher, custodian, object_x)
        print(f"  X fragment {result['fragment_index']:03d} ({result['fragment_size']} bytes) -> {custodian}")
    custody_x = load_custody(custodians[0], object_x)
    valid_x = get_valid_active_fragments(object_x, offer_x, custody_x, PEERS_DIR)
    require(len(valid_x) == 5, "X does not have five valid active fragments")
    require(all(load_custody(peer, object_x) == custody_x for peer in custodians),
            "X custody views differ")
    print("  X custody: 5/5 valid active fragments")

    print("[5/16] Reconstructing and verifying X at root N", flush=True)
    package_x = reconstruct_from_network(object_x, custodians[0])
    show_package(package_x, object_x)
    print(f"  Canonical height: {height_n}; trusted root: 0x{root_n.hex()}")
    print("  X healthy before mutation: yes")

    print("[6/16] Mutating Alice's local state", flush=True)
    nonce_path = PEERS_DIR / publisher / "cache" / "self" / "nonce"
    old_nonce = int(nonce_path.read_text(encoding="utf-8").strip())
    new_nonce = old_nonce + 1
    mutate_peer_state(publisher, nonce=new_nonce)
    require(int(nonce_path.read_text(encoding="utf-8").strip()) == new_nonce,
            "Nonce mutation was not stored")
    print(f"  Alice nonce: {old_nonce} -> {new_nonce}")

    print("[7/16] Committing Alice's mutated state", flush=True)
    root_next = commit_state()
    height_next = current_commit()["height"]
    require(height_next == height_n + 1, "Canonical height did not advance")
    require(root_n != root_next, "Mutation did not change the canonical root")
    print(f"  Height {height_next}; root N+1: 0x{root_next.hex()}")
    print("  Root changed: yes")

    print("[8/16] Creating current Alice object Y", flush=True)
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

    print("[9/16] Distributing current object Y", flush=True)
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

    print("[10/16] Reconstructing and verifying Y at root N+1", flush=True)
    package = reconstruct_from_network(object_id, custodians[0])
    show_package(package, object_id)
    print(f"  Canonical height: {height_next}; trusted root: 0x{root_next.hex()}")

    print("[11/16] Checking coexistence and canonical order", flush=True)
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

    print("[12/16] Taking Alice offline and reconstructing Y", flush=True)
    removed_dir = Path("data/removed_peers") / publisher
    removed_dir.parent.mkdir(parents=True, exist_ok=True)
    shutil.move(str(PEERS_DIR / publisher), str(removed_dir))
    require(not (PEERS_DIR / publisher).exists(), "Alice remains in the active peer set")
    print(f"  Alice moved to: {removed_dir}")
    package = reconstruct_from_network(object_id, custodians[0])
    show_package(package, object_id)
    print("  Publisher-independent reconstruction: passed")

    print("[13/16] Renewing Y custody", flush=True)
    before = custody["2"]["expires_at"]
    renewed = renew_custody(object_id, custodians[2])
    custody = load_custody(custodians[0], object_id)
    require(renewed["custodian"] == custodians[2]
            and parse_time(custody["2"]["expires_at"]) > parse_time(before),
            "Y custody renewal did not extend the lease")
    require(all(load_custody(peer, object_x) == custody_x for peer in custodians),
            "Y renewal changed X custody")
    print(f"  Y fragment 002 renewed by: {custodians[2]}")
    print(f"  Previous expiry: {before}")
    print(f"  New expiry: {custody['2']['expires_at']}")

    print("[14/16] Expiring one Y fragment claim", flush=True)
    for path in PEERS_DIR.glob(f"*/data/{object_id}/custody.json"):
        view = json.loads(path.read_text(encoding="utf-8"))
        view["0"]["expires_at"] = EXPIRED_AT
        path.write_text(json.dumps(view, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    custody = load_custody(custodians[0], object_id)
    valid = get_valid_active_fragments(object_id, manifest, custody, PEERS_DIR)
    require(len(valid) == 4 and {item[0] for item in valid} == {1, 2, 3, 4},
            "Expected only Y fragment zero to expire")
    print("  Y active fragments: 4/5")
    show_fragments(custody)

    print("[15/16] Repairing Y fragment", flush=True)
    executor = min({lease["custodian"] for _, lease, _, _ in valid}, key=str.lower)
    result = repair_network(object_id, executor, spare)
    require(result["fragment_index"] == 0 and result["custodian"] == spare,
            "Y repair assigned the wrong fragment or custodian")
    custody = load_custody(executor, object_id)
    valid = get_valid_active_fragments(object_id, manifest, custody, PEERS_DIR)
    require(len(valid) == 5 and len(active_claims(custody)) == 5,
            "Y repair did not restore five active fragments")
    require(all(load_custody(peer, object_x) == custody_x for peer in custodians),
            "Y repair changed X custody")
    print(f"  Executor: {executor}; replacement: {spare}")
    print(f"  Regenerated Y fragment: {result['fragment_index']:03d}")
    print(f"  Stored at: {result['destination']}")
    print("  Y active fragments: 5/5")
    show_fragments(custody)

    print("[16/16] Final Y reconstruction", flush=True)
    package = reconstruct_from_network(object_id, executor)
    show_package(package, object_id)
    require((removed_dir / "offers" / object_x).is_dir(), "X offer was lost")
    require((removed_dir / "offers" / object_id).is_dir(), "Y offer was lost")
    require(current_object(publisher) == object_id, "Current canonical object changed")
    print(f"  Canonical current: height {height_next}, object Y {object_id}")
    print("  X retained; Y repaired; X custody unchanged")
    print("Full run passed")

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
