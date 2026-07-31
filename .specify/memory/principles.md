# Legal-AI-Infraestructure IaC Principles

<!-- Sync Impact Report -->
<!-- Version change: N/A → 1.0.0 (initial adoption) -->
<!-- Modified principles: N/A (initial creation) -->
<!-- Added sections: Architecture (4), Code (24), Approaches (2), Governance -->
<!-- Removed sections: N/A -->
<!-- Deferred items: None -->
<!-- End Sync Impact Report -->

## Architecture Principles

High-level tenets expressing WHAT outcomes infrastructure achieves for this
on-premise legal-AI project. These are universal philosophies, NOT technical
implementation checklists.

### On-Premise Infrastructure

All infrastructure runs on the project's own physical server or explicitly
authorized internal resources. No dependency on public cloud services for
database, storage, queues, secrets, observability, backups, or inference.

**Why it matters**: The project handles sensitive legal documents and personal
data. Public cloud dependency introduces external risk, vendor lock-in, and
potential data exposure that violates the project's security constitution.

**Baseline (MVP)**: Docker Compose locally, Kubernetes on existing cluster,
Ollama via internal endpoint, PostgreSQL and Redis as containerized services.

**Enhanced (Production)**: Same architecture with formal backups, monitoring,
and capacity planning. No cloud migration unless an explicit, documented
decision justifies it.

### Project Isolation

Every resource belongs exclusively to this project. The namespace, database,
storage, secrets, configuration, ingress, and observability are completely
isolated from other projects. Destroying this project must not affect Ollama
or any other project.

**Why it matters**: Shared infrastructure creates hidden coupling. A misconfigured
migration or resource leak in this project could corrupt another project's data
or disrupt shared services like Ollama.

**Baseline (MVP)**: Dedicated Kubernetes namespace, own PostgreSQL instance,
own Redis instance, own PVCs, own secrets, own ServiceAccounts.

**Enhanced (Production)**: NetworkPolicies, ResourceQuotas, LimitRanges,
dedicated backup targets, separate Terraform state per environment.

### Design for Simplicity

The simplest solution that satisfies measured requirements is always preferred.
No additional microservices, separate vector databases, complex orchestrators,
autonomous agents, or fine-tuning without demonstrated need. Every new tool
must resolve an identified need. Operational complexity is an explicit cost.

**Why it matters**: This project has a small team and limited infrastructure.
Complexity multiplies maintenance burden, increases attack surface, and slows
delivery. PostgreSQL with pgvector is sufficient; Redis only if concretely
needed; no service mesh, no GitOps pipeline, no Vault unless justified.

**Baseline (MVP)**: Single PostgreSQL, optional Redis, Docker Compose for dev,
minimal Helm chart, simple Terraform modules.

**Enhanced (Production)**: Add monitoring, backups, formal CI/CD only when
the MVP has demonstrated value and operational maturity requires it.

### Plan for Server Failure

The physical server is a single point of failure. This must be documented
explicitly. External copies must exist for: PostgreSQL backups, Terraform state,
secret keys, configuration, charts, source code, and recovery documentation.
A backup without a tested restore procedure is not sufficient for production.

**Why it matters**: On-premise means no cloud provider SLA. A disk failure,
power loss, or hardware fault could destroy all project data. Recovery must
be possible from external copies.

**Baseline (MVP)**: Document what would be lost. Maintain off-disk copies of
backups, state, and secrets. Document manual recovery procedures.

**Enhanced (Production)**: Automated backup to second disk or NAS, tested
restore drills, documented RTO/RPO, disaster recovery runbook.

## IaC Code Principles

High-level tenets expressing HOW infrastructure code is written. These focus
on code quality, maintainability, security, and validation. They apply across
all environments.

### Terraform as Source of Truth

All persistent infrastructure and platform configuration must be declared in
Terraform. Manual changes must be avoided. If an emergency manual change occurs,
it must be documented and reconciled with Terraform afterward. No imperative
scripts for resources that Terraform can declare declaratively. Resources not
belonging to the project must be treated as external dependencies or data
sources, never imported without justification.

**Why it matters**: Terraform provides reproducibility, auditability, and
idempotency. Manual changes create drift, undocumented state, and recovery
uncertainty.

**How to apply**: Every Kubernetes resource, PVC, Secret reference, RBAC rule,
and networking policy must have a corresponding Terraform resource. `terraform
plan` must be reviewed before any `apply`. Destructive operations require human
approval.

