"""Temporary Phase 2 commit ordering; replace with chain metadata in Phase 3."""

import json
from pathlib import Path


DEFAULT_REFERENCE_DIR = Path("data/reference")


def load_history(reference_dir: Path = DEFAULT_REFERENCE_DIR) -> list[dict]:
    path = reference_dir / "canonical_history.json"
    if not path.exists():
        return []
    return json.loads(path.read_text(encoding="utf-8"))["commits"]


def save_history(commits: list[dict], reference_dir: Path = DEFAULT_REFERENCE_DIR) -> None:
    reference_dir.mkdir(parents=True, exist_ok=True)
    (reference_dir / "canonical_history.json").write_text(
        json.dumps({"commits": commits}, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def current_commit(reference_dir: Path = DEFAULT_REFERENCE_DIR) -> dict:
    commits = load_history(reference_dir)
    if not commits:
        raise ValueError("No canonical commit exists")
    return max(commits, key=lambda commit: commit["height"])


def commit_at_height(height: int, reference_dir: Path = DEFAULT_REFERENCE_DIR) -> dict:
    for commit in load_history(reference_dir):
        if commit["height"] == height:
            return commit
    raise ValueError(f"Canonical height not found: {height}")


def record_commit(state_root: str, reference_dir: Path = DEFAULT_REFERENCE_DIR) -> dict:
    commits = load_history(reference_dir)
    previous = max(commits, key=lambda commit: commit["height"]) if commits else None
    commit = {
        "height": previous["height"] + 1 if previous else 0,
        "state_root": state_root,
        "parent_root": previous["state_root"] if previous else None,
        "objects": {},
    }
    commits.append(commit)
    save_history(commits, reference_dir)
    return commit


def register_object(address: str, state_root: str, object_id: str,
                    reference_dir: Path = DEFAULT_REFERENCE_DIR) -> int:
    commits = load_history(reference_dir)
    if not commits:
        raise ValueError("Commit state before creating an offer")
    commit = max(commits, key=lambda item: item["height"])
    if commit["state_root"] != state_root:
        raise ValueError("Offer root does not match current canonical commit")
    commit["objects"][address.lower()] = object_id
    save_history(commits, reference_dir)
    return commit["height"]


def object_at_height(address: str, height: int,
                     reference_dir: Path = DEFAULT_REFERENCE_DIR) -> str:
    commit = commit_at_height(height, reference_dir)
    try:
        return commit["objects"][address.lower()]
    except KeyError as error:
        raise ValueError(f"No object for {address} at height {height}") from error


def object_at_root(address: str, state_root: str,
                   reference_dir: Path = DEFAULT_REFERENCE_DIR) -> str:
    matches = [commit for commit in load_history(reference_dir)
               if commit["state_root"] == state_root]
    if not matches:
        raise ValueError(f"Canonical root not found: {state_root}")
    commit = max(matches, key=lambda item: item["height"])
    return object_at_height(address, commit["height"], reference_dir)


def current_object(address: str, reference_dir: Path = DEFAULT_REFERENCE_DIR) -> str:
    return object_at_height(address, current_commit(reference_dir)["height"], reference_dir)


class SimulatorCanonicalSource:
    """Phase 2 provider of ordered, immutable object references."""

    def __init__(self, reference_dir: Path = DEFAULT_REFERENCE_DIR) -> None:
        self.reference_dir = reference_dir

    def versions(self, address: str) -> list[dict]:
        versions = [
            {
                "address": address.lower(),
                "sequence": commit["height"],
                "canonical_id": commit["state_root"],
                "parent_canonical_id": commit["parent_root"],
                "object_id": commit["objects"][address.lower()],
            }
            for commit in load_history(self.reference_dir)
            if address.lower() in commit["objects"]
        ]
        return sorted(versions, key=lambda version: version["sequence"])

    def version_for_object(self, object_id: str) -> dict:
        for commit in sorted(load_history(self.reference_dir),
                             key=lambda item: item["height"], reverse=True):
            for address, candidate in commit["objects"].items():
                if candidate == object_id:
                    return {
                        "address": address,
                        "sequence": commit["height"],
                        "canonical_id": commit["state_root"],
                        "parent_canonical_id": commit["parent_root"],
                        "object_id": object_id,
                    }
        raise ValueError(f"Canonical object not found: {object_id}")

    def root_for_manifest(self, manifest: dict,
                          expected_sequence: int | None = None) -> str:
        height = manifest["canonical_height"]
        if expected_sequence is not None and expected_sequence != height:
            raise ValueError("Requested canonical sequence does not match object")
        commit = commit_at_height(height, self.reference_dir)
        if (commit["state_root"] != manifest["state_root"]
                or commit["objects"].get(manifest["address"].lower())
                != manifest["object_id"]):
            raise ValueError("Object manifest does not match canonical source")
        return commit["state_root"]


def canonical_source(reference_dir: Path = DEFAULT_REFERENCE_DIR) -> SimulatorCanonicalSource:
    """Single replacement point for Phase 3's external canonical provider."""
    return SimulatorCanonicalSource(reference_dir)
