#!/usr/bin/env python3
"""W6: uninstall leaves nothing, install is idempotent. Run from anywhere:
  sudo python3 -I test/hw/w6uninstall.py
Runs `make SUDO= uninstall` (twice), checks nothing is left, then
`make SUDO= install` (twice) and `make SUDO= reload`, checks everything is back,
and asks for one Fn+Space press. Writes w6uninstall.log; ends with DONE.
"""
import glob, grp, json, os, select, stat, subprocess, sys, time, traceback

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.normpath(os.path.join(HERE, "..", ".."))
LOG = os.path.join(HERE, "w6uninstall.log")
logf = open(LOG, "w")
os.chmod(LOG, 0o644)
UNIT = "fw16-backlight-sync.service"
LIBEXEC = "/usr/local/lib/fw16-backlight"
FILES = ["/etc/udev-hid-bpf/fw16-backlight.bpf.o",
         "/etc/udev/rules.d/99-hid-bpf-fw16-backlight.rules",
         "/etc/udev/rules.d/70-fw16-backlight.rules",
         "/etc/systemd/system/" + UNIT,
         "/etc/sysusers.d/fw16-backlight.conf",
         LIBEXEC + "/fw16-backlight-sync",
         LIBEXEC + "/grant-console",
         LIBEXEC]

def out(s=""):
    print(s)
    sys.stdout.flush()
    logf.write(s + "\n")
    logf.flush()

def sh(*a, cwd=None):
    p = subprocess.run(list(a), capture_output=True, text=True, cwd=cwd)
    return p.returncode, (p.stdout + p.stderr).strip()

def make(*targets):
    rc, txt = sh("make", "SUDO=", *targets, cwd=ROOT)
    return rc, txt

def present():
    return [f for f in FILES if os.path.exists(f)]

def group_exists():
    try:
        grp.getgrnam("fw16-backlight")
        return True
    except KeyError:
        return False

def kb_hid():
    return glob.glob("/sys/bus/hid/devices/0003:32AC:0018.*")

def loaded_programs():
    n = 0
    for d in kb_hid():
        rc, txt = sh("udev-hid-bpf", "list-loaded", "--syspath", d)
        try:
            n += len(json.loads(txt)["devices"])
        except (ValueError, KeyError):
            out(f"  could not parse list-loaded for {d}: {txt[:100]!r}")
    return n

def hidraw_groups():
    res = {}
    for d in glob.glob("/sys/class/hidraw/hidraw*"):
        try:
            if "000032AC" not in open(d + "/device/uevent").read():
                continue
        except OSError:
            continue
        node = "/dev/" + os.path.basename(d)
        st = os.stat(node)
        try:
            gname = grp.getgrgid(st.st_gid).gr_name
        except KeyError:
            gname = f"gid{st.st_gid}(no such group)"
        res[node] = (gname, oct(stat.S_IMODE(st.st_mode)))
    return res

def state(prop):
    return sh("systemctl", "show", UNIT, "-p", prop, "--value")[1]

def find_via(pid):
    for d in glob.glob(f"/sys/bus/hid/devices/0003:32AC:{pid:04X}.*"):
        try:
            if open(d + "/report_descriptor", "rb").read(3) == bytes.fromhex("0660ff"):
                return "/dev/" + os.listdir(d + "/hidraw")[0]
        except OSError:
            pass

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

try:
    # The phony check-build target makes `all` never "up to date"; ask about the files.
    rc, txt = sh("make", "-q", "build/fw16-backlight.bpf.o", "build/fw16-backlight-sync",
                 "build/fw16-backlight-sync.service", "build/70-fw16-backlight.rules", cwd=ROOT)
    if rc != 0:
        out("FAIL build is not up to date; run `make` as yourself first (running make as root "
            "would leave root-owned files in build/)")
        raise SystemExit
    out(f"before: installed files={len(present())}/{len(FILES)} group={group_exists()} "
        f"unit active={state('ActiveState')} enabled={state('UnitFileState')} "
        f"loaded programs={loaded_programs()}")

    out("UNINSTALL")
    rc1, t1 = make("uninstall")
    out(f"  make uninstall rc={rc1}")
    rc2, t2 = make("uninstall")
    out(f"  make uninstall again rc={rc2} (want 0: idempotent)")
    time.sleep(1)
    left = present()
    g = [(n, v) for n, v in hidraw_groups().items() if v != ("root", "0o600")]
    out(f"RESULT uninstall: files left={left} group exists={group_exists()} "
        f"unit active={state('ActiveState')} loaded={state('LoadState')} "
        f"loaded programs={loaded_programs()} nodes not root:root 0600={g} (want [])")
    out(f"  numpad/keyboard still enumerated: {find_via(0x14)} {find_via(0x18)}")
    if rc1 or rc2:
        out("  make output tail: " + (t2 or t1)[-600:])

    out("INSTALL")
    rc1, t1 = make("install")
    out(f"  make install rc={rc1}")
    rc2, t2 = make("reload")
    out(f"  make reload rc={rc2}")
    rc3, t3 = make("install")
    out(f"  make install again rc={rc3} (want 0: idempotent)")
    time.sleep(4)
    miss = [f for f in FILES if not os.path.exists(f)]
    g = sorted(n for n, v in hidraw_groups().items() if v[0] == "fw16-backlight")
    out(f"RESULT install: missing files={miss} group exists={group_exists()} "
        f"unit active={state('ActiveState')} enabled={state('UnitFileState')} "
        f"loaded programs={loaded_programs()} (want 1) nodes in the group={g} (want 3)")
    for rc, t in ((rc1, t1), (rc2, t2), (rc3, t3)):
        if rc:
            out("  make output tail: " + t[-600:])

    out("PRESS Fn+Space ONCE now (8 s)")
    kb, np = find_via(0x18), find_via(0x14)
    t0, last, changes = time.monotonic(), None, 0
    while time.monotonic() - t0 < 8:
        k = level(kb)
        if last is not None and k != last:
            changes += 1
        last = k
        time.sleep(0.1)
    time.sleep(0.5)
    k, n = level(kb), level(np)
    out(f"RESULT press: keyboard changes seen={changes}, keyboard/numpad={k}/{n} equal={k == n}")
except SystemExit:
    pass
except Exception:
    out("EXCEPTION " + traceback.format_exc())
finally:
    out("DONE")
