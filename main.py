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


def show_package(package: bytes, object_id: str) -> None:
    actual_id = get_object_id(package)
    canonical = verify_state_package(package)
    require(actual_id == object_id and canonical, "Reconstructed package failed verification")
    print(f"  Reconstructed bytes: {len(package)}")
    print(f"  Reconstructed object ID: {actual_id}")
    print("  Canonical verification: passed")


def verify_current() -> None:
    peers = load_peer_dirs()
    root = load_state_root()
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
        custodian = max(
            custodians,
            key=lambda peer: len(active_claims(load_custody(peer, object_id))),
        )
        object_dir = PEERS_DIR / custodian / "data" / object_id
        manifest = json.loads((object_dir / "manifest.json").read_text(encoding="utf-8"))
        if manifest["state_root"] != f"0x{root.hex()}":
            continue
        custody = load_custody(custodian, object_id)
        valid = get_valid_active_fragments(object_id, manifest, custody, PEERS_DIR)
        require(len(valid) >= manifest["encoding"]["required_fragments"],
                f"Insufficient active fragments: {object_id}")
        package = reconstruct_from_network(object_id, custodian)
        require(get_object_id(package) == object_id and verify_state_package(package),
                f"Distributed object failed verification: {object_id}")
        print(f"Distributed object {object_id}: {len(valid)}/{manifest['encoding']['total_fragments']} active fragments, canonical verification passed")
        show_fragments(custody)
    current_network_objects = sum(
        json.loads((PEERS_DIR / custodians[0] / "data" / object_id / "manifest.json").read_text(encoding="utf-8"))["state_root"] == f"0x{root.hex()}"
        for object_id, custodians in network_objects.items()
    )
    print(f"Current distributed objects: {current_network_objects}")
    print("  Objects from previous roots are retained but not historically verified")
    print("Current state verification: passed")


