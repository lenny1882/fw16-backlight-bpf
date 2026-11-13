#!/usr/bin/env python3
"""W6 physical re-seat and suspend/resume. As root, with the service installed:
  sudo python3 -I test/hw/w6hotplug.py [numpad-sim] [keyboard-sim] [suspend] [numpad] [keyboard]
No arguments runs numpad-sim and keyboard-sim. Writes w6hotplug.log; ends with DONE.

numpad-sim, keyboard-sim : the script makes the kernel re-enumerate the module (USB
                           `authorized` 0 then 1), the same path as a re-seat, no hands.
                           The keyboard is dead for a second or two.
suspend                  : the script suspends the laptop; wake it with the power button
numpad, keyboard         : physical re-seat (you pull the module out and push it back in)
After each, you press Fn+Space once.
"""
import glob, grp, os, select, stat, subprocess, sys, time

HERE = os.path.dirname(os.path.abspath(__file__))
logf = open(os.path.join(HERE, "w6hotplug.log"), "w")
os.chmod(os.path.join(HERE, "w6hotplug.log"), 0o644)
UNIT = "fw16-backlight-sync.service"
ROLE = {"0660ff": "VIA", "0631ff": "console"}

def out(s=""):
    print(s)
    sys.stdout.flush()
    logf.write(s + "\n")
    logf.flush()

def sh(*a):
    p = subprocess.run(list(a), capture_output=True, text=True)
    return p.returncode, (p.stdout + p.stderr).strip()

def nodes():
    res = {}
    for d in glob.glob("/sys/class/hidraw/hidraw*"):
        try:
            uev = open(d + "/device/uevent").read()
            rd = open(d + "/device/report_descriptor", "rb").read(3).hex()
        except OSError:
            continue
        for line in uev.splitlines():
            if line.startswith("HID_ID=") and int(line[7:].split(":")[1], 16) == 0x32AC and rd in ROLE:
                pid = int(line[7:].split(":")[2], 16)
                res[f"{pid:04x}/{ROLE[rd]}"] = "/dev/" + os.path.basename(d)
    return res

def unit(prop):
    return sh("systemctl", "show", UNIT, "-p", prop, "--value")[1]

def perms(node):
    st = os.stat(node)
    try:
        g = grp.getgrgid(st.st_gid).gr_name
    except KeyError:
        g = f"gid{st.st_gid}"
    return f"{g} {oct(stat.S_IMODE(st.st_mode))}"

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
    except OSError:
        return None
    finally:
        os.close(fd)

def loaded():
    n = 0
    for d in glob.glob("/sys/bus/hid/devices/0003:32AC:0018.*"):
        _, t = sh("udev-hid-bpf", "list-loaded", "--syspath", d)
        n += t.count('"bpf_objects"')
    return n

def wait_for(pid, present, timeout):
    t0 = time.time()
    while time.time() - t0 < timeout:
        here = any(k.startswith(f"{pid:04x}/") for k in nodes())
        if here == present:
            return time.time() - t0
        time.sleep(0.2)
    return None

def check_and_press(label):
    time.sleep(3)
    n = nodes()
    want = {"0018/VIA", "0014/VIA", "0018/console"}
    out(f"  nodes now: " + ", ".join(f"{k} {v} [{perms(v)}]" for k, v in sorted(n.items())))
    miss = want - set(n)
    kb, np = (level(n["0018/VIA"]), level(n["0014/VIA"])) if not miss else (None, None)
    out(f"RESULT {label} before the press: service active={unit('ActiveState')} NRestarts={unit('NRestarts')} "
        f"filter loaded on {loaded()} device(s) (want 1) missing nodes={sorted(miss) or 'none'} "
        f"levels keyboard/numpad={kb}/{np}")
    out("  PRESS Fn+Space ONCE now (8 s)")
    t0, last, ch = time.monotonic(), None, 0
    while time.monotonic() - t0 < 8:
        n = nodes()
        v = level(n["0018/VIA"]) if "0018/VIA" in n else None
        if last is not None and v is not None and v != last:
            ch += 1
        last = v if v is not None else last
        time.sleep(0.1)
    time.sleep(0.5)
    n = nodes()
    kb, np = level(n["0018/VIA"]), level(n["0014/VIA"])
    out(f"RESULT {label} after the press: keyboard changes seen={ch}, keyboard/numpad={kb}/{np} "
        f"equal={kb == np}, service active={unit('ActiveState')}")

def usb_dev(pid):
    for d in glob.glob(f"/sys/bus/hid/devices/0003:32AC:{pid:04X}.*"):
        p = os.path.realpath(d)
        while p != "/" and not os.path.exists(p + "/idVendor"):
            p = os.path.dirname(p)
        if os.path.exists(p + "/authorized"):
            return p

def simulate(pid, name):
    dev = usb_dev(pid)
    if not dev:
        out(f"RESULT {name}-sim: could not locate the USB device; skipping")
        return
    out(f"PHASE {name}-sim: re-enumerating the {name} module")
    try:
        open(dev + "/authorized", "w").write("0")
        time.sleep(1)
        open(dev + "/authorized", "w").write("1")
    finally:
        try:
            open(dev + "/authorized", "w").write("1")
        except OSError:
            pass
    time.sleep(1)
    b = wait_for(pid, True, 30)
    if b is None:
        out(f"RESULT {name}-sim: module did not come back; skipping")
        return
    out(f"  {name} module back")
    check_and_press(f"{name} re-enumeration")

def reseat(pid, name):
    out(f"PHASE {name}: PULL THE {name.upper()} MODULE OUT NOW (waiting up to 60 s)")
    g = wait_for(pid, False, 60)
    if g is None:
        out(f"RESULT {name}: module never disappeared; skipping")
        return
    out(f"  {name} module gone after {g:.1f} s. Push it back in (waiting up to 90 s)")
    b = wait_for(pid, True, 90)
    if b is None:
        out(f"RESULT {name}: module did not come back; skipping")
        return
    out(f"  {name} module back after {b:.1f} s")
    check_and_press(f"{name} re-seat")

phases = sys.argv[1:] or ["numpad-sim", "keyboard-sim"]
try:
    out(f"start: service active={unit('ActiveState')} filter loaded on {loaded()} device(s)")
    if "numpad-sim" in phases:
        simulate(0x14, "numpad")
    if "keyboard-sim" in phases:
        simulate(0x18, "keyboard")
    if "numpad" in phases:
        reseat(0x14, "numpad")
    if "keyboard" in phases:
        reseat(0x18, "keyboard")
    if "suspend" in phases:
        out("PHASE suspend: the laptop suspends in 5 s. Wake it with the power button.")
        time.sleep(5)
        t0 = time.time()
        mono0 = time.monotonic()
        sh("systemctl", "suspend")
        time.sleep(1)
        out(f"  resumed (wall clock moved {time.time() - t0:.0f} s)")
        check_and_press("suspend/resume")
finally:
    out("DONE")
