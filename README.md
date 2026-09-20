# State Fabric

State Fabric is a small research simulator exploring whether cryptographically verifiable state can be distributed across unreliable, heterogeneous peers without requiring every participant to retain the complete state.

The project starts with a deliberately simplified model. It does not initially interact with Ethereum, real peer-to-peer networks, or production infrastructure.

The goal is to understand the underlying problem first.

## Research Question

Can a client reconstruct requested state from unreliable distributed peers and independently verify that the reconstructed data belongs to a known canonical state root?

The important properties are:

* state can be stored across multiple peers
* individual peers can disappear or return incorrect data
* a client does not need to trust the peer providing the data
* retrieved state can be independently verified against a known root

## Motivation

Large distributed systems often assume that sufficiently capable machines retain large portions of globally relevant state.

State Fabric explores a different question:

What happens if state is treated as something that can be distributed, reconstructed, and verified on demand?

Instead of starting with Ethereum itself, this project models the underlying properties in a controlled environment.

The first version uses fake accounts, simulated peers, and a simple Merkle tree.

Later experiments may replace those abstractions with systems that more closely resemble real decentralized networks.

## Phase 1 — Verifiable State

The first phase establishes the cryptographic foundation.

Generate a deterministic dataset of fake accounts:

```text
alice   3.0
bob     1.2
carol   18.4
```

Each account is serialized deterministically and hashed.

Those hashes become leaves in a Merkle tree:

```text
account records
      |
      v
    hashes
      |
      v
 Merkle tree
      |
      v
 STATE ROOT
```

A client must then be able to request an account and verify it using only:

```text
account record
Merkle proof
state root
```

The client should not need access to the complete dataset during verification.

### Phase 1 completion condition

```text
generate deterministic accounts
        |
build Merkle tree
        |
calculate state root
        |
request arbitrary account
        |
generate proof
        |
verify against state root
        |
modify account data
        |
verification fails
```

A successful Phase 1 proves only that individual state objects can be independently verified against a shared root.

It does not yet prove anything about distributed storage.

## Phase 2 — Distributed Storage

Phase 2 introduces simulated peers.

No real networking is required.

A peer is simply an object with limited storage and a collection of state objects.

Example:

```text
peer01   phone    small
peer02   phone    small
peer03   laptop   medium
peer04   server   large
peer05   server   large
```

State is replicated across several peers:

```text
alice
├── peer01
├── peer04
└── peer05
```

The requesting client should not directly know where an account is stored.

Conceptually:

```text
request account
      |
locate candidate peers
      |
retrieve object
      |
retrieve proof
      |
verify against known root
```

## Phase 3 — Failure Simulation

Once basic distributed retrieval works, peers begin failing.

Experiments may include:

```text
peer unavailable

peer refuses request

peer returns corrupted state

replica disappears
```

The simulator should record a small set of useful measurements:

```text
recovery success rate
peers contacted
bytes transferred
verification failures
```

Initial tests should examine increasing peer loss:

```text
0%
10%
30%
50%
70%
```

The purpose is not to prove that one replication strategy is optimal.

The purpose is to understand how availability, redundancy, and verification interact.

## Phase 4 — Fragmentation and Recovery

Replication stores complete copies of an object.

The next experiment removes that assumption.

A larger object can first be divided into fixed-size chunks:

```text
object
  |
  +-- chunk 0
  +-- chunk 1
  +-- chunk 2
  +-- chunk 3
```

Those chunks can then be distributed independently.

Later, simple chunking can be replaced with erasure coding:

```text
original object
       |
 erasure encode
       |
many fragments
       |
some disappear
       |
enough remain
       |
 reconstruct
       |
 verify
```

At this point the system no longer asks:

> Which peer has this object?

It begins asking:

> Can the network collectively provide enough verified information to reconstruct this object?

That is the primary research direction of the project.

## Initial Scope

The first versions intentionally do not include:

```text
Geth
Ethereum RPC
libp2p
DHTs
real network sockets
real Ethereum nodes
Ethereum's Merkle Patricia Trie
performance optimization
production deployment
```

These are not rejected technologies.

They are intentionally deferred until the simplified model produces useful results.

## Repository Structure

Initial structure:

```text
state-fabric/
├── state.py
├── merkle.py
├── peer.py
├── network.py
├── experiments.py
└── README.md
```

Not every file needs to exist immediately.

Phase 1 should begin with only the components required to:

```text
generate state
→ hash state
→ build a root
→ generate a proof
→ verify the proof
```

## Development Principles

Keep the simulator small.

Prefer deterministic behavior where possible so experiments can be reproduced.

Avoid introducing networking infrastructure before networking is part of the research question.

Treat corrupted or malicious peer responses as expected behavior rather than exceptional behavior.

Verification should happen at the client boundary. A peer providing data should never need to be trusted simply because it successfully responded.

## Current Status

```text
Phase 1 — Verifiable State            planned
Phase 2 — Distributed Storage         planned
Phase 3 — Failure Simulation          planned
Phase 4 — Fragmentation and Recovery  planned
```

The immediate milestone is simple:

```text
10,000 deterministic accounts
        |
Merkle root
        |
one requested account
        |
Merkle proof
        |
independent verification
```

Everything else builds from there.
