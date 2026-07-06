# Job Executor Backends

This doc explains how madosho runs background jobs, the two backend modes, and how to
configure them. Start with the walk-through below, then use the knob table as a reference.

## One research run, step by step

You trigger a research run from the UI. The `app` plane writes a row to the
`research_run` table and enqueues a `run_research` job onto the `research` queue in
Postgres (procrastinate). Nothing else in the app layer is involved.

The `worker` container is sitting in a poll loop. It pulls the job and calls
`EXECUTOR_FOR("research").run("run_research", {"research_run_id": 7})`.

With backend B active (`MADOSHO_JOB_EXECUTOR_RESEARCH=container`):

1. `resolve_executor` sees the per-queue override and returns a `ContainerExecutor`.
2. `ContainerExecutor` calls the socket-proxy over TCP to create a container:
   image `madosho:local`, command `madosho-run-job run_research '{"research_run_id": 7}'`,
   the shared volumes mounted at their usual paths, the compose network attached,
   and any CPU/memory/GPU caps from config.
3. The proxy forwards the create/start to `/var/run/docker.sock` on the host daemon.
   The job container starts as a sibling container on the host.
4. The worker waits (up to `MADOSHO_JOB_TIMEOUT_RESEARCH`; `compose.container.yaml`
   sets 3600 s - unset, there is no ceiling). The job
   container runs `_run_research_impl(research_run_id=7)` in-process, writes results to
   Postgres and the shared filestore volume, then exits 0.
5. The worker reads the exit code. 0 -> mark success, reap. Non-zero -> mark failed.
6. On timeout: the worker calls docker stop (SIGTERM + grace period, then SIGKILL),
   the job's SIGTERM handler marks the row failed and drops any partial Qdrant collection,
   and the worker marks the job failed.
7. If the worker process is SIGKILLed while a job container is still running, the job
   container keeps running but the worker can no longer reap it. When the worker restarts,
   a startup-only sweeper (runs once per worker boot, never again) checks the DB for rows
   that were left in a running/building state. The sweeper is purely time-based: it fails
   any row whose updated_at has not advanced for longer than the job timeout + a grace
   period. It does NOT introspect live containers or compare against Docker state. A
   consequence: a job container that is externally SIGKILLed while the worker itself
   survives stays stuck until the next worker restart.

### Sweeper scope: ingest and build only (deliberate design)

The startup sweeper reconciles ONLY Document (indexing) and Pipeline (building) jobs.
These are the only job types that create Qdrant collections, which must be cleaned up on
failure to avoid orphaned storage.

Research and Eval runs are deliberately NOT auto-swept. They are user-initiated and
open-ended; a research run only reads the corpus and writes a report row, leaving no
orphaned Qdrant resources. A background timer that auto-killed a long-running research
job would silently destroy user work. These runs are reconciled by the user via explicit
cancel, a separate active-runs management surface.

With backend A (default, `MADOSHO_JOB_EXECUTOR=inproc`):

Steps 2-3 do not happen. The worker calls `_run_research_impl(research_run_id=7)` directly
in its own process. Faster startup, warm model cache. No runtime access needed.

## Backend A: in-process workers

This is the default. Every job runs inside the worker process. No container runtime access
required.

Scale by running more workers:

```
# Pool draining all queues:
docker compose up --scale worker=3

# Queue-pinned workers (prevents a long research job from blocking uploads):
# In your own compose override or shell env:
MADOSHO_WORKER_QUEUES=ingest,ratings   # for an ingest-dedicated worker
MADOSHO_WORKER_QUEUES=research,eval    # for a research-dedicated worker
```

`MADOSHO_WORKER_QUEUES` takes a comma-separated list of queue names. Default is all four
queues (`ingest`, `ratings`, `eval`, `research`). Queue-pinning composes with backend B:
a pinned worker can itself run in container mode for its assigned queues.

## Backend B: per-job containers

Each job runs in its own short-lived container. The worker launches it, caps its resources,
waits, and reaps it. This gives:

- A hard wall-clock timeout with a forced kill -- not available in inproc mode.
- Per-job CPU/memory/GPU caps.
- Isolation: a crashed job container does not take down the worker.

Enable by adding the override:

```
docker compose -f compose.yaml -f compose.container.yaml up
```

Backend B needs the worker to reach a container runtime. That is where the access model
comes in.

### Access model

**No docker-in-docker.** Job containers are siblings on the host's existing daemon. dind
needs `--privileged`, gives worse isolation, and makes GPU passthrough painful.

**The worker stays unprivileged.** It is not root and not `--privileged`. It opens a TCP
connection to a socket-proxy sidecar and asks it to create/start/wait/remove a container.

**The topology:**

```
[worker] --TCP--> [socket-proxy sidecar] --> /var/run/docker.sock (host daemon)
 unprivileged      CONTAINERS=1, POST=1
                   (403 on everything else)
```

The socket-proxy (`lscr.io/linuxserver/socket-proxy`) removes most of the danger surface:
no exec into other containers, no reading other containers' env/secrets, no image push,
no swarm access. The worker never sees the raw socket. GPU passthrough works because the
spawned container talks to the host daemon that already has the NVIDIA runtime.

