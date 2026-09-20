# Kubernetes / GKE deployment

These manifests run the FastAPI Meeting Insights Agent as a stateless workload.
The service endpoint is internal (`ClusterIP`); expose it through the team's
Ingress or Gateway rather than assigning every pod a public IP.

## What is included

- `deployment.yaml`: two API replicas, `/health` readiness and liveness probes,
  a 256 MiB ephemeral sandbox, CPU/memory requests and limits, and a restricted
  container security context.
- `service.yaml`: internal HTTP service on port 80.
- `configmap.yaml`: non-secret agent and Qdrant runtime settings.
- `configmap.kind.yaml`: local-kind override that forces the LangGraph
  pipeline when the optional Claude Agent SDK cannot run in that container.
- `secret.example.yaml`: a credential **template only**. Never apply it with
  placeholder values or commit a populated secret file.
- `hpa.yaml`: CPU-based autoscaling from 2 to 8 pods. It requires Metrics Server
  (enabled by default on GKE).
- `serviceaccount.yaml`: workload service account. It does not mount the legacy
  Kubernetes API token because this service does not call the Kubernetes API.

The deployment expects a Qdrant-compatible service called `qdrant` on port
`6333` in the same namespace. Change `QDRANT_HOST` in `configmap.yaml` if it is
managed elsewhere.

`GROQ_VISION_MODEL` is set to `qwen/qwen3.8-27b`. Confirm that the Groq API key
for each environment is entitled to that model by listing its authenticated
`/models` endpoint; model access can differ by account or plan.

## Prepare an image

Build and push the existing project `Dockerfile` to a trusted registry, then
replace the placeholder image in `deployment.yaml` with an immutable digest.
For Artifact Registry, the shape is:

```text
REGION-docker.pkg.dev/PROJECT_ID/meeting-insights/agent@sha256:...
```

Grant the GKE node/service identity permission to pull that image. Do not use
the mutable `latest` tag for an environment deployment.

## Create the namespace and secrets

```bash
kubectl create namespace meeting-insights
kubectl -n meeting-insights create secret generic meeting-insights-agent-secrets \
  --from-literal=GROQ_API_KEY='replace-me' \
  --from-literal=ANTHROPIC_API_KEY='replace-me'
```

Use your organisation's secret manager and external-secrets controller in a
production cluster. The command is a local/bootstrap example; do not paste
real credentials into shell history or Git.

## Deploy

Apply the non-secret resources after updating the image and any ConfigMap
values:

```bash
kubectl -n meeting-insights apply -f serviceaccount.yaml
kubectl -n meeting-insights apply -f configmap.yaml
kubectl -n meeting-insights apply -f deployment.yaml
kubectl -n meeting-insights apply -f service.yaml
kubectl -n meeting-insights apply -f hpa.yaml
kubectl -n meeting-insights rollout status deployment/meeting-insights-agent
kubectl -n meeting-insights get pods,svc,hpa
```

### Local kind compatibility mode

On some local Kubernetes-in-Docker environments, the optional Claude Agent SDK
or bundled Claude CLI can be incompatible with the node CPU architecture. The
application has a deterministic LangGraph fallback. For a stable local demo,
apply the kind override after `configmap.yaml`, rebuild/load the image, and
restart the deployment:

```bash
kubectl -n meeting-insights apply -f configmap.kind.yaml
docker build -t meeting-insights-agent:local .
kind load docker-image meeting-insights-agent:local --name meeting-demo
kubectl -n meeting-insights rollout restart deployment/meeting-insights-agent
kubectl -n meeting-insights rollout status deployment/meeting-insights-agent
```

This compatibility mode is for local Kubernetes demos only. It deliberately
reports `claude_sdk_checked: false` from `/health`; it does not prove the
Claude Agent SDK path. Validate that path on a supported macOS or cloud runtime
before claiming it is deployed there.

For a non-production smoke test, port-forward the internal service:

```bash
kubectl -n meeting-insights port-forward service/meeting-insights-agent 8742:80
curl http://127.0.0.1:8742/health
```

## GKE identity and cloud access

This project currently uses the direct Anthropic API when `ANTHROPIC_API_KEY`
is present. If future tools call BigQuery, Cloud Storage, or Vertex AI, enable
GKE Workload Identity, bind only the required Google service-account roles,
and annotate `meeting-insights-agent` with that Google service account. Avoid
static GCP service-account keys and do not put them in Kubernetes Secrets.

If Bedrock remains the selected model provider, the workload also needs an
AWS-to-GCP workload-identity federation design or another approved short-lived
credential path. Do not add long-lived AWS keys to this manifest.

## Operational notes

- The HPA scales on CPU. For production, also monitor request latency, queue
  depth, model-provider errors, agent turns, and per-run token cost.
- The `/health` endpoint is process health, not an end-to-end check of Qdrant
  or model-provider availability. Alert on those dependencies separately.
- `emptyDir` sandbox files disappear when a pod terminates. Store only
  temporary uploads there; persist approved reports and source assets outside
  the pod.
