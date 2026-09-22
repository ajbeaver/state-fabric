"""Replaceable commitment boundary; this module contains the toy Merkle backend."""

import json
from pathlib import Path
from typing import Protocol

from eth_utils import keccak

from modules.content_store import content_id, get_content, put_content
from modules.state_values import state_value_id, store_state_value


DEFAULT_REFERENCE_DIR = Path("data/reference")


class CommitmentBackend(Protocol):
    """Bind state keys to value bytes under an externally trusted commitment."""
    def commit(self, entries: list[tuple[bytes, bytes]]) -> bytes: ...
    def build_witness(self, root: bytes, state_key: bytes,
                      value_bytes: bytes) -> dict: ...
    def verify_witness(self, state_key: bytes, value_bytes: bytes,
                       witness: dict, trusted_root: bytes) -> bool: ...


class ToyMerkleBackend:
    """Balanced toy tree; key/value bindings and traversal stay backend-private."""

    codec = "toy-merkle-v1"

    def __init__(self, reference_dir: Path = DEFAULT_REFERENCE_DIR) -> None:
        self.reference_dir = reference_dir
        self.nodes_dir = reference_dir / "authenticated_nodes"
        self.roots_dir = reference_dir / "toy_merkle" / "roots"

    @staticmethod
    def _leaf_bytes(state_key: bytes, value_bytes: bytes) -> bytes:
        return b"address=" + state_key + b"\n" + value_bytes

    def _root_metadata_path(self, root: bytes) -> Path:
        return self.roots_dir / f"{root.hex()}.json"

    def commit(self, entries: list[tuple[bytes, bytes]]) -> bytes:
        """Retain values and all nodes needed for later path regeneration."""
        from modules.merkle import build_merkle_levels

        if not entries:
            raise ValueError("Cannot commit an empty state")
        keys = [key for key, _ in entries]
        if keys != sorted(set(keys)):
            raise ValueError("State keys must be unique and sorted")

        leaves = []
        for key, value in entries:
            store_state_value(value, self.reference_dir)
            leaves.append(bytes.fromhex(put_content(
                self.nodes_dir, self._leaf_bytes(key, value),
            )[2:]))
        levels = build_merkle_levels(leaves)
        for level in levels[:-1]:
            working = level + ([level[-1]] if len(level) % 2 else [])
            for index in range(0, len(working), 2):
                put_content(self.nodes_dir, working[index] + working[index + 1])

        root = levels[-1][0]
        self.roots_dir.mkdir(parents=True, exist_ok=True)
        metadata = {
            "codec": self.codec,
            "keys": [key.hex() for key in keys],
            "levels": [[node.hex() for node in level] for level in levels],
        }
        path = self._root_metadata_path(root)
        if path.exists():
            if json.loads(path.read_text(encoding="utf-8")) != metadata:
                raise ValueError("Conflicting toy traversal metadata")
        else:
            path.write_text(json.dumps(metadata, indent=2) + "\n", encoding="utf-8")
        return root

    def build_witness(self, root: bytes, state_key: bytes,
                      value_bytes: bytes) -> dict:
        """Read and validate retained nodes; no cached witness is required."""
        metadata = json.loads(self._root_metadata_path(root).read_text(encoding="utf-8"))
        if metadata.get("codec") != self.codec:
            raise ValueError("Wrong commitment codec")
        keys = metadata["keys"]
        if state_key.hex() not in keys:
            raise ValueError("State key absent from retained commitment")
        levels = metadata["levels"]
        if levels[-1] != [root.hex()]:
            raise ValueError("Root metadata does not match requested commitment")

        index = keys.index(state_key.hex())
        leaf_id = "0x" + levels[0][index]
        leaf = get_content(self.nodes_dir, leaf_id)
        if leaf != self._leaf_bytes(state_key, value_bytes):
            raise ValueError("State value does not match retained leaf")
        siblings = []
        for level in levels[:-1]:
            side = "right" if index % 2 == 0 else "left"
            sibling_index = index ^ 1
            if sibling_index >= len(level):
                sibling_index = index
            node_id = "0x" + level[index]
            sibling_id = "0x" + level[sibling_index]
            get_content(self.nodes_dir, node_id)
            get_content(self.nodes_dir, sibling_id)
            node_hash = bytes.fromhex(node_id[2:])
            sibling_hash = bytes.fromhex(sibling_id[2:])
            parent = (node_hash + sibling_hash if index % 2 == 0
                      else sibling_hash + node_hash)
            index //= 2
            if content_id(parent) != "0x" + levels[len(siblings) + 1][index]:
                raise ValueError("Authenticated path does not match retained nodes")
            get_content(self.nodes_dir, content_id(parent))
            siblings.append({
                "side": side,
                "hash": sibling_id,
            })

        witness = {
            "codec": self.codec,
            "root": f"0x{root.hex()}",
            "state_key": state_key.hex(),
            "state_value_id": state_value_id(value_bytes),
            "siblings": siblings,
        }
        if not self.verify_witness(state_key, value_bytes, witness, root):
            raise ValueError("Regenerated witness does not verify")
        return witness

    def verify_witness(self, state_key: bytes, value_bytes: bytes,
                       witness: dict, trusted_root: bytes) -> bool:
        """Verify a state value and derived witness against an externally trusted root."""
        if (witness.get("codec") != self.codec
                or witness.get("root") != f"0x{trusted_root.hex()}"
                or witness.get("state_key") != state_key.hex()
                or witness.get("state_value_id") != state_value_id(value_bytes)):
            return False
        current = keccak(self._leaf_bytes(state_key, value_bytes))
        try:
            for sibling in witness["siblings"]:
                sibling_hash = bytes.fromhex(sibling["hash"].removeprefix("0x"))
                if len(sibling_hash) != 32:
                    return False
                if sibling["side"] == "left":
                    current = keccak(sibling_hash + current)
                elif sibling["side"] == "right":
                    current = keccak(current + sibling_hash)
                else:
                    return False
        except (KeyError, TypeError, ValueError):
            return False
        return current == trusted_root
