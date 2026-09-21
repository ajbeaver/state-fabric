#!/bin/zsh

set -euo pipefail

repo_dir=${0:A:h:h}
python_bin="$repo_dir/venv/bin/python"
test_dir=$(mktemp -d)

cleanup() {
    rm -rf "$test_dir"
}

trap cleanup EXIT

cd "$test_dir"

"$python_bin" "$repo_dir/main.py" init --peers 6
"$python_bin" "$repo_dir/main.py" commit

peers=(data/peers/*)
publisher=${peers[1]:t}
custodians=(
    ${peers[2]:t}
    ${peers[3]:t}
    ${peers[4]:t}
    ${peers[5]:t}
    ${peers[6]:t}
)

"$python_bin" "$repo_dir/main.py" offer \
    --address "$publisher" \
    --encoding erasure

offers=("data/peers/$publisher/offers"/*)
object_id=${offers[1]:t}

for custodian in "${custodians[@]}"; do
    "$python_bin" "$repo_dir/main.py" request-custody \
        --publisher "$publisher" \
        --custodian "$custodian" \
        --object-id "$object_id"

    test -f "data/peers/$custodian/data/$object_id/manifest.json"
    test -f "data/peers/$custodian/data/$object_id/custody.json"
done

rm -rf "data/peers/$publisher"

"$python_bin" "$repo_dir/main.py" renew-custody \
    --object-id "$object_id" \
    --peer "${custodians[2]}"

"$python_bin" - "$object_id" <<'PY'
import json
import pathlib
import sys

object_id = sys.argv[1]
paths = pathlib.Path("data/peers").glob(
    f"*/data/{object_id}/custody.json"
)

for path in paths:
    custody = json.loads(path.read_text())
    custody["0"]["expires_at"] = "2000-01-01T00:00:00Z"
    path.write_text(
        json.dumps(custody, indent=2, sort_keys=True) + "\n"
    )
PY

executor=$("$python_bin" - "$object_id" <<'PY'
import datetime
import json
import pathlib
import sys

object_id = sys.argv[1]
path = next(
    pathlib.Path("data/peers").glob(
        f"*/data/{object_id}/custody.json"
    )
)
custody = json.loads(path.read_text())
now = datetime.datetime.now(datetime.timezone.utc)
active = [
    claim["custodian"]
    for claim in custody.values()
    if (
        claim["status"] == "leased"
        and datetime.datetime.fromisoformat(
            claim["expires_at"].replace("Z", "+00:00")
        ) > now
    )
]

assert len(active) == 4, active
print(min(active, key=str.lower))
PY
)

"$python_bin" "$repo_dir/main.py" repair-network \
    --object-id "$object_id" \
    --peer "$executor" \
    --new-custodian "${custodians[1]}"

test -f "data/peers/${custodians[1]}/data/$object_id/000.bin"
test -f "data/peers/${custodians[1]}/data/$object_id/manifest.json"
test -f "data/peers/${custodians[1]}/data/$object_id/lease.json"
test -f "data/peers/${custodians[1]}/data/$object_id/custody.json"

"$python_bin" - "$object_id" "$executor" "${custodians[1]}" <<'PY'
import datetime
import json
import pathlib
import sys

object_id = sys.argv[1]
executor = sys.argv[2]
repaired_custodian = sys.argv[3]
path = (
    pathlib.Path("data/peers")
    / executor
    / "data"
    / object_id
    / "custody.json"
)
custody = json.loads(path.read_text())
now = datetime.datetime.now(datetime.timezone.utc)
active = [
    claim
    for claim in custody.values()
    if (
        claim["status"] == "leased"
        and datetime.datetime.fromisoformat(
            claim["expires_at"].replace("Z", "+00:00")
        ) > now
    )
]

assert len(active) == 5, active
assert sum(
    claim["custodian"].lower() == repaired_custodian.lower()
    for claim in active
) == 1, active
PY

"$python_bin" "$repo_dir/main.py" reconstruct-network \
    --object-id "$object_id" \
    --peer "$executor"

print "Custody renewal and repair test passed"
