#!/usr/bin/env python3
"""Single startup entrypoint for full VAMP stack.

Starts:
- BuzzService (9009)
- SwarmGuard (9010)
- Main Flask + coordinator loop (5000)
"""

import atexit
import os
import signal
import subprocess
import sys
import time


def _spawn(cmd, name):
    proc = subprocess.Popen(cmd)
    print(f"[start_vamp] started {name} pid={proc.pid}: {' '.join(cmd)}")
    return proc


def main():
    os.environ.setdefault("PYTHONUNBUFFERED", "1")

    procs = []
    procs.append(_spawn([sys.executable, "-m", "uvicorn", "buzzservice.service:app", "--host", "0.0.0.0", "--port", "9009"], "buzzservice"))
    procs.append(_spawn([sys.executable, "-m", "uvicorn", "swarmguard_service.service:app", "--host", "0.0.0.0", "--port", "9010"], "swarmguard"))

    def cleanup(*_):
        for p in procs:
            if p.poll() is None:
                p.terminate()
        for p in procs:
            try:
                p.wait(timeout=5)
            except Exception:
                if p.poll() is None:
                    p.kill()

    atexit.register(cleanup)
    signal.signal(signal.SIGINT, cleanup)
    signal.signal(signal.SIGTERM, cleanup)

    # Wallet monitor runs as part of main coordinator initialization when config is set.
    main_proc = _spawn([sys.executable, "main.py"], "main")
    procs.append(main_proc)

    # Keep parent alive and propagate child failures.
    try:
        while True:
            if main_proc.poll() is not None:
                code = main_proc.returncode
                print(f"[start_vamp] main exited with code {code}")
                return code or 0
            time.sleep(1)
    finally:
        cleanup()


if __name__ == "__main__":
    sys.exit(main())
