# Deployment

This guide covers running `gcp-local` via Docker, docker-compose, and Kubernetes (with a section dedicated to Rancher Desktop). For per-service usage details, see [`docs/services/`](services/).

> **Heads-up:** No image is published to a registry yet. You always build from source.

## Default ports

| Component       | Port | Notes |
|-----------------|------|-------|
| Admin API       | 4510 | `/_emulator/health`, `/_emulator/services`, `/_emulator/reset` |
| GCS             | 4443 | REST; client honors `STORAGE_EMULATOR_HOST` |
| BigQuery        | 9050 | REST; client honors `BIGQUERY_EMULATOR_HOST` |
| Secret Manager  | 8086 | gRPC; no standard env var (use `client_options.api_endpoint`) |
| Pub/Sub         | 8085 | gRPC; client honors `PUBSUB_EMULATOR_HOST` |
| Firestore       | 8080 | gRPC; client honors `FIRESTORE_EMULATOR_HOST` |

## Building the image

```bash
docker build -f docker/Dockerfile -t gcp-local:dev .
```

The Dockerfile is `python:3.13-slim` plus `pip install .`, exposes the admin port, and declares `/data` as a volume. Pin the tag however you like; CI uses `gcp-local:dev`.

## Running with `docker run`

### All services, ephemeral

```bash
docker run --rm \
  -p 4510:4510 \
  -p 4443:4443 \
  -p 8086:8086 \
  -p 9050:9050 \
  gcp-local:dev
```

Health check:

```bash
curl http://localhost:4510/_emulator/health
```

### Pick a subset of services

`SERVICES` is a comma-separated allowlist. Other services don't initialize and their ports never bind, so you only need to publish the ports you care about:

```bash
docker run --rm \
  -e SERVICES=gcs,bigquery \
  -p 4510:4510 \
  -p 4443:4443 \
  -p 9050:9050 \
  gcp-local:dev
```

### Persist state to disk

`PERSIST=1` writes state under `/data` inside the container. Mount a volume so it survives restarts:

```bash
docker run --rm \
  -e PERSIST=1 \
  -v gcp-local-data:/data \
  -p 4510:4510 -p 4443:4443 -p 8086:8086 -p 9050:9050 \
  gcp-local:dev
```

Layout under `/data`:

- `gcs/<bucket>/<object>` plus `.meta.json` sidecars
- `bigquery.duckdb`
- `secret_manager/secrets.json`

BigQuery **job records** are in-memory only — they don't survive a container restart even with `PERSIST=1`. Datasets, tables, and rows do.

### Override a service port

Each service honors `<NAME>_EMULATOR_PORT`:

```bash
docker run --rm \
  -e BIGQUERY_EMULATOR_PORT=19050 \
  -p 4510:4510 -p 19050:19050 \
  gcp-local:dev
```

### Reset state without restarting

```bash
# everything
curl -X POST http://localhost:4510/_emulator/reset

# a single service
curl -X POST 'http://localhost:4510/_emulator/reset?service=bigquery'
```

## docker-compose

```yaml
# docker-compose.yml
services:
  gcp-local:
    image: gcp-local:dev
    build:
      context: .
      dockerfile: docker/Dockerfile
    environment:
      SERVICES: gcs,bigquery,secret_manager
      PERSIST: "1"
    ports:
      - "4510:4510"   # admin
      - "4443:4443"   # gcs
      - "9050:9050"   # bigquery
      - "8086:8086"   # secret manager
    volumes:
      - gcp-local-data:/data
    healthcheck:
      test: ["CMD", "curl", "-fsS", "http://localhost:4510/_emulator/health"]
      interval: 5s
      timeout: 2s
      retries: 10

volumes:
  gcp-local-data:
```

## Kubernetes

The emulator is a single-process stateful service. State lives in-process; persistence (when enabled) writes to `/data`. Run it as a single replica.

### Sample manifest