### Separation of Terraform, Helm, and Application

Each layer has a distinct responsibility. Terraform manages cluster-level
resources (namespace, RBAC, storage, networking, Helm releases). Helm manages
workloads (Deployments, Services, Jobs, ConfigMaps, probes, limits). The
application manages business logic (schemas, migrations, parsing, chunking,
embeddings, retrieval, generation, audit). No resource must be administered
by more than one layer.

**Why it matters**: Mixed ownership creates conflicts, drift, and debugging
nightmares. When Terraform and Helm both try to manage the same Deployment,
changes overwrite each other silently.

**How to apply**: Terraform creates the namespace and installs the Helm chart.
Helm deploys the application. The application runs migrations internally via
Alembic. No Terraform resource should define a container image tag; no Helm
template should create a namespace.

### Small Modules with Clear Responsibilities

Avoid a single monolithic Terraform module. Separate modules by coherent
capabilities: namespace/governance, PostgreSQL, Redis, application deployment,
networking/ingress, security, observability, backups. Each module must have
clear inputs, outputs, and responsibilities. Dependencies between modules must
be explicit and minimal. Modules must not assume fixed domains, disk sizes,
or endpoints. Do not create generic modules prematurely.

**Why it matters**: Small, focused modules are easier to test, review, reuse,
and replace. Monolithic modules hide dependencies and make changes risky.

**How to apply**: Start with separate `.tf` files per concern within a single
root module. Extract to separate modules when reuse or isolation is needed.
Never create a "utils" or "shared" module without concrete justification.

### Separated Environments

Local development uses Docker Compose, not Terraform. Kubernetes environments
start with a single dev/MVP environment. Staging and production are added
only when a real need exists. Each Kubernetes environment must have independent
Terraform state. No state sharing between environments. Environment-specific
configuration must be separated from reusable modules. No hardcoded names,
domains, sizes, endpoints, or credentials from one environment inside modules.

**Why it matters**: Shared state means a `terraform apply` in dev can destroy
production. Environment separation prevents catastrophic cross-environment
accidents.

**How to apply**: Use separate directories or workspaces per environment.
Variable files are environment-specific. Modules receive all configuration
through variables, never through local values derived from other environments.

### On-Premise Terraform State

Terraform state must not be stored in Git. For initial testing, a local backend
may be used temporarily and documented. Before shared deployment, configure a
remote on-premise backend with locking. Preferred options in order: internal
HTTP backend, GitLab Terraform State (if available), MinIO S3-compatible,
other internal backend with locking and access control. States for dev, staging,
and prod must be separated. Sensitive data within state must be minimized.
Access to state must follow least privilege. State must be included in backup
policy. Critical persistent resources must be protected against accidental
destruction.

**Why it matters**: State contains secrets and infrastructure metadata. If
stored in Git, it is exposed to everyone with repository access. If stored
locally, only one person can operate infrastructure and state loss means
rebuilding from scratch.

**How to apply**: Configure remote backend before any shared environment.
Use `terraform state lock` mechanisms. Mark sensitive outputs. Include state
in automated backup scope.

### Protect Persistent Data

PostgreSQL must use persistent storage. Embeddings, documents, audit trails,
and drafts must not depend on ephemeral pod filesystems. Production volumes
must not be automatically deleted when destroying an application release.
An explicit retention policy must be defined. Destructive changes to PVCs,
databases, or data require human review. A documented backup and recovery
strategy must exist. Terraform must not execute destructive data migrations.
Schema and migrations must be managed from the application via Alembic. PVCs
must use the authorized StorageClass. StorageClass selection must document
capacity, performance, and reclamation policy.

**Why it matters**: Legal document drafts and audit trails are irreplaceable.
A misconfigured Helm release that deletes PVCs would destroy the entire
corpus and all generated work.

**How to apply**: Set `deletionPolicy: Retain` on critical PVCs. Separate
database infrastructure from application infrastructure in Terraform. Run
migrations via Jobs, not via Terraform.

### On-Premise Backups

PostgreSQL must have automatable backups stored outside the primary PVC. A
backup on the same physical disk is not sufficient protection. Acceptable
destinations: second physical disk, NAS, another backup server, on-premise
S3-compatible storage (MinIO). No cloud storage unless explicitly decided
later. Retention must be configurable. Backups must be encrypted when containing
sensitive data. Restore procedures must be documented. A backup without a
tested restore is not sufficient for production. For the MVP, a simple CronJob
is acceptable if the evolution strategy is documented. Backup credentials must
be managed as secrets.

