# State Fabric

State Fabric is a research project exploring whether authenticated Ethereum-like state can be distributed across unreliable peers, reconstructed on demand, repaired after peer loss, and independently verified without requiring every participant to store the full state.

The core question is:

> Can canonical state survive as a distributed, self-repairing set of fragments while remaining verifiable against a trusted state root?

State Fabric is currently a local Python simulator. It does not modify Ethereum or participate in consensus.

## Phase 1 — Distributed Static State

Phase 1 models immutable authenticated state.

Each simulated peer has:

- an Ethereum address
- local state
- volunteered storage capacity
- a local data directory for fragment custody

Peer state is committed into a Merkle tree and verified against a shared trusted state root.

Before distribution, state is packed into a deterministic binary object containing:

```text
address
balance
nonce
state root
Merkle proof
```

The object is content-addressed with Keccak-256 and encoded using a 2-of-5 erasure scheme.

Any two valid fragments can reconstruct the original object.

## What Works

State Fabric currently supports:

```text
✓ deterministic Ethereum-address peers
✓ Merkle state commitments
✓ canonical state verification
✓ deterministic state packages
✓ fragment integrity hashes
✓ 2-of-5 erasure coding
✓ peer storage capacity enforcement
✓ fragment custody across independent peers
✓ replicated custody metadata
✓ publisher-independent reconstruction
✓ expiring custody claims
✓ independent custody renewal
✓ deterministic repair executor selection
✓ missing-fragment regeneration
✓ fragment reassignment after peer loss
✓ recovery after the original publisher disappears
✓ pytest coverage for Phase 1 failure behavior
```

The Phase 1 lifecycle now looks like:

```text
publisher creates authenticated state
        ↓
object encoded into 5 fragments
        ↓
fragments distributed to independent custodians
        ↓
custody metadata replicated
        ↓
publisher disappears
        ↓
custodian disappears or claim expires
        ↓
surviving fragments reconstruct the object
        ↓
missing fragment regenerated
        ↓
new custodian accepts fragment
        ↓
redundancy returns to 5 fragments
        ↓
state remains independently verifiable
```

The publisher is required to create and initially distribute the object, but is not required for later reconstruction, custody renewal, or fragment repair.

## Trust Model

State Fabric separates three concerns:

```text
trusted state root
    ↓
determines canonical truth

object and fragment hashes
    ↓
determine integrity

custody metadata
    ↓
describes where fragments are currently available
```

Custody metadata is not treated as canonical state.

A fragment only counts toward network availability while its custody claim is active and unexpired.

Expired fragments are treated as unavailable and may be regenerated from surviving fragments.

## CLI

Initialize peers:

```bash
python3 main.py init --peers 7
```

Commit state:

```bash
python3 main.py commit
```

Create a 2-of-5 erasure-coded offer:

```bash
python3 main.py offer \
  --address 0xPEER_ADDRESS \
  --encoding erasure
```

Request fragment custody:

```bash
python3 main.py request-custody \
  --publisher 0xPUBLISHER \
  --custodian 0xCUSTODIAN \
  --object-id 0xOBJECT_ID
```

Reconstruct from the distributed custody view:

```bash
python3 main.py reconstruct-network \
  --object-id 0xOBJECT_ID \
  --peer 0xCUSTODIAN
```

Renew an active custody claim:

```bash
python3 main.py renew-custody \
  --object-id 0xOBJECT_ID \
  --peer 0xCUSTODIAN
```

Repair a missing fragment:

```bash
python3 main.py repair-network \
  --object-id 0xOBJECT_ID \
  --peer 0xREPAIR_EXECUTOR \
  --new-custodian 0xNEW_CUSTODIAN
```

## Tests

Phase 1 behavior is covered with pytest.

```bash
python3 -m pytest -q
```

The suite covers healthy reconstruction, publisher loss, missing peers, corrupt fragments, missing fragments, expired custody, capacity exhaustion, recovery-threshold failure, repair executor enforcement, former-custodian re-entry, and successful redundancy restoration.

## Research Path

```text
Phase 1
Distributed static state
✓ complete

Phase 2
Dynamic state and versioning

Phase 3
Anvil-backed Ethereum state

Phase 4
Public Ethereum testnet
```

Phase 2 will ask whether the same storage model remains useful when canonical state changes over time and old fragments must be distinguished from current state.

## Repository

```text
state-fabric/
├── main.py
├── modules/
│   ├── wallets.py
│   ├── peers.py
│   ├── merkle.py
│   ├── storage.py
│   └── custody.py
├── tests/
└── README.md
```

`data/` contains generated runtime state and is not tracked in Git.