```yaml
# gcp-local.yaml
apiVersion: v1
kind: PersistentVolumeClaim
metadata:
  name: gcp-local-data
spec:
  accessModes: ["ReadWriteOnce"]
  resources:
    requests:
      storage: 1Gi
---
apiVersion: apps/v1
kind: Deployment
metadata:
  name: gcp-local
  labels:
    app: gcp-local
spec:
  replicas: 1
  strategy:
    type: Recreate          # state is in-process; rolling updates would split traffic
  selector:
    matchLabels:
      app: gcp-local
  template:
    metadata:
      labels:
        app: gcp-local
    spec:
      containers:
        - name: gcp-local
          image: gcp-local:dev
          imagePullPolicy: IfNotPresent     # locally-built image; not in a registry
          env:
            - name: SERVICES
              value: "gcs,bigquery,secret_manager"
            - name: PERSIST
              value: "1"
          ports:
            - { name: admin,    containerPort: 4510 }
            - { name: gcs,      containerPort: 4443 }
            - { name: bigquery, containerPort: 9050 }
            - { name: secrets,  containerPort: 8086 }
          volumeMounts:
            - name: data
              mountPath: /data
          readinessProbe:
            httpGet:
              path: /_emulator/health
              port: admin
            initialDelaySeconds: 2
            periodSeconds: 5
          livenessProbe:
            httpGet:
              path: /_emulator/health
              port: admin
            initialDelaySeconds: 10
            periodSeconds: 15
      volumes:
        - name: data
          persistentVolumeClaim:
            claimName: gcp-local-data
---
apiVersion: v1
kind: Service
metadata:
  name: gcp-local
spec:
  selector:
    app: gcp-local
  ports:
    - { name: admin,    port: 4510, targetPort: admin }
    - { name: gcs,      port: 4443, targetPort: gcs }
    - { name: bigquery, port: 9050, targetPort: bigquery }
    - { name: secrets,  port: 8086, targetPort: secrets }
```

Apply:

```bash
kubectl apply -f gcp-local.yaml
kubectl rollout status deploy/gcp-local
```

## Rancher Desktop

Rancher Desktop runs Kubernetes (k3s) on top of either **dockerd** or **containerd**, selectable in **Settings → Container Engine**. The image-build command differs.

### dockerd backend

The Docker socket and the Kubernetes node share the same image store. Standard build works as-is:

```bash
docker build -f docker/Dockerfile -t gcp-local:dev .
kubectl apply -f gcp-local.yaml
```

### containerd backend

The kubelet looks up images in containerd's `k8s.io` namespace. A bare `nerdctl build` lands in the default namespace, where kubelet can't see it. Build into the right namespace:

```bash
nerdctl --namespace k8s.io build -f docker/Dockerfile -t gcp-local:dev .
kubectl apply -f gcp-local.yaml
```

If you forget the namespace flag, the pod fails with `ErrImageNeverPull`/`ImagePullBackOff` because `imagePullPolicy: IfNotPresent` and the image is invisible to kubelet.

### Reaching the emulator from your host

Two options:

**Port-forward** — simplest, no ingress:

```bash
kubectl port-forward svc/gcp-local 4510:4510 4443:4443 9050:9050 8086:8086
```

Clients on the host then talk to `localhost:<port>` as if running locally.

**Traefik ingress** (Rancher Desktop ships Traefik on the default profile) — useful if you want a hostname:

```yaml
apiVersion: networking.k8s.io/v1
kind: Ingress
metadata:
  name: gcp-local-admin
spec:
  rules:
    - host: gcp-local.localhost
      http:
        paths:
          - path: /
            pathType: Prefix
            backend:
              service:
                name: gcp-local
                port:
                  number: 4510
```

(The official Google client libraries authenticate against `localhost:<port>`-style endpoints rather than HTTP `Host` headers, so for client traffic port-forward is usually less friction.)

## Connecting clients

### From the host (out of cluster)

```bash
export STORAGE_EMULATOR_HOST=http://localhost:4443
export BIGQUERY_EMULATOR_HOST=localhost:9050
# Secret Manager has no standard env var — see docs/services/secret_manager when written.
```

Per-service connection details (Python snippets, gotchas) live in `docs/services/<svc>.md`.

### From another pod (in cluster)

Use the Kubernetes Service DNS name:

```bash
STORAGE_EMULATOR_HOST=http://gcp-local.default.svc.cluster.local:4443
BIGQUERY_EMULATOR_HOST=gcp-local.default.svc.cluster.local:9050
```

Replace `default` with whatever namespace you deployed into.

## Health and observability

```bash
# Overall + per-service status
curl http://<host>:4510/_emulator/health

# List running services
curl http://<host>:4510/_emulator/services
```

Container logs:

```bash
docker logs -f <container-id>
# or
kubectl logs -f deploy/gcp-local
```

## Limitations

- **No published image.** You build from source. A future release will publish to a registry.
- **No TLS.** All emulator endpoints are plain HTTP / insecure gRPC. Clients must use `AnonymousCredentials` (Python) or insecure channels.
- **Single replica only.** State is in-process; running multiple pods means inconsistent state. Use `strategy: Recreate`.
- **No clustering / no HA.** Pod restart loses BigQuery job history (data persists with `PERSIST=1`); Pub/Sub and Firestore (when added) will follow the same model.
- **Resources.** No CPU/memory limits set in the sample manifest. BigQuery in particular pulls DuckDB into memory; size the pod accordingly if you load big tables. For local dev the defaults are fine.
- **Auth/IAM is a no-op.** Any token (or no token) is accepted; project IDs are not validated. Don't use this for testing IAM-related code paths.
