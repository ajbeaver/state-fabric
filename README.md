# State Fabric

State Fabric is a research project exploring whether authenticated Ethereum-like state can be distributed across unreliable peers, reconstructed on demand, and verified without requiring every participant to store the full state.

The core question is:

> Can canonical state be fragmented across many devices, reconstructed from only a subset of those fragments, and still be independently verified against a trusted state root?

This is currently a local Python simulator. It does not modify Ethereum or participate in consensus.

## Current Experiment

Each simulated peer has:

- an Ethereum address
- a small amount of local state
- a storage capacity
- a local data directory for future fragment custody

State is committed into a Merkle tree and verified against a shared state root.

Before distribution, peer state is packed into a deterministic binary object containing:

```text
address
balance
nonce
state root
Merkle proof
```

That object is content-addressed with Keccak-256.

## What Works

State Fabric currently supports:

```text
✓ deterministic Ethereum-address peers
✓ Merkle state commitments
✓ independent state verification
✓ deterministic state packages
✓ plain striping
✓ fragment integrity hashes
✓ 2-of-5 erasure coding
✓ reconstruction from any 2 fragments
✓ verification after reconstruction
```

The current recovery test is:

```text
state package
     ↓
5 encoded fragments
     ↓
destroy 3
     ↓
reconstruct from 2
     ↓
verify object hash
     ↓
verify Merkle proof
     ↓
canonical state recovered
```

With only one fragment remaining, reconstruction fails as expected.

## CLI

Initialize five peers:

```bash
python3 main.py init --peers 5
```

Commit the current state:

```bash
python3 main.py commit
```

Create a 2-of-5 erasure-coded offer:

```bash
python3 main.py offer \
  --address 0xPEER_ADDRESS \
  --encoding erasure
```

Reconstruct it:

```bash
python3 main.py reconstruct \
  --address 0xPEER_ADDRESS
```

Delete fragments for failure testing:

```bash
python3 main.py drop-fragment \
  --address 0xPEER_ADDRESS \
  --index 2
```

Plain striping is also available as a control:

```bash
python3 main.py offer \
  --address 0xPEER_ADDRESS \
  --encoding stripe \
  --fragments 4
```

## Next Milestone

The five fragments are currently created locally by the publishing peer.

The next step is to distribute them into independent peer `data/` directories, enforce capacity limits, remove the publisher, and prove that surviving peers alone can reconstruct and verify the state.

The target test is:

```text
publisher creates state
        ↓
fragments distributed to peers
        ↓
publisher disappears
        ↓
several storage peers disappear
        ↓
threshold fragments survive
        ↓
state reconstructs and verifies
```

## Research Path

```text
Phase 1
Distributed static state

Phase 2
Dynamic state and versioning

Phase 3
Anvil-backed Ethereum state

Phase 4
Public Ethereum testnet
```

The project is intentionally staying below the networking and consensus layers until the storage model proves useful.

## Repository

```text
state-fabric/
├── main.py
├── modules/
│   ├── wallets.py
│   ├── peers.py
│   ├── merkle.py
│   └── storage.py
└── README.md
```

`data/` is generated runtime state and should not be tracked in Git.
