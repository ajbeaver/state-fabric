# State Fabric

State Fabric is a research simulator for distributing authenticated state across peers, reconstructing it after failures, and verifying it against an externally trusted canonical root.

**Research question:** Can a distributed storage fabric keep state recoverable and independently verifiable without every participant storing the full state?

## Status

- **Phase 1 complete:** 2-of-5 erasure-coded custody, reconstruction, renewal, and repair.
- **Phase 2 complete:** canonical transitions, sparse per-address versions, retention, and transition failure behavior.
- **Phase 2+ active:** separating stable state-value bytes, retained authenticated commitment structure, and regenerable witnesses.
- **Phase 3:** Anvil integration.
- **Phase 4:** public testnet experiments.

The new Phase 2+ value and authenticated-node stores are currently **local reference stores**. Their migration into distributed custody remains future work. The existing distributed custody experiment still uses the legacy root-bound state package.

## CLI

```bash
python3 main.py init --peers 7
python3 main.py commit
python3 main.py verify
python3 main.py run
```

`run` executes the research lifecycle and checks its invariants. These are the current human-facing commands; custody and repair primitives remain available in Python modules.

## Tests

```bash
python3 -m pytest -v
```

See [docs/concept.md](docs/concept.md) for the architecture and research rationale. Generated runtime state lives in `data/`.
