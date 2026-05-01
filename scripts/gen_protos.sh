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

# Wrap the bare DESCRIPTOR = AddSerializedFile call in a try/except
# FindFileContainingSymbol fallback. Newer grpcio-tools (>=1.65) emit a bare
# call that raises on duplicate symbols; older versions emitted the wrapper.
# We need the wrapper because google-cloud-secret-manager (a dev dep, used by
# integration tests) ships its own copy of the same descriptors — both register
# google.cloud.secretmanager.v1.Secret in the global pool, and without the
# fallback the second registration aborts pytest collection across the suite.
python - <<'PY'
import pathlib, re
out = pathlib.Path('src/gcp_local/generated/google/cloud/secretmanager/v1')
fallback_symbols = {
    'resources_pb2.py': 'google.cloud.secretmanager.v1.Secret',
    'service_pb2.py': 'google.cloud.secretmanager.v1.SecretManagerService',
}
pattern = re.compile(
    r'^DESCRIPTOR = (_descriptor_pool\.Default\(\)\.AddSerializedFile\(.+?\))\n',
    re.MULTILINE | re.DOTALL,
)
for fname, symbol in fallback_symbols.items():
    p = out / fname
    text = p.read_text()
    m = pattern.search(text)
    if not m:
        continue  # already wrapped, or shape changed
    wrapper = (
        f"try:\n"
        f"  DESCRIPTOR = {m.group(1)}\n"
        f"except TypeError:\n"
        f"  DESCRIPTOR = _descriptor_pool.Default().FindFileContainingSymbol(\n"
        f"    '{symbol}'\n"
        f"  )\n"
    )
    p.write_text(text[:m.start()] + wrapper + text[m.end():])
    print(f'wrapped DESCRIPTOR in {p}')
PY

echo 'generated:'
ls -1 "src/gcp_local/generated/google/cloud/secretmanager/v1/"

# Pub/Sub (pubsub.proto + transitive schema.proto)
python -m grpc_tools.protoc \
  --proto_path=protos \
  --proto_path="$EXTRA_PROTO_PATH" \
  --python_out="$OUT" \
  --pyi_out="$OUT" \
  --grpc_python_out="$OUT" \
  protos/google/pubsub/v1/pubsub.proto \
  protos/google/pubsub/v1/schema.proto

python - <<'PY'
import pathlib, re
out = pathlib.Path('src/gcp_local/generated/google/pubsub/v1')
for p in out.glob('*.py'):
    text = p.read_text()
    new = re.sub(
        r'^from google\.pubsub\.v1 import',
        'from gcp_local.generated.google.pubsub.v1 import',
        text,
        flags=re.MULTILINE,
    )
    if new != text:
        p.write_text(new)
        print(f'rewrote imports in {p}')
PY

# Same descriptor-pool collision fallback as the secret_manager block above:
# google-cloud-pubsub is a dev dep used by integration tests, and proto-plus
# eagerly registers google.pubsub.v1.{Topic,SchemaView,...}. Wrap our pb2 files
# so the second AddSerializedFile call (whichever side wins the import race)
# falls back to FindFileContainingSymbol instead of aborting pytest collection.
python - <<'PY'
import pathlib, re
out = pathlib.Path('src/gcp_local/generated/google/pubsub/v1')
fallback_symbols = {
    'pubsub_pb2.py': 'google.pubsub.v1.Topic',
    'schema_pb2.py': 'google.pubsub.v1.Schema',
}
pattern = re.compile(
    r'^DESCRIPTOR = (_descriptor_pool\.Default\(\)\.AddSerializedFile\(.+?\))\n',
    re.MULTILINE | re.DOTALL,
)
for fname, symbol in fallback_symbols.items():
    p = out / fname
    text = p.read_text()
    m = pattern.search(text)
    if not m:
        continue  # already wrapped, or shape changed
    wrapper = (
        f"try:\n"
        f"  DESCRIPTOR = {m.group(1)}\n"
        f"except TypeError:\n"
        f"  DESCRIPTOR = _descriptor_pool.Default().FindFileContainingSymbol(\n"
        f"    '{symbol}'\n"
        f"  )\n"
    )
    p.write_text(text[:m.start()] + wrapper + text[m.end():])
    print(f'wrapped DESCRIPTOR in {p}')
PY

echo 'generated pubsub:'
ls -1 "src/gcp_local/generated/google/pubsub/v1/"

# Firestore v1 + admin/v1
python -m grpc_tools.protoc \
  --proto_path=protos \
  --proto_path="$EXTRA_PROTO_PATH" \
  --python_out="$OUT" \
  --pyi_out="$OUT" \
  --grpc_python_out="$OUT" \
  protos/google/firestore/v1/firestore.proto \
  protos/google/firestore/v1/document.proto \
  protos/google/firestore/v1/query.proto \
  protos/google/firestore/v1/write.proto \
  protos/google/firestore/v1/common.proto \
  protos/google/firestore/v1/aggregation_result.proto \
  protos/google/firestore/v1/bloom_filter.proto \
  protos/google/firestore/v1/explain_stats.proto \
  protos/google/firestore/v1/query_profile.proto \
  protos/google/firestore/v1/pipeline.proto \
  protos/google/firestore/admin/v1/firestore_admin.proto \
  protos/google/firestore/admin/v1/index.proto \
  protos/google/firestore/admin/v1/field.proto \
  protos/google/firestore/admin/v1/database.proto \
  protos/google/firestore/admin/v1/operation.proto \
  protos/google/firestore/admin/v1/backup.proto \
  protos/google/firestore/admin/v1/realtime_updates.proto \
  protos/google/firestore/admin/v1/schedule.proto \
  protos/google/firestore/admin/v1/snapshot.proto \
  protos/google/firestore/admin/v1/user_creds.proto

