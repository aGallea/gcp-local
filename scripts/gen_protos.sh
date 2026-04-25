#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."

OUT="src/gcp_local/generated"
mkdir -p "$OUT"

# Find the site-packages dir that contains the google/api protos
# (from googleapis-common-protos). We add it to the proto path so
# imports like google/api/annotations.proto resolve.
EXTRA_PROTO_PATH="$(python -c 'import google.api; import os; print(os.path.dirname(os.path.dirname(list(google.api.__path__)[0])))')"

python -m grpc_tools.protoc \
  --proto_path=protos \
  --proto_path="$EXTRA_PROTO_PATH" \
  --python_out="$OUT" \
  --pyi_out="$OUT" \
  --grpc_python_out="$OUT" \
  protos/google/cloud/secretmanager/v1/resources.proto \
  protos/google/cloud/secretmanager/v1/service.proto

# grpcio-tools emits imports as `from google.cloud.secretmanager.v1 import ...`.
# Our generated files live under `gcp_local.generated.google.cloud.secretmanager.v1`.
# Rewrite the import lines so they resolve inside our package tree.
python - <<'PY'
import pathlib, re
out = pathlib.Path('src/gcp_local/generated/google/cloud/secretmanager/v1')
for p in out.glob('*.py'):
    text = p.read_text()
    new = re.sub(
        r'^from google\.cloud\.secretmanager\.v1 import',
        'from gcp_local.generated.google.cloud.secretmanager.v1 import',
        text,
        flags=re.MULTILINE,
    )
    if new != text:
        p.write_text(new)
        print(f'rewrote imports in {p}')
PY

echo 'generated:'
ls -1 "src/gcp_local/generated/google/cloud/secretmanager/v1/"
