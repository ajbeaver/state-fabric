# State Fabric

State Fabric is a research simulator exploring whether authenticated Ethereum-like state can be distributed across heterogeneous peers, reconstructed on demand, and independently verified without requiring every participant to retain the complete state.

The project is intentionally starting below the Ethereum protocol layer.

Before integrating with a real execution client, State Fabric isolates the underlying storage problem:

> Can canonical state be fragmented across unreliable peers, reconstructed from only a subset of those fragments, and still be cryptographically verified against a trusted state root?

The current implementation is a local Python experiment. It does not modify Ethereum, participate in consensus, or run a real peer-to-peer network.

## Core Idea

A State Fabric peer represents a participating device.

Each peer:

- is identified by an Ethereum address
- has a local cached view of its own state
- declares how many bytes of storage it is willing to contribute
- can eventually store fragments belonging to other participants

Conceptually:

```text
peers/
└── 0xPEER_ADDRESS/
    ├── capacity
    ├── cache/
    │   └── self/
    │       ├── balance
    │       ├── nonce
    │       └── proof.json
    ├── data/
    └── offers/
```

The peer's local cache is convenient, but it is not authoritative.

Canonical truth is represented by a cryptographic state root.

The long-term goal is for state to remain recoverable even if the peer associated with that state is completely unavailable.

## Trust Model

State Fabric separates storage from truth.

A peer storing or serving data does not need to be trusted.

Validation currently occurs in several layers:

```text
fragment hash
      ↓
Was this fragment received intact?

object hash
      ↓
Did these fragments reconstruct the exact original object?

Merkle proof
      ↓
Does the reconstructed state belong to the canonical state root?
```

A large number of peers agreeing on incorrect state does not make that state valid.

The independently trusted state root remains the authority used for verification.

## Current State Model

Each simulated participant currently has a minimal Ethereum-like state record:

```text
address
balance
nonce
```

Addresses are deterministically derived Ethereum addresses.

Balances are stored as integer wei values.

Nonces are integer transaction counters.

The simulator produces deterministic state so the same seed produces the same peers, state, and resulting state root.

## Canonical State

Peer state is serialized deterministically and hashed with Keccak-256.

Those hashes become leaves in a Merkle tree:

```text
peer state
    ↓
Keccak-256
    ↓
leaf hashes
    ↓
Merkle tree
    ↓
STATE ROOT
```

`commit` writes the resulting root to:

```text
data/reference/state_root
```

It also places the appropriate Merkle proof into each peer's local cache.

A peer can therefore verify its cached state using only:

```text
address
balance
nonce
Merkle proof
trusted state root
```

Changing even one balance or nonce causes verification against the existing root to fail.

## State Packages

Before state is fragmented, it is converted into a deterministic binary State Fabric State Package.

Version 1 contains:

```text
magic
version
state root
Ethereum address
balance
nonce
Merkle proof
```

The complete package is hashed with Keccak-256.

That hash becomes the object's content identifier:

```text
state package bytes
        ↓
    Keccak-256
        ↓
     object_id
```

For the current five-peer experiment, one package is approximately 198 bytes.

The package contains everything necessary to verify the recovered state except the independently trusted state root.

## Fragmentation

State Fabric currently implements two storage experiments.

### Plain Striping

The package can be divided into ordinary sequential fragments.

For example:

```text
198-byte package
      ↓
50 bytes
50 bytes
50 bytes
48 bytes
```

All fragments are required for reconstruction.

This behaves like a simplified RAID 0 control experiment:

```text
4 fragments available
→ reconstruction succeeds

1 fragment lost
→ reconstruction fails
```

This establishes the baseline cost of distributing data without redundancy.

### 2-of-5 Erasure Coding

The current recovery experiment encodes two data shards into five total fragments over GF(256).

```text
original object
      ↓
2 data components
      ↓
5 encoded fragments
```

Any two valid fragments can recover the complete package.

The experiment has demonstrated:

```text
5 fragments
→ recover

2 fragments
→ recover

1 fragment
→ fail
```

After reconstruction, State Fabric verifies:

1. the reconstructed object's Keccak hash
2. the embedded state package
3. the Merkle proof against the trusted state root

The current erasure-code implementation exists for the research simulator. It is not intended as a production cryptographic or storage library.

## Offers

A peer preparing state for distribution creates an offer:

```text
peers/0xPEER_ADDRESS/
└── offers/
    └── 0xOBJECT_ID/
        ├── manifest.json
        └── fragments/
            ├── 000.bin
            ├── 001.bin
            ├── 002.bin
            ├── 003.bin
            └── 004.bin
```

`manifest.json` describes:

- object identity
- associated address and state root
- original object size
- encoding scheme
- number of required and total fragments
- size and Keccak hash of each fragment

The manifest helps peers validate fragments and reconstruct an object.

It does not itself establish canonical truth.

## Peer Capacity

Every simulated peer declares a storage contribution in bytes.

Current deterministic test levels are:

```text
64 KiB
64 MiB
1 GiB
```

The storage layer treats these only as byte budgets. It does not need to know whether the participant is intended to represent a watch, phone, laptop, or server.

Conceptually:

```text
capacity
- bytes stored under data/
= available capacity
```

A future receiving peer should only accept a fragment when that fragment fits within its remaining contribution.

This models the broader idea that heterogeneous devices could contribute different amounts of storage without requiring each device to retain the complete state.

