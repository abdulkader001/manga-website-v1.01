# Reference cloud infrastructure (apply when you have a cloud account)

> **Status: reference only. Nothing here is wired into CI/CD or applied
> automatically.** The project currently runs on the local Docker stack
> (`docker-compose.yml` + `docker-compose.scale.yml`). These files describe the
> *managed-cloud equivalent* of that scale overlay so the jump to a real
> provider is a fill-in-the-blanks exercise rather than a redesign.

## What maps to what

| Local scale overlay (`docker-compose.scale.yml`) | Managed-cloud equivalent (here) |
| --- | --- |
| `pgbouncer` container | RDS/Cloud SQL Postgres **+ a read replica** and (optionally) RDS Proxy / PgBouncer sidecar — `terraform/main.tf` |
| `redis` container | ElastiCache / Memorystore Redis — `terraform/main.tf` |
| `celery_worker_*` per-queue services | one k8s `Deployment` per queue + `HorizontalPodAutoscaler` — `k8s/celery-workers.yaml` |
| `backend` service | k8s API `Deployment` + `Service` + HPA — `k8s/api.yaml` |
| `manga-stack-migrate` one-shot | k8s `Job` run before rollout — `k8s/migrate-job.yaml` |

## How to actually use it later

1. `terraform/` — set the variables, `terraform plan`, review, `terraform apply`.
   Feed the output DSNs (writer endpoint, reader endpoint, Redis endpoint) into
   your k8s secrets.
2. `k8s/` — replace `image:` refs and the `backend-secrets` / `backend-config`
   references, then `kubectl apply -f k8s/`. The app already reads a separate
   read replica via `DATABASE_READ_URL` (item 32) — point it at the reader
   endpoint to offload read traffic.
3. Follow [`docs/runbooks/scale-to-100k.md`](../../docs/runbooks/scale-to-100k.md) for
   capacity math, the load test (item 44b), and the rollout order.

These are intentionally minimal sketches — no remote state backend, no module
registry pins, no provider hardening. Treat them as a starting point for your
platform team, not production-ready modules.
