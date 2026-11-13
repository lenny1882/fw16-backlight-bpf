#!/usr/bin/env python3
"""W4 acceptance: filter attached shows only event reports; detached shows raw.

Usage: sudo python3 -I w4test.py /path/to/fw16-backlight.bpf.o
Phase A (30 s): type normally on the keyboard and press Fn+Space exactly 8 times.
Phase B (5 s): keep typing; the filter is detached. Prints counts and steps only.
"""
import glob, os, select, subprocess, sys, time

obj = sys.argv[1]

LOG = os.path.join(os.path.dirname(os.path.abspath(__file__)), "w4test.log")
logf = open(LOG, "w")
os.chmod(LOG, 0o644)

class Tee:
    def write(self, t):
        sys.__stdout__.write(t)
        logf.write(t)
        logf.flush()
    def flush(self):
        sys.__stdout__.flush()

sys.stdout = Tee()
MAGIC = bytes.fromhex("fb96b1e1")

def find():
    for d in glob.glob("/sys/bus/hid/devices/0003:32AC:0018.*"):
        try:
            desc = open(d + "/report_descriptor", "rb").read(3)
        except OSError:
            continue
        if desc == bytes.fromhex("0631ff"):
            return d, "/dev/" + os.listdir(d + "/hidraw")[0]
    sys.exit("keyboard console not found")

def collect(node, secs):
    fd = os.open(node, os.O_RDONLY | os.O_NONBLOCK)
    reps = []
    t0 = time.time()
    end = t0 + secs
    print(f"  collect start {time.strftime('%H:%M:%S')} on {node}")
    while time.time() < end:
        r, _, _ = select.select([fd], [], [], 0.5)
        if r:
            try:
                reps.append(os.read(fd, 64))
            except BlockingIOError:
                pass
            except OSError as e:
                print(f"  READ FAILED at {time.strftime('%H:%M:%S')} "
                      f"({time.time() - t0:.1f}s in, {len(reps)} reports so far): {e}")
                break
    os.close(fd)
    return reps

def run(*args):
    cmd = ["udev-hid-bpf", "--verbose", *args] if args[0] == "add" else ["udev-hid-bpf", *args]
    p = subprocess.run(cmd, capture_output=True, text=True)
    err = p.stderr + p.stdout
    failed = p.returncode != 0 or "Failed" in err or "WARN" in err
    print(f"  udev-hid-bpf {args[0]}: rc={p.returncode} {'FAILED' if failed else 'ok'}")
    if failed and args[0] == "add":
        logf.write("---- udev-hid-bpf output (verifier log) ----\n" + err + "\n")
        logf.flush()
        print("filter did not load; verifier log is in the log file")
        sys.exit(1)

dev, node = find()
run("remove", dev)
time.sleep(1)
dev, node = find()
run("add", dev, obj)
time.sleep(1)
dev, node = find()
print("Phase A: type and press Fn+Space exactly 8 times (30 s)")
reps = collect(node, 30)
good = [r for r in reps if len(r) == 32 and r[:4] == MAGIC and r[4] == 1 and r[5] == 1
        and r[6] <= 3 and not any(r[7:])]
bad = [r for r in reps if r not in good]
print(f"[A] reports: {len(reps)}, valid events: {len(good)}, other: {len(bad)}")
print(f"    steps: {[r[6] for r in good]}")
if bad:
    print(f"    first other report, byte values only: {list(bad[0])}")
run("remove", dev)
time.sleep(1)
dev, node = find()
print("Phase B: keep typing (5 s)")
raw = collect(node, 5)
print(f"[B] filter detached: reports {len(raw)}, "
      f"with magic {sum(r[:4] == MAGIC for r in raw)}")