## The Fabric

State Fabric is not intended to be a centralized storage coordinator.

The planned model is pull-oriented.

A peer with verified state creates fragments and advertises an offer.

Other peers:

```text
discover offer
      ↓
inspect manifest
      ↓
choose a fragment
      ↓
check local capacity
      ↓
pull fragment
      ↓
verify fragment hash
      ↓
store locally
      ↓
advertise possession
```

The storage owner controls its own disk.

The eventual "fabric" is the protocol formed by peers discovering, storing, serving, verifying, and repairing fragments.

Real networking and decentralized discovery are intentionally deferred until the storage behavior itself is understood.

## CLI

Initialize a deterministic simulated network:

```bash
python3 main.py init --peers 5
```

Commit its current state:

```bash
python3 main.py commit
```

Verify one peer's cached state:

```bash
python3 main.py verify --address 0xPEER_ADDRESS
```

Create an erasure-coded offer:

```bash
python3 main.py offer \
  --address 0xPEER_ADDRESS \
  --encoding erasure
```

Reconstruct the state package:

```bash
python3 main.py reconstruct \
  --address 0xPEER_ADDRESS
```

Delete a fragment for failure testing:

```bash
python3 main.py drop-fragment \
  --address 0xPEER_ADDRESS \
  --index 2
```

Plain striping remains available as a control:

```bash
python3 main.py offer \
  --address 0xPEER_ADDRESS \
  --encoding stripe \
  --fragments 4
```

## Research Phases

### Phase 1 — Static Authenticated Storage

Establish the storage primitives independently of Ethereum.

Completed:

```text
✓ deterministic Ethereum-address peers
✓ heterogeneous local capacity
✓ deterministic state serialization
✓ Keccak state hashing
✓ Merkle state root
✓ independent Merkle verification
✓ deterministic binary state package
✓ content-addressed object identity
✓ plain striping and reconstruction
✓ fragment integrity hashes
✓ 2-of-5 erasure recovery
✓ verification after reconstruction
✓ failure when recovery threshold is lost
```

Remaining work includes physically distributing fragments into independent peer `data/` directories, enforcing capacity during acceptance, removing the publisher from the recovery path, rejecting corrupted fragments, and recovering exclusively from surviving peers.

The Phase 1 completion test is:

```text
peer publishes authenticated state
        ↓
fragments move to independent peers
        ↓
publisher disappears
        ↓
multiple fragment holders disappear
        ↓
threshold fragments survive
        ↓
state reconstructs
        ↓
object hash verifies
        ↓
Merkle proof verifies
        ↓
canonical state recovered
```

### Phase 2 — Dynamic State

Static state is only the storage primitive.

The next problem is state that continuously changes.

The first dynamic experiments should establish:

```text
root N
→ state transition
→ root N+1

old fragments
→ remain valid for root N
→ cannot authenticate against root N+1

new fragments
→ authenticate against root N+1
```

This phase introduces state versioning, fragment replacement, stale-state detection, repair, and retirement.

### Phase 3 — Anvil

Once dynamic-state mechanics are understood, replace the toy state transitions with a local Ethereum execution environment using Anvil.

Complexity can increase progressively:

```text
ETH transfers
→ ERC-20 state
→ contract storage
→ many accounts
→ many contracts
→ sustained transaction traffic
```

State Fabric remains outside consensus.

Anvil produces the canonical Ethereum state transitions and roots. State Fabric experiments with storing and recovering the authenticated state associated with them.

Important measurements will include:

- time from a new root to sufficient fragment availability
- storage overhead
- recovery success rate
- stale fragment volume
- repair bandwidth
- bytes redistributed per state transition

### Phase 4 — Public Testnet

After the system can keep up with deliberately stressful Anvil workloads, attach it to an appropriate public Ethereum testnet.

At that stage the workload is no longer controlled by the experiment.

The question becomes whether the same storage model can follow externally produced Ethereum state under unpredictable activity and network conditions.

Sepolia is a likely candidate, subject to the state of Ethereum testnets when this phase begins.

## Out of Scope for Now

State Fabric is not currently attempting to solve:

```text
Ethereum consensus
validator economics
real P2P transport
DHT discovery
geographic placement
latency optimization
proximity-weighted retrieval
production erasure coding
Sybil resistance
incentives
production deployment
```

Those may become relevant only if the underlying storage model continues to hold up experimentally.

## Repository Structure

Current implementation:

```text
state-fabric/
├── main.py
├── modules/
│   ├── wallets.py
│   ├── peers.py
│   ├── merkle.py
│   └── storage.py
├── data/
│   ├── peers/
│   └── reference/
├── README.md
└── TODO.md
```

The generated `data/` tree is the experimental environment.

## Current Result

The project has demonstrated the underlying recovery primitive on static simulated state:

```text
canonical peer state
        ↓
Merkle authenticated package
        ↓
2-of-5 erasure encoding
        ↓
5 independent fragments
        ↓
3 fragments destroyed
        ↓
2 surviving fragments
        ↓
exact package reconstruction
        ↓
object hash verified
        ↓
Merkle proof verified
        ↓
original canonical state recovered
```

With only one fragment remaining, reconstruction fails as expected.

The next milestone is to move those fragments off the publishing peer and into the capacity-limited storage directories of independent peers so that recovery no longer depends on the publisher at all.