**Why it matters**: On-premise means no provider-managed backups. If the
primary disk fails and backups are on the same disk, all data is lost.

**How to apply**: Configure CronJob for pg_dump to a separate volume. Document
restore procedure. Test restore at least once before declaring production-ready.

### Secrets Management

No secret must be stored in plaintext in Git. No passwords directly in
versioned tfvars files. Avoid storing secret values directly in Terraform
resources when that exposes the secret in state. For the MVP, prefer SOPS
with age or Sealed Secrets. Do not introduce Vault unless it already exists
or a clear need justifies it. Terraform must manage references and permissions,
not necessarily secret values. Secrets must be separated per environment.
Credentials for PostgreSQL, Redis, registry, TLS, and tokens must be rotatable
without rebuilding infrastructure. Private decryption keys must stay out of
Git. Secrets must not appear in logs, plans, outputs, or documentation.

**Why it matters**: Secrets in Git are accessible to anyone with repository
access. Secrets in Terraform state are exposed during `terraform plan` output.
Both create security vulnerabilities.

**How to apply**: Use SOPS-encrypted files or Sealed Secrets. Mark Terraform
outputs containing references as `sensitive = true`. Never print plan output
containing secret values in CI logs.

### Networking and Network Isolation

Apply default-deny NetworkPolicy when the cluster CNI supports it. Allow only
required flows. Frontend communicates only with API. API and workers communicate
with PostgreSQL, Redis, and Ollama. PostgreSQL and Redis must not be exposed
via Ingress, NodePort, or LoadBalancer. Ollama must not be exposed to frontend.
Ollama access must be restricted by host, port, namespace, or IP when possible.
Ingress must expose only required endpoints. All user traffic must use HTTPS.
Domain and certificates must be configurable. API, PostgreSQL, Redis, and
Ollama must not be directly exposed to the internet. Internal services must
use ClusterIP. Egress must be restricted to required destinations when viable.

**Why it matters**: Legal documents and personal data traverse the network.
Unrestricted network access means a compromised frontend could directly
access the database.

**How to apply**: Define NetworkPolicy resources in Terraform. Use Helm values
to configure service types. Verify with `kubectl get networkpolicies` after
deployment.

### Ollama as External Dependency

Ollama is a shared external dependency. Its endpoint must be configurable via
`OLLAMA_BASE_URL`. Terraform must not manage Ollama. Helm must not deploy
Ollama. Infrastructure must allow changing the endpoint without rebuilding
images. Timeouts, health checks, and connectivity tests must exist. An Ollama
failure must not prevent the API from exposing differentiated health checks.
The application must tolerate temporary Ollama unavailability without data
corruption. Mass ingestion must not monopolize shared capacity. Workers must
have configurable concurrency. Interactive requests must be prioritizable over
batch jobs. No exclusive GPU access must be assumed. Models must not be loaded
or unloaded without coordination with shared infrastructure. The project must
record the model name used but not manage its global lifecycle.

**Why it matters**: Ollama is shared across projects. If this project's
ingestion saturates Ollama, other projects suffer. If Ollama goes down,
this project must degrade gracefully, not crash.

**How to apply**: Configure `OLLAMA_BASE_URL` as environment variable. Implement
circuit breaker or timeout in the Ollama client adapter. Set worker concurrency
limits. Log Ollama connectivity status in health checks.

### Server Resources and Capacity

Every container must define CPU and memory requests and limits. No arbitrarily
high values without measurement. Values must be adjustable per environment.
API, frontend, and workers must scale independently. PostgreSQL and Redis must
not scale horizontally without explicit architectural decision. No autoscaling
in the MVP without metrics or demonstrated need. Batch jobs must limit
concurrency. Limits must prevent affecting other cluster projects. Namespace
must include ResourceQuota and LimitRange when viable. Storage capacity must
be monitored. Disk, memory, or GPU saturation must be treated as operational
risk. Resources must be sized from real measurements. The project must not
reserve GPU directly if it only consumes Ollama via endpoint. The application
must support backpressure when Ollama is saturated.

**Why it matters**: On a shared server, one project consuming all resources
starves others. Without limits, a runaway ingestion job could OOM the node.

**How to apply**: Start with conservative limits based on local testing.
Document measured resource usage. Adjust after MVP validates actual consumption.

### Availability and Updates

