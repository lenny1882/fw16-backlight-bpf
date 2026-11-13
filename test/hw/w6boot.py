#!/usr/bin/env python3
"""W6 reboot check. Two runs, as root:
  sudo python3 -I test/hw/w6boot.py before     (records the hidraw numbers)
  ... reboot, do nothing else, then ...
  sudo python3 -I test/hw/w6boot.py after      (checks the service came up unattended)
Writes w6boot.log and w6boot-before.json next to this script; ends with DONE.
"""
import glob, grp, json, os, select, stat, subprocess, sys, time

HERE = os.path.dirname(os.path.abspath(__file__))
SNAP = os.path.join(HERE, "w6boot-before.json")
logf = open(os.path.join(HERE, "w6boot.log"), "w")
os.chmod(os.path.join(HERE, "w6boot.log"), 0o644)
UNIT = "fw16-backlight-sync.service"
ROLE = {"050109": "keys", "0660ff": "VIA", "0631ff": "console"}

def out(s=""):
    print(s)
    sys.stdout.flush()
    logf.write(s + "\n")
    logf.flush()

def sh(*a):
    p = subprocess.run(list(a), capture_output=True, text=True)
    return p.returncode, (p.stdout + p.stderr).strip()

def snapshot():
    res = {}
    for d in sorted(glob.glob("/sys/class/hidraw/hidraw*")):
        try:
            uev = open(d + "/device/uevent").read()
            rd = open(d + "/device/report_descriptor", "rb").read(3).hex()
        except OSError:
            continue
        for line in uev.splitlines():
            if line.startswith("HID_ID=") and int(line[7:].split(":")[1], 16) == 0x32AC:
                pid = int(line[7:].split(":")[2], 16)
                res[f"{pid:04x}/{ROLE.get(rd, rd)}"] = "/dev/" + os.path.basename(d)
    return res

def perms(node):
    st = os.stat(node)
    try:
        g = grp.getgrgid(st.st_gid).gr_name
    except KeyError:
        g = f"gid{st.st_gid}"
    return g, oct(stat.S_IMODE(st.st_mode))

def unit(prop):
    return sh("systemctl", "show", UNIT, "-p", prop, "--value")[1]

def level(node):
    fd = os.open(node, os.O_RDWR | os.O_NONBLOCK)
    try:
        os.write(fd, bytes([0, 8, 1, 1]) + bytes(29))
        end = time.time() + 1
        while time.time() < end:
            r, _, _ = select.select([fd], [], [], 0.2)
            if r:
                rep = os.read(fd, 64)
                if rep[:3] == bytes([8, 1, 1]):
                    return rep[3]
    finally:
        os.close(fd)

boot_id = open("/proc/sys/kernel/random/boot_id").read().strip()
mode = sys.argv[1] if len(sys.argv) > 1 else ""
try:
    if mode == "before":
        snap = snapshot()
        json.dump({"boot_id": boot_id, "nodes": snap}, open(SNAP, "w"), indent=1)
        out(f"recorded {len(snap)} nodes (boot {boot_id[:8]}):")
        for k, v in snap.items():
            out(f"  {k:14} {v}")
        out("Now reboot, do nothing else, log in, and run the `after` command.")
    elif mode == "after":
        before = json.load(open(SNAP))
        now = snapshot()
        out(f"boot id changed: {before['boot_id'] != boot_id}; uptime {float(open('/proc/uptime').read().split()[0]):.0f} s")
        changed = {k: (before["nodes"].get(k), now.get(k)) for k in now if before["nodes"].get(k) != now[k]}
        out(f"RESULT hidraw numbers: {len(changed)} of {len(now)} nodes changed: {changed or 'none'}")

        out(f"RESULT service: active={unit('ActiveState')} enabled={unit('UnitFileState')} "
            f"NRestarts={unit('NRestarts')} result={unit('Result')}")
        _, jl = sh("journalctl", "-b", "-u", UNIT, "--no-pager", "-o", "short-monotonic")
        out("  journal this boot:")
        for l in jl.splitlines()[:8]:
            out("    " + l[:200])

        want = {"0018/VIA", "0014/VIA", "0018/console"}
        bad = []
        for k, node in now.items():
            g, m = perms(node)
            ok = (g == "fw16-backlight" and m == "0o660") if k in want else (g != "fw16-backlight")
            if not ok:
                bad.append((k, node, g, m))
        out(f"RESULT permissions: nodes not as wanted = {bad or 'none'}")
        n = 0
        for d in glob.glob("/sys/bus/hid/devices/0003:32AC:0018.*"):
            _, t = sh("udev-hid-bpf", "list-loaded", "--syspath", d)
            n += t.count('"bpf_objects"')
        out(f"RESULT filter: loaded on {n} keyboard HID device(s) (want 1)")

        k, p = level(now["0018/VIA"]), level(now["0014/VIA"])
        out(f"RESULT levels after boot with no press: keyboard/numpad = {k}/{p} equal={k == p}")
        out("PRESS Fn+Space ONCE now (8 s)")
        t0, last, ch = time.monotonic(), None, 0
        while time.monotonic() - t0 < 8:
            v = level(now["0018/VIA"])
            if last is not None and v != last:
                ch += 1
            last = v
            time.sleep(0.1)
        time.sleep(0.5)
        k, p = level(now["0018/VIA"]), level(now["0014/VIA"])
        out(f"RESULT press: keyboard changes seen={ch}, keyboard/numpad = {k}/{p} equal={k == p}")
    else:
        out("usage: w6boot.py before|after")
finally:
    out("DONE")
