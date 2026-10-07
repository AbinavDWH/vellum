# Vellum Phase 3 — Production Cloud Readiness Plan

> **Type:** Planning & prevention spec (no code)
> **Rule 1 — Gate discipline:** A module is "done" only when its Exit Tests pass. Fail = fix + retest. Never skip forward.
> **Rule 2 — Staging first:** Every module is proven in a staging environment that mirrors production before touching production.
> **Rule 3 — Rollback first:** Before any change is applied, its rollback path is defined and tested.
> **Rule 4 — Prevention over reaction:** Every known real-world failure mode gets a designed control, not a hope.

---

## Module P-01 — Container Image Pipeline & Registry

**Goal:** Every release becomes a small, scanned, immutable, traceable artifact.

| Real-World Problem | Prevention Method / Feature |
|---|---|
| Bloated images → slow deploys, huge attack surface | Multi-stage builds; minimal base images; build-time dependency pruning; image size budget enforced in CI |
| `latest` tag in production → nobody knows what is running; rollback impossible | Immutable SHA-pinned tags only in prod; semver + commit-SHA tagging scheme; registry mutability disabled |
| Vulnerable base image ships to customers (Log4Shell-class events) | Automated vulnerability scan on every push; CI gate blocks CRITICAL/HIGH; weekly re-scan of stored images; auto-rebuild on base-image CVE |
| Secret accidentally baked into an image layer | Build-time secret scanning; `.dockerignore` policy; secrets never enter build context — injected only at runtime |
| Registry outage freezes all deployments | Registry replication to secondary region; last-known-good image cached in cluster |
| Tampered / unverified image runs in prod | Image signing at build time; cluster admits only signed, scanned images |

**Exit Tests (gate to P-02):**
1. Image builds reproducibly under the size budget.
2. Deploying by SHA tag twice yields identical running artifacts.
3. Injected test vulnerability is caught and blocks the pipeline.
4. Injected test secret in a layer is detected and fails the build.
5. Registry failover drill: pull succeeds from replica during simulated primary outage.

---

## Module P-02 — CI/CD Pipeline & Release Governance

**Goal:** Changes flow automatically to staging, and to production only through guarded gates.

| Real-World Problem | Prevention Method / Feature |
|---|---|
| Broken build reaches production | Mandatory test + lint + security gates; branch protection; no direct prod pushes |
| Leaked pipeline credentials in logs | Short-lived OIDC federation to cloud (no stored keys); secret masking in logs; log scanning for credential patterns |
| Two deploys race each other → corrupted release | Pipeline concurrency locks; one deploy in flight per environment |
| Outage lasts hours because rollback is manual and untested | One-click rollback to any previous SHA; rollback rehearsed every release cycle; auto-rollback wired to health signals |
| Friday-night deploy destroys the weekend | Deploy windows + freeze calendar; after-hours deploys require explicit override with recorded approval |
| Flaky tests get permanently bypassed | Flaky-test quarantine policy: quarantined tests tracked with owner and expiry; bypass requires recorded approval |

**Exit Tests:**
1. Deliberately failing test blocks a production deploy.
2. Full pipeline (commit → staging) completes within target time.
3. Rollback drill restores previous version in under the defined RTO.
4. Concurrency test: two simultaneous triggers serialize correctly.
5. Credential-leak simulation is masked/blocked.

---

## Module P-03 — Production Infrastructure as Code

**Goal:** The entire production environment is reproducible from version-controlled definitions.

| Real-World Problem | Prevention Method / Feature |
|---|---|
| State file lost or corrupted → orphaned infrastructure | Remote encrypted, versioned state with locking; state backups; no local state in prod |
| Two engineers apply at once → state corruption | State locking; apply only via pipeline, never from laptops |
| Manual console edits silently drift from definitions | Scheduled drift detection; config-rule alerts on out-of-band changes; console write access removed for humans |
| Single-AZ outage kills the service | Multi-AZ distribution for compute, database, and storage |
| Database accidentally public | Policy-as-code guardrails in pipeline (block public DB, block 0.0.0.0/0 to data ports) before apply |
| Forgotten resources burn money for months | Mandatory tagging policy; untagged resources auto-flagged; scheduled orphan scan |

**Exit Tests:**
1. Destroy-and-rebuild drill of staging from definitions succeeds end-to-end.
2. Simultaneous apply attempt is rejected by locking.
3. Manual console change is detected and alerted within the target window.
4. Policy guardrail blocks a deliberately unsafe plan (public DB).
5. AZ-failure simulation: service survives with one AZ removed.

---

## Module P-04 — Secrets, Identity & Least Privilege

**Goal:** No secret exists in code, images, or logs; every identity has minimum power.

