#!/usr/bin/env python3
"""W6 check of an installed system. Run after `make install` and `make reload`:
  sudo python3 -I test/hw/w6check.py
Writes w6check.log next to this script and ends with a DONE line.

A  permissions of every 32AC hidraw node (S4)
B  service identity: unprivileged, no capabilities (S3)
C  systemd-analyze verify and security
D  press sync with the installed service (you press Fn+Space twice)
E  fail closed (S2): the filter is removed under the running service, you press
   one key; then permissions are reset, the service is restarted, and the
   filter is restored (you press Fn+Space once)
"""
import glob, grp, os, pwd, select, stat, subprocess, sys, time

HERE = os.path.dirname(os.path.abspath(__file__))
LOG = os.path.join(HERE, "w6check.log")
logf = open(LOG, "w")
os.chmod(LOG, 0o644)
UNIT = "fw16-backlight-sync.service"
GROUP = "fw16-backlight"

def out(s=""):
    print(s)
    sys.stdout.flush()
    logf.write(s + "\n")
    logf.flush()

def sh(*a, check=False):
    p = subprocess.run(list(a), capture_output=True, text=True)
    return p.returncode, (p.stdout + p.stderr).strip()

ROLE = {bytes.fromhex("050109"): "keys", bytes.fromhex("0660ff"): "VIA", bytes.fromhex("0631ff"): "console"}

def nodes():
    res = []
    for d in sorted(glob.glob("/sys/class/hidraw/hidraw*")):
        try:
            uev = open(d + "/device/uevent").read()
            rd = open(d + "/device/report_descriptor", "rb").read(3)
        except OSError:
            continue
        pid = None
        for line in uev.splitlines():
            if line.startswith("HID_ID="):
                _, v, p = line[7:].split(":")
                if int(v, 16) == 0x32AC:
                    pid = int(p, 16)
        if pid is not None:
            res.append((pid, ROLE.get(rd, rd.hex()), "/dev/" + os.path.basename(d)))
    return res

def perms(node):
    st = os.stat(node)
    return pwd.getpwuid(st.st_uid).pw_name, grp.getgrgid(st.st_gid).gr_name, oct(stat.S_IMODE(st.st_mode))

def table():
    ok = True
    for pid, role, node in nodes():
        u, g, m = perms(node)
        want_group = (role == "VIA" and pid in (0x18, 0x14)) or (role == "console" and pid == 0x18)
        good = (g == GROUP and m == "0o660") if want_group else (g != GROUP)
        ok &= good
        out(f"  {node:13} {pid:04x} {role:8} {u}:{g} {m}  "
            f"{'ok' if good else 'WRONG'} (want {'group access' if want_group else 'no group access'})")
    return ok

def find(pid, role):
    for p, r, n in nodes():
        if p == pid and r == role:
            return n

def via_get(node):
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

def levels():
    return via_get(find(0x18, "VIA")), via_get(find(0x14, "VIA"))

def watch(secs):
    t0, last, changes = time.monotonic(), None, 0
    while time.monotonic() - t0 < secs:
        k = levels()[0]
        if last is not None and k != last:
            changes += 1
        last = k
        time.sleep(0.1)
    return changes

def kb_hid_devices():
    return glob.glob("/sys/bus/hid/devices/0003:32AC:0018.*")

def unit(prop):
    return sh("systemctl", "show", UNIT, "-p", prop, "--value")[1]

def reload_filter():
    for d in kb_hid_devices():
        sh("udev-hid-bpf", "remove", d)
    sh("udevadm", "trigger", "--action=add", "--subsystem-match=hid",
       "--property-match=MODALIAS=hid:b0003g0001v000032ACp00000018")
    sh("udevadm", "settle")
    sh("udevadm", "trigger", "--action=change", "--subsystem-match=hidraw")
    sh("udevadm", "settle")