All services must have appropriate readiness and liveness probes. API must
differentiate health, readiness, and external dependencies. Deployments must
use rolling updates. Updates must not depend on `latest` tags. Images must
use immutable tags or digests. Migrations must execute in a controlled manner
before or during deployment. A failed deployment must be reversible. High
availability is not required for the MVP without demonstrated need. Operational
simplicity has priority during the first phase. Pod restarts must not lose
persistent data. Jobs must be idempotent when possible. CronJobs must define
concurrency policies and history retention.

**Why it matters**: Uncontrolled deployments can cause downtime. Immutable
tags prevent "it works on my machine" failures in production.

**How to apply**: Use specific image tags in Helm values. Configure rolling
update strategy. Set `imagePullPolicy: IfNotPresent` with immutable tags.
Test migration rollback before deploying schema changes.

### Container Security

Run containers as non-root user whenever possible. Use read-only filesystem
when compatible. Remove unnecessary capabilities. Avoid large or unmaintained
base images. Pin image versions. Scan images and dependencies. No development
tools or secrets in production images. Use multi-stage builds. Configure
`securityContext` for pods and containers. Avoid `privileged` containers.
Avoid `hostPath` unless documented. Set `allowPrivilegeEscalation: false`
when possible. Use `seccomp: RuntimeDefault`. Mount only necessary volumes.
No process execution as root without documented exception.

**Why it matters**: Container escape vulnerabilities exist. Running as root
or with privileged access amplifies the blast radius of any container
compromise.

**How to apply**: Define `securityContext` in Helm templates. Use ` Trivy`
or `grype` in CI to scan images. Use distroless or alpine base images.

### RBAC and Least Privilege

Each workload must use its own ServiceAccount when permissions differ. Never
use `cluster-admin`. Avoid ClusterRole unless there is a real need. Prefer
Role and RoleBinding within the namespace. Workers must not have permissions
to modify infrastructure. API must not have Kubernetes permissions unless it
needs them. Migration jobs must receive only strictly necessary permissions.
Permissions must be reviewed as part of planning and security analysis.
Credentials used by Terraform must be limited to project resources when the
cluster allows. SSH administrative access does not replace Kubernetes access
control. Do not use the namespace default ServiceAccount for production
workloads requiring differentiated permissions.

**Why it matters**: Over-permissive RBAC means a compromised pod can modify
other projects, access secrets, or disrupt the cluster.

**How to apply**: Create per-service ServiceAccounts in Terraform. Bind
minimal Roles. Never grant `create`, `update`, or `delete` on Secrets or
Namespaces unless absolutely required.

### PostgreSQL Database

PostgreSQL must include pgvector. The extension must be enabled via migration
or controlled initialization. The database must be exclusive to the project.
Access must be limited to authorized workloads. Migrations must be versioned.
Terraform must not model application tables, columns, or data. Application
schema must be managed via Alembic. Backups must include relational and vector
data. The initial deployment may use a single PostgreSQL instance. Highly
available architecture must be evaluated only after the MVP demonstrates value.
PostgreSQL must not be exposed outside the cluster unless an explicit and
temporary administrative need exists. Connections must use application-specific
credentials. Administrative credentials must not be used from the API.
Connection limits must be configured. A major version upgrade strategy must
be defined.

**Why it matters**: PostgreSQL stores the entire legal corpus, embeddings,
and audit trail. Uncontrolled schema changes or credential exposure could
compromise the entire system.

**How to apply**: Use Terraform for namespace and PVC. Use Helm for the
PostgreSQL deployment configuration. Use Alembic for all schema changes.
Rotate credentials via secret rotation, not pod restart.

### Redis

Redis must be exclusive to the project. It must be used only when a concrete
need for queues, coordination, or caching exists. It must not serve as source
of truth for documents, audit, or permanent results. Critical data must be
persisted in PostgreSQL. Redis persistence need must be defined based on real
usage. Redis must not be exposed publicly. Authentication and memory policy
must be configured explicitly. `maxmemory-policy` must be defined. Losing
Redis must not eliminate persistent legal information. If no real queue need
exists initially, Redis may be deferred. It must not be included by
architectural inertia.

**Why it matters**: Redis without persistence means data loss on pod restart.
Including Redis "because it might be needed" adds operational complexity
without demonstrated value.

**How to apply**: Start without Redis. Add only when a concrete use case
(e.g., job queue, rate limiting) is validated. If added, configure
`maxmemory-policy: allkeys-lru` and persistent storage.

### On-Premise Observability