| Real-World Problem | Prevention Method / Feature |
|---|---|
| Secret committed to git → leaked forever | Pre-commit + CI secret scanning; history-rewrite runbook; rotation-on-exposure procedure |
| Over-permissive roles → one compromised container owns the cloud | Least-privilege IAM per service; permission boundaries; periodic access reviews; unused-permission detection |
| Rotation breaks the app (hard cutover) | Dual-validity rotation window (old + new active simultaneously); rotation drills in staging |
| The AI/LLM layer ever sees a credential (Vellum's core promise) | Credential isolation enforced architecturally: LLM receives connection IDs, never secrets; automated test asserts no secret string appears in any LLM prompt/log |
| Human uses standing production access | Just-in-time elevated access with expiry + recorded justification; all human prod actions audited |

**Exit Tests:**
1. Committed test secret is caught pre-merge and post-merge (history scan).
2. Role-permission audit shows zero wildcard data-plane permissions.
3. Rotation drill completes with zero failed requests during cutover.
4. Prompt/log scan proves no secret material reaches the LLM layer.
5. JIT access expires automatically and is logged.

---

## Module P-05 — Zero-Downtime Deployment Strategy

**Goal:** Users never notice a release; bad releases remove themselves.

| Real-World Problem | Prevention Method / Feature |
|---|---|
| Dropped connections during deploy | Connection draining; graceful shutdown handling; readiness vs liveness probes separated (not-ready ≠ killed) |
| New version fine in staging, crashes under real traffic | Canary release: small traffic slice first, metric-gated promotion, automatic rollback on regression |
| Schema change breaks the old version mid-rollout (both versions live at once) | Expand–contract migration pattern: additive changes first, contract only after full rollout; compatibility contract tested |
| Deploy succeeds but feature is broken (silent bad release) | Feature flags separate deploy from release; instant flag-off without redeploy |
| Long-running executions (Terraform applies) killed mid-flight | Job handoff design: in-flight work drains to completion or resumes from checkpoint; new version inherits queue |

**Exit Tests:**
1. Load test across a deploy shows zero failed requests and zero connection resets.
2. Canary with injected error rate auto-rolls back within target time.
3. Mixed-version compatibility test: old app + new schema and new app + old schema both pass.
4. Feature flag off-switch takes effect within seconds, no redeploy.
5. In-flight long job survives a deploy without duplication or loss.

---

## Module P-06 — Observability, Alerting & On-Call

**Goal:** The team learns about problems before customers do, and every alert is actionable.

| Real-World Problem | Prevention Method / Feature |
|---|---|
| Outage discovered via customer complaint | SLO-based monitoring on golden signals (latency, traffic, errors, saturation); synthetic user probes; black-box endpoint checks |
| Alert storm → real alerts ignored | Alert budget policy: every alert mapped to a runbook or deleted; deduplication and grouping; severity tiers with distinct channels |
| Cannot trace one request across services | Correlation/trace IDs propagated end-to-end (UI → API → execution → LLM calls); distributed tracing |
| Silent backlog growth (queues, approvals, executions) | Queue-depth and age metrics with alerts; dead-letter monitoring for failed executions |
| Logs expire exactly when needed | Retention policy per data class (hot/warm/archive); audit logs immutable and long-lived |

**Exit Tests:**
1. Injected latency/error incident is paged within target detection time.
2. One request traceable UI → backend → executor → verification with a single ID.
3. Queue-stall simulation raises a backlog alert before user impact.
4. Alert-to-runbook mapping audit: zero orphan alerts.
5. Log retention drill: 90-day-old audit entry retrievable and hash-verified.

---

## Module P-07 — Data Layer: Migrations, Backups, Disaster Recovery

**Goal:** Data survives mistakes, outages, and disasters — proven, not assumed.

| Real-World Problem | Prevention Method / Feature |
|---|---|
| Migration fails halfway → corrupted schema | Transactional, idempotent, rehearsed migrations; run first against a production-sized restored copy in staging |
| Backups exist but never restore (backup theater) | Scheduled automated restore drills; restore time and data completeness measured and reported |
| Ransomware/malice deletes primary and backups together | Immutable, versioned backups; cross-region copies; separate backup account with its own credentials |
| Region-level outage = total loss | Defined RTO/RPO per component; cross-region standby or restore path; failover runbook rehearsed |
| Data growth silently degrades performance | Capacity forecasts from metrics; partitioning/archival policy for audit and execution history |

**Exit Tests:**
1. Migration rehearsal on production-scale clone passes within window.
2. Restore drill meets RPO and RTO targets with data integrity verified.
3. Backup-immutability test: deletion attempt on protected backup is denied.
4. Region-failover tabletop + partial live drill completed and documented.
5. Archival job moves aged data without affecting query performance.

---

## Module P-08 — Security Hardening, Abuse & AI-Specific Defense

**Goal:** The platform resists attackers, abusers, and its own AI.

| Real-World Problem | Prevention Method / Feature |
|---|---|
| Public storage/data leak via misconfiguration | Continuous posture scanning; policy-as-code blocks at plan time; external attack-surface monitor |
| Bot/abuse traffic burns compute and LLM budget | Rate limiting and quotas per user/tenant; WAF rules; anomaly-based blocking |
| Prompt injection via ingested documents hijacks the agent | Retrieved-content sanitization; instruction/data separation; tool-call allowlist; LLM output always passes deterministic validation before any action |
| AI approves its own dangerous action | Human-in-the-loop preserved in production with separation of duties; critical actions require second approver; approval records immutable (existing SHA-256 chain extended) |
| Unpatched dependency becomes the breach | Automated dependency updates with staged rollout; patch SLA per severity |

**Exit Tests:**
1. Posture scan shows zero critical misconfigurations; injected misconfig is auto-flagged.
2. Abuse load test: quotas and WAF hold error rate and cost within limits.
3. Red-team prompt-injection suite: zero successful unauthorized actions.
4. Critical-action test: execution impossible without recorded human approval.
5. Dependency CVE drill: patch from disclosure to staged rollout within SLA.

---

## Module P-09 — Cost, Capacity & Lifecycle Governance

**Goal:** The bill is predictable and every resource has an owner and an expiry.

| Real-World Problem | Prevention Method / Feature |
|---|---|
| Bill shock from forgotten or runaway resources | Budgets with anomaly alerts; per-environment cost attribution via mandatory tags; weekly cost review report |
| Traffic spike exhausts capacity (launch day, peak season) | Autoscaling with tested limits; pre-season load tests; headroom policy; scale-up faster than scale-down |
| Storage and logs grow unbounded | Lifecycle policies per data class; automatic expiration and tiering; growth alerts |
| Over-provisioning "just in case" becomes permanent | Right-sizing reviews from utilization metrics; scheduled downscale for non-prod (nights/weekends) |

**Exit Tests:**
1. Injected spend anomaly alerts within target time with owner attribution.
2. Load test at 3× baseline: autoscaling holds SLOs, then scales back down.
3. Lifecycle policy drill: expired data tiered/deleted on schedule, retrievable classes intact.
4. Non-prod environments auto-downscale off-hours and recover on schedule.

---

## Module P-10 — Resilience Validation (Chaos & Game Days)

**Goal:** Failures are rehearsed on purpose, small, and often — so real ones are boring.

| Real-World Problem | Prevention Method / Feature |
|---|---|
| First encounter with a failure mode happens during a real incident | Chaos experiments: kill instances/AZs, inject latency, corrupt responses, drop the LLM endpoint — in staging, then controlled prod |
| Dependency outage (LLM server down, DB failover) cascades | Circuit breakers, timeouts with jittered retries, graceful degradation: queue requests when LLM offline, serve read-only mode when executor down |
| Nobody remembers how to recover at 3 a.m. | Runbooks linked from every alert; quarterly game days with scored recovery; post-incident reviews with tracked action items |
| Retried destructive action executes twice | Idempotency keys on all execution APIs; exactly-once semantics on the execution queue |

**Exit Tests:**
1. Chaos suite (AZ loss, LLM down, DB failover, network latency) completes with SLOs held or graceful degradation engaged.
2. Idempotency test: duplicated execution request produces exactly one effect.
3. Game day: team recovers a simulated major incident within RTO using only runbooks.
4. All post-incident action items from the last two drills closed.

---

## 🚦 Phase Gate Summary

| Module | Theme | Gate = Exit Tests Passed |
|---|---|---|
| P-01 | Image pipeline & registry | 5/5 |
| P-02 | CI/CD & release governance | 5/5 |
| P-03 | Production IaC | 5/5 |
| P-04 | Secrets & identity | 5/5 |
| P-05 | Zero-downtime deploys | 5/5 |
| P-06 | Observability & on-call | 5/5 |
| P-07 | Data, backups, DR | 5/5 |
| P-08 | Security & AI defense | 5/5 |
| P-09 | Cost & capacity | 4/4 |
| P-10 | Chaos & resilience | 4/4 |

**Ordering rule:** P-01 → P-02 → P-03 are the foundation (nothing deploys safely without them). P-04–P-06 make it trustworthy. P-07–P-08 make it survivable and defensible. P-09–P-10 make it sustainable. Each gate failure sends you back inside that module only — never forward.

**Definition of "Production Ready":** All 10 gates green + one full game day completed + rollback and DR drills evidenced in the audit trail.
