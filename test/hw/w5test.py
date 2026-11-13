#!/usr/bin/env python3
"""W5 hardware check. Usage: sudo python3 -I w5test.py FILTER.bpf.o SERVICE_BINARY

1. attach the filter
2. numpad deliberately unequal to keyboard -> start service -> equal?
3. restart service with levels already equal -> still equal?
4. you press Fn+Space 4 times (about 2 s apart): latency until numpad matches
5. idle CPU of the service over 5 s
Writes w5test.log next to this script and ends with a DONE line.
"""
import glob, os, select, subprocess, sys, time

obj, svc = sys.argv[1], sys.argv[2]
HERE = os.path.dirname(os.path.abspath(__file__))
LOG = os.path.join(HERE, "w5test.log")
logf = open(LOG, "w")
os.chmod(LOG, 0o644)

def out(s=""):
    print(s)
    sys.stdout.flush()
    logf.write(s + "\n")
    logf.flush()

def find(pid, desc):
    for d in glob.glob(f"/sys/bus/hid/devices/0003:32AC:{pid:04X}.*"):
        try:
            if open(d + "/report_descriptor", "rb").read(3) == desc:
                return d, "/dev/" + os.listdir(d + "/hidraw")[0]
        except OSError:
            pass
    return None, None

VIA = bytes.fromhex("0660ff")
CON = bytes.fromhex("0631ff")

def via(node, req):
    fd = os.open(node, os.O_RDWR | os.O_NONBLOCK)
    try:
        os.write(fd, bytes([0]) + req + bytes(32 - len(req)))
        end = time.time() + 1
        while time.time() < end:
            r, _, _ = select.select([fd], [], [], 0.2)
            if r:
                rep = os.read(fd, 64)
                if rep[:3] == req[:3]:
                    return rep[3]
    finally:
        os.close(fd)
    return None

def levels():
    _, kb = find(0x0018, VIA)
    _, np = find(0x0014, VIA)
    return via(kb, bytes([8, 1, 1])), via(np, bytes([8, 1, 1]))

def set_np(level):
    _, np = find(0x0014, VIA)
    via(np, bytes([7, 1, 1, level]))

def udev(*a):
    p = subprocess.run(["udev-hid-bpf", *a], capture_output=True, text=True)
    return p.returncode, (p.stderr + p.stdout)

def start():
    return subprocess.Popen([svc], stderr=open(os.path.join(HERE, "w5svc.log"), "w"))

def cpu_ticks(pid):
    f = open(f"/proc/{pid}/stat").read().rsplit(")", 1)[1].split()
    return int(f[11]) + int(f[12])

try:
    d, _ = find(0x0018, CON)
    if not d:
        out("FAIL keyboard console not found (module not enumerated?)")
        raise SystemExit
    udev("remove", d)
    time.sleep(1)
    d, _ = find(0x0018, CON)
    rc, txt = udev("add", d, obj)
    out(f"filter add rc={rc}")
    if rc != 0 or "Failed" in txt:
        out("FAIL filter did not load")
        raise SystemExit
    time.sleep(1)

    kb, np = levels()
    out(f"levels at start: keyboard={kb} numpad={np}")
    other = [v for v in (0, 85, 170, 255) if v != kb][0]
    set_np(other)
    time.sleep(0.3)
    out(f"forced unequal: keyboard/numpad = {levels()}")

    p = start()
    time.sleep(1.5)
    out(f"RESULT unequal start -> after 1.5 s: keyboard/numpad = {levels()}")
    p.terminate(); p.wait()

    p = start()
    time.sleep(1.5)
    out(f"RESULT equal start -> after 1.5 s: keyboard/numpad = {levels()}")

    out("PHASE press Fn+Space 4 times, about 2 s apart, starting now (14 s)")
    t0 = time.monotonic()
    log = []
    last = None
    while time.monotonic() - t0 < 14:
        k, n = levels()
        if (k, n) != last:
            log.append((time.monotonic() - t0, k, n))
            last = (k, n)
        time.sleep(0.05)
    for t, k, n in log:
        out(f"  t={t:5.2f}s keyboard={k} numpad={n}")
    kb_changes = [(t, k) for i, (t, k, n) in enumerate(log) if i and k != log[i - 1][1]]
    out(f"RESULT keyboard level changes seen: {len(kb_changes)}")
    for t, k in kb_changes:
        m = next((t2 for t2, k2, n2 in log if t2 >= t and n2 == k), None)
        out(f"  keyboard -> {k} at {t:.2f}s: numpad matched "
            + (f"after {m - t:.2f}s" if m is not None else "NEVER"))

    out("PHASE idle: do not touch the keyboard (5 s)")
    a = cpu_ticks(p.pid)
    time.sleep(5)
    b = cpu_ticks(p.pid)
    out(f"RESULT service CPU over 5 s idle: {b - a} ticks (100 ticks = 1 s)")
    p.terminate(); p.wait()
    out(f"service stderr: {open(os.path.join(HERE, 'w5svc.log')).read().strip() or '(empty)'}")
finally:
    d, _ = find(0x0018, CON)
    if d:
        udev("remove", d)
    out("DONE")