All components must produce structured logs. Logs must not contain personal
data, full documents, full prompts, or secrets. Metrics must be exposed when
Prometheus support exists. At minimum, measure: availability, latency, errors,
job status, PostgreSQL connectivity, Redis connectivity, Ollama connectivity,
generation duration, embedding duration, queue depth, storage usage. Integrate
with Prometheus, Grafana, and Loki if they already exist in the cluster. If
they do not exist, start with Kubernetes logs, basic metrics, and health
checks. Do not deploy a full observability platform before validating the MVP.
Observability must be incorporable without modifying business logic. Dashboards
and alerts must be versioned when incorporated.

**Why it matters**: On-premise means no cloud monitoring dashboard. Without
observability, problems are invisible until users complain.

**How to apply**: Start with `kubectl logs` and health check endpoints. Add
Prometheus ServiceMonitor when available. Use structured JSON logging in the
application.

### Local Docker Compose

The local environment must be launched via Docker Compose. It must include
PostgreSQL with pgvector, API, and workers. Redis only when a real need
exists. Frontend may run inside or outside Compose per the technical plan.
Ollama may be consumed locally or remotely via variable. Docker Compose must
not share data with Kubernetes. Named volumes must be used. `.env.example`
without secrets must exist. Commands for start, stop, migration, and cleanup
must be documented. Do not assume the developer has local Kubernetes. Docker
Compose must be sufficient to implement and test the first phases. A secure
way to point to the remote Ollama endpoint must exist. Test data must not
contain real sensitive information.

**Why it matters**: Developer experience directly impacts velocity. If
setting up the local environment requires undocumented manual steps, new
team members are blocked.

**How to apply**: Define `docker-compose.yml` with all services. Provide
`.env.example` with documented variables. Include Makefile or scripts for
common operations.

### Registry and Images

Application images must be built reproducibly. They must be stored in a
registry accessible from the cluster. The registry may be: an existing internal
registry, GitHub Container Registry (only if authorized), or another private
registry. The system must not depend on continuously downloading images from
the internet. Immutable tags or digests must be used. No `latest`. Images
must be scanned before deployment. Registry credentials must be managed as
secrets. The procedure for publishing and promoting images must be documented.
Critical base images must be pinned by version or digest.

**Why it matters**: If images are pulled from public registries on every
deployment, a network outage or registry downtime blocks all deployments.

**How to apply**: Pre-pull critical images to the cluster. Use specific tags
in Helm values. Run image scanning in CI before merge.

### CI/CD and Validation

Every infrastructure change must run at minimum: `terraform fmt -check`,
`terraform validate`, `tflint`, security analysis with Checkov/tfsec or
equivalent, `helm lint`, `helm template`, manifest validation, and
`terraform plan` for relevant changes. `terraform apply` must not execute
automatically from an unprotected branch. Production changes must require
manual approval. The applied plan must match the reviewed plan. Pipeline
credentials must follow least privilege. Plan and analysis results must be
retained as artifacts when viable. The pipeline may run on a local or
self-hosted runner. Do not assume cloud runner availability. Cluster access
from CI must use restricted credentials. Apply operations must be audited.

**Why it matters**: Unvalidated infrastructure changes can destroy production.
Automated checks catch syntax errors, security issues, and drift before they
reach the cluster.

**How to apply**: Define CI pipeline with required checks. Block merge if
checks fail. Require approval for production apply. Log all apply operations.

### Versioning

Pin and version: Terraform providers, minimum Terraform version, modules,
Helm charts, images, manifests, linting tools, environment configuration,
operational scripts, and security policies. Do not use open-ended versions
that may introduce incompatible changes. Lock files must be versioned. Updates
must be explicit and reviewed. Infrastructure version must be associated with
the deployed application version. Incompatible changes must be documented.
PostgreSQL, Redis, and chart versions must be pinned. Major version changes
require a migration plan.

**Why it matters**: Unpinned versions mean `terraform apply` on Monday
produces different results than on Friday. Reproducibility requires explicit
version constraints.

**How to apply**: Use `= X.Y.Z` for modules in production. Use
`.terraform.lock.hcl` for provider versions. Document version bumps in
commit messages.

### Operational Documentation

Infrastructure must include documentation for: prerequisites, server topology,
SSH access, Terraform backend configuration, variables, secrets, initial
deployment, updates, rollback, backup, restore, log access, PostgreSQL
diagnostics, Redis diagnostics, Ollama diagnostics, networking diagnostics,
storage diagnostics, safe environment destruction, and server failure recovery.
Do not depend on tacit operator knowledge.

