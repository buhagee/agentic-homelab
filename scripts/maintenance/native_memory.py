"""Observe native memory without changing the service, cgroup, or deployment."""
from pathlib import Path
import re
import subprocess
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'lib'))
from incident import main as report

UNIT = 'qacey-openchamber.service'
GROUP = Path('/sys/fs/cgroup/system.slice') / UNIT


def classify(active, oom, psi):
    up = 'healthy' if active == 'active' else 'unknown'
    sustained = re.search(r'^some .*\bavg300=(\d+(?:\.\d+)?)\b', psi, re.M)
    return {
        'oom': 'failed' if oom is True else up if oom is False else 'unknown',
        'pressure': ('failed' if float(sustained[1]) >= 5 else 'healthy')
                    if sustained and up == 'healthy' else 'unknown',
        'service': 'failed' if active == 'failed' else up,
    }


def main():
    active = subprocess.run(['/usr/bin/systemctl', 'show', UNIT, '-p', 'ActiveState', '--value'],
                            capture_output=True, text=True, timeout=10, check=True).stdout.strip()
    # Overlap successive 15-minute samples; the incident store deduplicates.
    # Kernel records survive a service restart that resets its cgroup counters.
    kernel = subprocess.run(['/usr/bin/journalctl', '-k', '--since', '35 minutes ago', '-n', '1',
                             '--grep', r'oom-kill:.*task_memcg=/system\.slice/qacey-openchamber\.service(?:/|,)',
                             '--no-pager', '-o', 'cat'], capture_output=True, text=True, timeout=15)
    oom = None
    if kernel.returncode == 0 and 'oom-kill:' in kernel.stdout:
        oom = True
    elif kernel.returncode == 1 and not kernel.stderr.strip() and kernel.stdout.strip() in ('', '-- No entries --'):
        oom = False
    try:
        psi = (GROUP / 'memory.pressure').read_text()
        size = (GROUP / 'memory.current').read_text().strip()
    except FileNotFoundError:
        psi, size = '', 'unknown'
    detail = f'{UNIT}: {active}; recent kernel OOM={oom}; memory.current={size}; {psi.strip()}'
    print(detail)
    failed = False
    for key, value in classify(active, oom, psi).items():
        try:
            report([f'openchamber.{key}', value, detail])
        except Exception as exc:
            print(f'{key}: incident observation or delivery failed ({type(exc).__name__})', file=sys.stderr)
            failed = True
    return int(failed)


if __name__ == '__main__':
    sys.exit(main())