try:
    out("A permissions (S4)")
    for d in kb_hid_devices():
        rc, txt = sh("udev-hid-bpf", "list-loaded", "--syspath", d)
        out(f"  list-loaded {os.path.basename(d)}: rc={rc} {txt[:300]!r}")
    out(f"RESULT A: all nodes as wanted = {table()}")

    out("B service identity (S3)")
    active = unit("ActiveState")
    pid = unit("MainPID")
    out(f"  state={active} MainPID={pid} NRestarts={unit('NRestarts')}")
    if pid and pid != "0":
        st = open(f"/proc/{pid}/status").read()
        f = {l.split(":")[0]: l.split(":", 1)[1].strip() for l in st.splitlines() if ":" in l}
        gid = grp.getgrnam(GROUP).gr_gid
        uid = int(f["Uid"].split()[0])
        out(f"  uid={uid} (root=0) groups={f['Groups']} (has {GROUP} {gid}: {str(gid) in f['Groups'].split()}) "
            f"CapEff={f['CapEff']} NoNewPrivs={f['NoNewPrivs']}")
        out(f"RESULT B: unprivileged={uid != 0} no_caps={int(f['CapEff'], 16) == 0}")
    else:
        out("RESULT B: service has no main pid (not running)")

    out("C systemd-analyze")
    rc, txt = sh("systemd-analyze", "verify", UNIT)
    out(f"  verify rc={rc} {txt[:300]}")
    rc, txt = sh("systemd-analyze", "security", "--no-pager", UNIT)
    out("  security (last lines):")
    for l in txt.splitlines()[-6:]:
        out("    " + l)

    out("D press sync. Press Fn+Space TWICE now, about 2 s apart (9 s)")
    ch = watch(9)
    k, n = levels()
    out(f"RESULT D: keyboard changes seen={ch}, keyboard/numpad now={k}/{n} equal={k == n}")

    out("E fail closed (S2)")
    for d in kb_hid_devices():
        sh("udev-hid-bpf", "remove", d)
    out("  filter removed from the keyboard. Press ONE ordinary key now (the console is raw again) (6 s)")
    time.sleep(6)
    out(f"RESULT E1: state={unit('ActiveState')} result={unit('Result')} "
        f"exit_status={unit('ExecMainStatus')} (want failed / exit-code / 2)")
    _, jl = sh("journalctl", "-u", UNIT, "--no-pager", "-n", "5", "-o", "cat")
    out("  service log: " + " | ".join(jl.splitlines()[-3:]))

    sh("udevadm", "trigger", "--action=change", "--subsystem-match=hidraw")
    sh("udevadm", "settle")
    con = find(0x18, "console")
    u, g, m = perms(con)
    out(f"RESULT E2: console node after the permission reset: {u}:{g} {m} "
        f"(want not {GROUP}) -> {'ok' if g != GROUP else 'WRONG'}")
    _, jl = sh("journalctl", "-t", "fw16-backlight", "--no-pager", "-n", "2", "-o", "cat")
    out("  helper log: " + " | ".join(jl.splitlines()[-2:]))

    sh("systemctl", "reset-failed", UNIT)
    sh("systemctl", "restart", UNIT)
    time.sleep(4)
    _, jl = sh("journalctl", "-u", UNIT, "--no-pager", "-n", "3", "-o", "cat")
    out(f"RESULT E3: after restart state={unit('ActiveState')}; log: " + " | ".join(jl.splitlines()[-2:]))

    reload_filter()
    time.sleep(4)
    u, g, m = perms(find(0x18, "console"))
    out(f"  filter restored; console node {u}:{g} {m}")
    out("  Press Fn+Space ONCE now (8 s)")
    ch = watch(8)
    k, n = levels()
    out(f"RESULT E4: keyboard changes seen={ch}, keyboard/numpad now={k}/{n} equal={k == n}, "
        f"service state={unit('ActiveState')}")
finally:
    out("DONE")