# Rewrite imports for firestore v1 files
python - <<'PY'
import pathlib, re
out = pathlib.Path('src/gcp_local/generated/google/firestore/v1')
for p in out.glob('*.py'):
    text = p.read_text()
    new = re.sub(
        r'^from google\.firestore\.v1 import',
        'from gcp_local.generated.google.firestore.v1 import',
        text,
        flags=re.MULTILINE,
    )
    if new != text:
        p.write_text(new)
        print(f'rewrote imports in {p}')
PY

# Rewrite imports for firestore admin/v1 files
python - <<'PY'
import pathlib, re
out = pathlib.Path('src/gcp_local/generated/google/firestore/admin/v1')
for p in out.glob('*.py'):
    text = p.read_text()
    new = re.sub(
        r'^from google\.firestore\.admin\.v1 import',
        'from gcp_local.generated.google.firestore.admin.v1 import',
        text,
        flags=re.MULTILINE,
    )
    if new != text:
        p.write_text(new)
        print(f'rewrote imports in {p}')
PY

# Descriptor-pool collision wrapper for firestore v1 pb2 files.
# google-cloud-firestore (dev dep used by integration tests) ships its own
# copies of these descriptors. Without the try/except fallback the second
# AddSerializedFile call aborts pytest collection across the suite.
python - <<'PY'
import pathlib, re
out = pathlib.Path('src/gcp_local/generated/google/firestore/v1')
fallback_symbols = {
    'firestore_pb2.py':          'google.firestore.v1.GetDocumentRequest',
    'document_pb2.py':           'google.firestore.v1.Document',
    'query_pb2.py':              'google.firestore.v1.StructuredQuery',
    'write_pb2.py':              'google.firestore.v1.Write',
    'common_pb2.py':             'google.firestore.v1.DocumentMask',
    'aggregation_result_pb2.py': 'google.firestore.v1.AggregationResult',
    'bloom_filter_pb2.py':       'google.firestore.v1.BloomFilter',
    'explain_stats_pb2.py':      'google.firestore.v1.ExplainStats',
    'query_profile_pb2.py':      'google.firestore.v1.ExplainOptions',
    'pipeline_pb2.py':           'google.firestore.v1.StructuredPipeline',
}
pattern = re.compile(
    r'^DESCRIPTOR = (_descriptor_pool\.Default\(\)\.AddSerializedFile\(.+?\))\n',
    re.MULTILINE | re.DOTALL,
)
for fname, symbol in fallback_symbols.items():
    p = out / fname
    if not p.exists():
        continue
    text = p.read_text()
    m = pattern.search(text)
    if not m:
        continue  # already wrapped, or shape changed
    wrapper = (
        f"try:\n"
        f"  DESCRIPTOR = {m.group(1)}\n"
        f"except TypeError:\n"
        f"  DESCRIPTOR = _descriptor_pool.Default().FindFileContainingSymbol(\n"
        f"    '{symbol}'\n"
        f"  )\n"
    )
    p.write_text(text[:m.start()] + wrapper + text[m.end():])
    print(f'wrapped DESCRIPTOR in {p}')
PY

# Descriptor-pool collision wrapper for firestore admin/v1 pb2 files.
python - <<'PY'
import pathlib, re
out = pathlib.Path('src/gcp_local/generated/google/firestore/admin/v1')
fallback_symbols = {
    'firestore_admin_pb2.py':    'google.firestore.admin.v1.GetIndexRequest',
    'index_pb2.py':              'google.firestore.admin.v1.Index',
    'field_pb2.py':              'google.firestore.admin.v1.Field',
    'database_pb2.py':           'google.firestore.admin.v1.Database',
    'operation_pb2.py':          'google.firestore.admin.v1.IndexOperationMetadata',
    'backup_pb2.py':             'google.firestore.admin.v1.Backup',
    'realtime_updates_pb2.py':   'google.firestore.admin.v1.RealtimeUpdatesMode',
    'schedule_pb2.py':           'google.firestore.admin.v1.BackupSchedule',
    'snapshot_pb2.py':           'google.firestore.admin.v1.PitrSnapshot',
    'user_creds_pb2.py':         'google.firestore.admin.v1.UserCreds',
}
pattern = re.compile(
    r'^DESCRIPTOR = (_descriptor_pool\.Default\(\)\.AddSerializedFile\(.+?\))\n',
    re.MULTILINE | re.DOTALL,
)
for fname, symbol in fallback_symbols.items():
    p = out / fname
    if not p.exists():
        continue
    text = p.read_text()
    m = pattern.search(text)
    if not m:
        continue  # already wrapped, or shape changed
    wrapper = (
        f"try:\n"
        f"  DESCRIPTOR = {m.group(1)}\n"
        f"except TypeError:\n"
        f"  DESCRIPTOR = _descriptor_pool.Default().FindFileContainingSymbol(\n"
        f"    '{symbol}'\n"
        f"  )\n"
    )
    p.write_text(text[:m.start()] + wrapper + text[m.end():])
    print(f'wrapped DESCRIPTOR in {p}')
PY

echo 'generated firestore:'
ls -1 "src/gcp_local/generated/google/firestore/v1/"
ls -1 "src/gcp_local/generated/google/firestore/admin/v1/"