**Why it matters**: On-premise means no cloud support team. If the only
person who knows how to restore PostgreSQL leaves, the system is
unrecoverable.

**How to apply**: Maintain `docs/operations/` directory. Update documentation
with every infrastructure change. Include runbooks for common failure scenarios.

### Incremental Infrastructure

Mandatory infrastructure order: (1) Docker Compose locally, (2) API
connectivity with PostgreSQL and Ollama, (3) Redis only if the application
requires it, (4) reproducible Dockerfiles, (5) minimal Helm chart, (6)
namespace and Kubernetes configuration, (7) Terraform for project-owned
resources, (8) Ingress and TLS, (9) security and NetworkPolicies, (10)
backups, (11) observability, (12) staging and production if needed. Do not
implement the entire Kubernetes infrastructure before validating the local
environment.

**Why it matters**: Building everything at once means debugging ten things
simultaneously. Incremental delivery validates each layer before adding the
next.

**How to apply**: Follow the prescribed order. Do not skip to Helm charts
before Docker Compose works. Do not add Terraform before Helm is validated.

### SSH Administration

SSH is used for bootstrap, diagnostics, and recovery. Normal deployments must
not depend on manually copying files via SSH. Permanent changes made via SSH
must be reflected afterward in Git, Terraform, or Helm. SSH private keys must
not be stored in the repository. SSH access must be limited to authorized
users. Key-based authentication must be preferred. Operations performed via
SSH must be documented when they affect production. SSH must not be used to
permanently expose PostgreSQL, Redis, or Ollama. SSH tunnels may be used
temporarily for administrative diagnostics.

**Why it matters**: SSH is the escape hatch for when automation fails. If
changes are made via SSH but never reconciled with Terraform, the next
`terraform apply` may revert them.

**How to apply**: Use SSH for one-time fixes only. Document any SSH operation
that modifies production state. Reconcile with IaC within the same day.

## Implementation Approaches

Decision frameworks for WHEN to apply different patterns and complexity levels.

### Progressive Complexity

Start with the minimum viable infrastructure and add complexity only when
measured need justifies it. MVP: Docker Compose, single PostgreSQL, optional
Redis, minimal Helm, single Kubernetes environment. Post-MVP: add backups,
monitoring, formal CI/CD. Production: add HA, staging, comprehensive security.
Every addition must justify which risk or metric it improves.

**When to apply**: Always. This is the default decision framework for this
project. Complexity is never added speculatively.

### Risk-Based Controls

Security and operational controls scale with data sensitivity and system
maturity. The legal document corpus and personal data (DNI, CUIL) demand
baseline security from day one: encryption at rest, network isolation, RBAC,
secret management. Advanced controls (audit logging, immutable storage,
formal disaster recovery) are added when the system demonstrates value and
the operational team is ready to maintain them.

**When to apply**: When deciding whether a security control is required for
the MVP or can be deferred. Legal data always requires at least baseline
controls.

## Governance

These principles govern all infrastructure specifications, plans, tasks, and
IaC implementation for the legal-AI-infraestructure project.

**Authority and Precedence**: These principles supersede individual
preferences, tactical decisions, and conflicting guidance. When in doubt,
these principles guide the decision.

**Compliance and Accountability**: All infrastructure specifications,
implementation plans, and generated code must demonstrate alignment with
these principles. Code reviews and automated checks verify ongoing compliance.

**Justification for Complexity**: Architectural decisions that extend beyond
baseline patterns require documented justification explaining the business or
technical need. This ensures complexity serves purpose rather than emerging
by default.

**Deviation and Exception Process**: Deviations from these principles require
explicit acknowledgment, documented rationale, and appropriate approval.
Exceptions are tracked and periodically reviewed for patterns suggesting
principle amendments.

**Amendment and Evolution**: These principles evolve as needs, capabilities,
and requirements change. Amendments follow semantic versioning (MAJOR for
breaking changes, MINOR for new principles, PATCH for clarifications),
require stakeholder review, and include migration guidance when impacting
existing infrastructure.

**Relationship to Functional Constitution**: These IaC principles establish
infrastructure WHAT and WHY. The functional constitution (GitHub Spec Kit)
governs application behavior. They must remain aligned. IaC Spec Kit is used
only for infrastructure; GitHub Spec Kit is used for application logic.

**Version**: 1.0.0 | **Ratified**: 2026-07-31 | **Last Amended**: 2026-07-31
