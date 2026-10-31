# Public request coordination

The application host now uses a single in-process coordinator per exchange.
Priority 0 is manual holdings/price-alert collection; priority 1 is opportunity
scanning. Waiting priority-0 requests precede waiting scans; FIFO within a priority.
Only one public HTTP request owns an exchange lease, with a conservative one-second
gap after release. The pinned SDK also retains its own exchange/weight limiter.
This is an engineering throttle, not a claim to know every exchange's rate budget.

The isolated worker asks the host for a permit before each SDK HTTP transport
call and releases it afterwards. The worker retains one SDK instance. Both the
existing host_reader path and coordinated probes use this protocol, so directory,
statistics, OHLCV and books participate in the same host queue. No stock data
source, account endpoint, credentials or generic agent method is introduced.

Requests already in flight are not preempted: urgent collection can wait for one
request/SDK network timeout (15 seconds), plus its own request work. It does not
wait for an entire 180-second scan. Sustained urgent traffic may exhaust a scan's
deadline; it must then report failure/partial coverage, never starve urgent work.

Cancellation/deadline terminates the owned worker before releasing an active
lease. Windows termination uses the owned process tree; Python helpers are not
left running. Queue waits are cancellable. Framing, message size, IDs, module
names and options are bounded, and AI/auth/PYTHONPATH are not forwarded.

Standalone CLI behavior remains opt-in and unchanged unless the coordinator is
supplied by the host. Avoid running separate CLI scans concurrently with the app.
The guarantee is for one application process. Multiple uvicorn workers, multiple
containers or unrelated clients need a shared external limiter and are not
supported by this stage. No background scan or scheduler is added here.

Tests cover priority/FIFO, mutual exclusion, cancellation, spacing, independent
exchanges, actual pinned transport hooking and real child-protocol rejection.
Real network priority/cancellation acceptance is recorded separately.