**The honest caveat:** the proxy filters by API endpoint, not request body. It can allow
or deny `POST /containers/create`, but it cannot inspect what that create asks for. A
create that bind-mounts the host `/` is the classic host-root escape. Backend B
fundamentally needs create + start, so on a root daemon this permission is, in the worst
case, a host-root path if the worker itself is compromised (RCE in madosho's own code).
The job containers are our own code, not hostile workloads. On a single-tenant box the
operator controls, that residual risk is acceptable. The proxy is defense-in-depth over
a raw socket, not a complete boundary.

**Lock-it-down alternative:** run a rootless Podman or rootless Docker daemon as an
unprivileged user. If the worker is compromised, an escape lands as that unprivileged user,
not root. Cost: rootless networking quirks and more GPU-passthrough setup. Point
`MADOSHO_DOCKER_HOST` at the rootless socket or Podman API -- it is a config change, not
a code change.

## Selector: which backend, which queue

Resolution order per job:

1. `MADOSHO_JOB_EXECUTOR_<QUEUE>` (e.g. `MADOSHO_JOB_EXECUTOR_RESEARCH=container`)
2. `MADOSHO_JOB_EXECUTOR` (global default)
3. Fallback: `inproc`

Example: research jobs in containers, everything else in-process:

```
MADOSHO_JOB_EXECUTOR=inproc
MADOSHO_JOB_EXECUTOR_RESEARCH=container
MADOSHO_DOCKER_HOST=tcp://socket-proxy:2375
```

This is the recommended split -- see the warm-cache tradeoff below.

## Warm-cache tradeoff

`inproc` keeps models warm. They load once per worker process and stay resident
(the `_CORPUS_CACHE` behavior). Container mode pays a cold start per job: model weights
are on the shared `hf_cache` volume, but they reload into RAM for every new container.

- High-frequency small ingests -> `inproc` wins. Container cold-start would dominate.
- Long, heavy, isolation-needing jobs (research, big builds, anything that needs a hard
  kill ceiling or a per-job GPU cap) -> `container` wins.

This is the concrete argument for per-queue selection: `ingest=inproc, research=container`
is a stronger default than any single global switch.

## Knob reference

| Variable                             | Default              | Meaning                                         |
|--------------------------------------|----------------------|-------------------------------------------------|
| `MADOSHO_JOB_EXECUTOR`               | `inproc`             | Global backend: `inproc` or `container`         |
| `MADOSHO_JOB_EXECUTOR_<QUEUE>`       | (inherits global)    | Per-queue override (e.g. `_RESEARCH`)           |
| `MADOSHO_WORKER_QUEUES`              | all four queues      | Queues this worker drains (enables A pinning)   |
| `MADOSHO_JOB_IMAGE`                  | `madosho:local`      | Image for job containers (B only)               |
| `MADOSHO_DOCKER_HOST`                | unset                | Proxy URL or socket path; unset = no runtime    |
| `MADOSHO_JOB_NETWORK`                | `madosho_default` *  | Network job containers attach to (B only)       |
| `MADOSHO_JOB_MOUNTS`                 | see below            | Comma-separated `volume:path` pairs (B only)    |
| `MADOSHO_JOB_TIMEOUT`                | unset (no ceiling)   | Global wall-clock ceiling in seconds (B only)   |
| `MADOSHO_JOB_TIMEOUT_<QUEUE>`        | inherits global      | Per-queue override (e.g. `_RESEARCH`, `_INGEST`)|
| `MADOSHO_JOB_CPUS`                   | unset (no cap)       | CPU limit for job containers (B only)           |
| `MADOSHO_JOB_CPUS_<QUEUE>`           | inherits `_CPUS`     | Per-queue CPU override                          |
| `MADOSHO_JOB_MEMORY`                 | unset (no cap)       | Memory limit for job containers (B only)        |
| `MADOSHO_JOB_MEMORY_<QUEUE>`         | inherits `_MEMORY`   | Per-queue memory override                       |
| `MADOSHO_JOB_GPUS`                   | unset (no cap)       | GPU flag for job containers, e.g. `all` (B only)|
| `MADOSHO_JOB_GPUS_<QUEUE>`           | inherits `_GPUS`     | Per-queue GPU override                          |

* `MADOSHO_JOB_NETWORK` default shown is what `compose.container.yaml` sets; the
  bare-binary default is none (no explicit network passed to docker-py on create).

Default mounts (set by `compose.container.yaml`, match the worker's volume paths):

```
madosho_filestore:/data/filestore
madosho_corpora:/data/corpora
madosho_hf_cache:/models
```

The job container must mount these at the SAME paths the worker uses so it reads files
the worker (or app) wrote there.

## Quick-start: enable container mode for research

```bash
# Bring up the stack with the container override:
docker compose -f compose.yaml -f compose.container.yaml up

# The worker now runs research jobs in isolated containers.
# Ingest jobs continue to run in-process (warm model cache).
```

No other changes are needed. The `madosho:local` image is already built by the base
compose, so the job container image is available immediately.