def run_experiment() -> None:
    print("[1/15] Initializing peers", flush=True)
    require(initialize(7) == 7, "Expected seven peers")
    addresses = [path.name for path in load_peer_dirs()]
    publisher, custodians, spare = addresses[0], addresses[1:6], addresses[6]
    for index, address in enumerate(addresses):
        role = "publisher" if address == publisher else "spare" if address == spare else "custodian"
        print(f"  peer {index}: {address} ({role})")

    print("[2/15] Committing state", flush=True)
    root_n = commit_state()
    print(f"Root N (Alice's original state): 0x{root_n.hex()}")
    require(all(verify_peer(address) for address in addresses), "Initial peer proof failed")
    print(f"  Proofs verified: {len(addresses)}/{len(addresses)}")

    print("[3/15] Creating Alice's original 2-of-5 object X", flush=True)
    offer_x = create_offer(publisher, encoding_type="erasure")
    object_x = offer_x["object_id"]
    encoding = offer_x["encoding"]
    require((encoding["required_fragments"], encoding["total_fragments"]) == (2, 5),
            "Expected 2-of-5 encoding")
    print(f"Object X: {object_x}")
    print(f"  Publisher: {publisher}")
    print(f"  Package size: {offer_x['original_size']} bytes")
    print(f"  Encoding: {encoding['type']}, {encoding['required_fragments']}-of-{encoding['total_fragments']}")
    offers_dir = PEERS_DIR / publisher / "offers"
    old_dir = offers_dir / object_x
    require(old_dir.is_dir(), "Object X offer is missing")
    print(f"  Offer X: {old_dir}")

    print("\n=== Controlled state transition: Alice before custody ===")
    print("[4/15] Mutating Alice's local state", flush=True)
    nonce_path = PEERS_DIR / publisher / "cache" / "self" / "nonce"
    old_nonce = int(nonce_path.read_text(encoding="utf-8").strip())
    new_nonce = old_nonce + 1
    mutate_peer_state(publisher, nonce=new_nonce)
    require(int(nonce_path.read_text(encoding="utf-8").strip()) == new_nonce,
            "Nonce mutation was not stored")
    print(f"  Alice: {publisher}")
    print(f"  Nonce: {old_nonce} -> {new_nonce}")

    print("[5/15] Committing Alice's mutated state", flush=True)
    root_next = commit_state()
    require(root_n != root_next, "Mutation did not change the canonical root")
    print(f"  Root N+1 (Alice's mutated state): 0x{root_next.hex()}")
    print("  Root changed: yes")

    print("[6/15] Creating current object Y", flush=True)
    manifest = create_offer(publisher, encoding_type="erasure")
    object_id = manifest["object_id"]
    new_dir = offers_dir / object_id
    require(object_x != object_id, "Mutation did not change the object ID")
    require(old_dir.is_dir() and new_dir.is_dir(), "Both offers must remain on disk")
    print(f"  Object Y: {object_id}")
    print(f"  Offer Y: {new_dir}")
    print("  Object changed: yes")
    print("  Previous object preserved: yes")

    print("[7/15] Verifying Alice's new current state", flush=True)
    package = reconstruct_offer(new_dir)
    show_package(package, object_id)
    require(verify_peer(publisher), "Mutated Alice proof failed verification")
    print("  Alice's updated proof: passed")
    print("State transition experiment passed")

    print("\n=== Phase 1 custody lifecycle using object Y ===")

    print("[8/15] Distributing current object Y fragments", flush=True)
    print(f"  Distributing object Y: {object_id}")
    for custodian in custodians:
        result = request_custody(publisher, custodian, object_id)
        print(f"  fragment {result['fragment_index']:03d} ({result['fragment_size']} bytes) -> {custodian}")
    custody = load_custody(custodians[0], object_id)
    require(len(active_claims(custody)) == 5, "Expected five active claims")
    require(all(load_custody(peer, object_id) == custody for peer in custodians),
            "Custody views differ")
    print("Active fragments: 5/5; custody views agree")
    show_fragments(custody)

    print("[9/15] Reconstructing Y from distributed custody", flush=True)
    package = reconstruct_from_network(object_id, custodians[0])
    print(f"  Starting custodian: {custodians[0]}")
    show_package(package, object_id)

    print("[10/15] Removing Alice and reconstructing Y", flush=True)
    removed_dir = Path("data/removed_peers") / publisher
    removed_dir.parent.mkdir(parents=True, exist_ok=True)
    shutil.move(str(PEERS_DIR / publisher), str(removed_dir))
    require(not (PEERS_DIR / publisher).exists(), "Alice remains in the active peer set")
    print(f"  Alice removed from active peers; files retained at: {removed_dir}")
    package = reconstruct_from_network(object_id, custodians[0])
    show_package(package, object_id)
    print("Publisher-independent reconstruction: passed")

    print("[11/15] Renewing custody", flush=True)
    before = custody["2"]["expires_at"]
    renewed = renew_custody(object_id, custodians[2])
    custody = load_custody(custodians[0], object_id)
    require(renewed["custodian"] == custodians[2]
            and parse_time(custody["2"]["expires_at"]) > parse_time(before),
            "Custody renewal did not extend the lease")
    print(f"Renewed: {custodians[2]}")
    print(f"  Fragment: 002; previous expiry: {before}")
    print(f"  New expiry: {custody['2']['expires_at']}")

    print("[12/15] Expiring one fragment claim", flush=True)
    for path in PEERS_DIR.glob(f"*/data/{object_id}/custody.json"):
        view = json.loads(path.read_text(encoding="utf-8"))
        view["0"]["expires_at"] = EXPIRED_AT
        path.write_text(json.dumps(view, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    custody = load_custody(custodians[0], object_id)
    valid = get_valid_active_fragments(object_id, manifest, custody, PEERS_DIR)
    require(len(valid) == 4 and {item[0] for item in valid} == {1, 2, 3, 4},
            "Expected only fragment zero to expire")
    print("Active fragments: 4/5")
    print(f"  Fragment 000 claim expiry set to {EXPIRED_AT} in replicated custody views")
    show_fragments(custody)

    print("[13/15] Repairing missing fragment", flush=True)
    executor = min({lease["custodian"] for _, lease, _, _ in valid}, key=str.lower)
    result = repair_network(object_id, executor, spare)
    require(result["fragment_index"] == 0 and result["custodian"] == spare,
            "Repair assigned the wrong fragment or custodian")
    custody = load_custody(executor, object_id)
    valid = get_valid_active_fragments(object_id, manifest, custody, PEERS_DIR)
    require(len(valid) == 5 and len(active_claims(custody)) == 5,
            "Repair did not restore five active fragments")
    print(f"Executor: {executor}; replacement: {spare}")
    print(f"  Regenerated fragment: {result['fragment_index']:03d}")
    print(f"  Stored at: {result['destination']}")
    print("Active fragments: 5/5")
    show_fragments(custody)

    print("[14/15] Final reconstruction", flush=True)
    package = reconstruct_from_network(object_id, executor)
    print(f"  Starting custodian: {executor}")
    show_package(package, object_id)
    print("[15/15] Confirming final Y and preserved X", flush=True)
    require(get_object_id(package) == object_id, "Final reconstruction was not object Y")
    require((removed_dir / "offers" / object_x).is_dir(), "Object X was lost")
    require((removed_dir / "offers" / object_id).is_dir(), "Object Y was lost")
    print(f"  Reconstructed object Y: {object_id}")
    print(f"  Preserved object X: {removed_dir / 'offers' / object_x}")
    print("  Publisher-independent custody lifecycle: passed")
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
