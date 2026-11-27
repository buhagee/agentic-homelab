# OpenChamber memory incident

The home server has about 30.6 GiB RAM and 4 GiB swap. On November 27 the kernel
reported three global OOM kills in `qacey-openchamber.service`. At 17:53 UTC a
single victim used 19.49 GiB anonymous RSS; the unit peaked at 21.4 GiB.
`MainThread` does not identify the executable. Do not attribute a leak to a
session based solely on token counts or to a binary based on its cgroup.

The managed unit throttles at 8 GiB and caps the whole service tree at 12 GiB,
with a separate 2 GiB swap ceiling. A cgroup OOM terminates the unit as a group.
Systemd waits 15 seconds before restarting and permits three starts per 15
minutes. These are host protection limits, not a measured allowance for every
build. Reassess under real workloads; do not induce an OOM to test them.

During this incident the safe bridge to the managed unit is a **current-cgroup
only** emergency cap. With the native deployment lock held, verify the unit's
active invocation, exact cgroup, memory and swap usage, and the absence of a
transaction. Write `memory.high`, `memory.swap.max`, then `memory.max` only if
current usage is comfortably below each limit. Record and verify the actual
values. This does not edit the unit, change the baseline or create a systemd
drop-in. The kernel settings may disappear at service restart or manager
reconfiguration. Do not rely on them for the next invocation. Do not run swapoff.

Use the supported session interrupt and verify **both** inactive execution and
`goal.status=paused` before blaming or resuming autonomous work. Preserve pending
dispatch results, worktrees and history. Sample unit and host memory PSI, swap,
`memory.current`, `memory.stat` and `memory.events` over time. A flat short
sample is not proof of a fix. A new cgroup resets its counters; consult the
kernel journal across restarts. If the start limit trips, investigate before
manually clearing it. Do not bypass idle admission or reopen revoked ingress.

After a reviewed merge, let the independent reconciliation timer publish the
managed unit at an idle window. Compare `systemctl show` and the cgroup files;
verify both runtimes and the originally intended ingress before declaring
recovery. Do not re-enroll to accept unexpected drift.
