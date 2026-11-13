#!/usr/bin/env python3
"""W5 VIA-failure check with a virtual numpad. Usage:
  sudo python3 -I w5via.py FILTER.bpf.o SERVICE_BINARY

The real numpad is deauthorized for the test; a uhid device with the numpad's
ids and VIA descriptor stands in and misbehaves on cue. Needs /dev/uhid
(sudo modprobe uhid). Writes w5via.log, w5via-svc.log; ends with DONE.
"""
import glob, os, select, struct, subprocess, sys, time

obj, svc = sys.argv[1], sys.argv[2]
HERE = os.path.dirname(os.path.abspath(__file__))
LOG = os.path.join(HERE, "w5via.log")
SVCLOG = os.path.join(HERE, "w5via-svc.log")
logf = open(LOG, "w")
os.chmod(LOG, 0o644)

def out(s=""):
    print(s)
    sys.stdout.flush()
    logf.write(s + "\n")
    logf.flush()

VIA = bytes.fromhex("0660ff")
CON = bytes.fromhex("0631ff")
# QMK raw HID: 32-byte input and output reports, no report id.
VIA_DESC = bytes.fromhex("06 60 ff 09 61 a1 01 09 62 15 00 26 ff 00 95 20 75 08 81 02 "
                         "09 63 15 00 26 ff 00 95 20 75 08 91 02 c0".replace(" ", ""))

UHID_DESTROY, UHID_OUTPUT, UHID_CREATE2, UHID_INPUT2 = 1, 6, 11, 12
UHID_SET_REPORT, UHID_SET_REPORT_REPLY = 13, 14
EVSZ = 4376

def ev(t, payload=b""):
    return (struct.pack("<I", t) + payload).ljust(EVSZ, b"\0")

def find(pid, desc):
    for d in glob.glob(f"/sys/bus/hid/devices/0003:32AC:{pid:04X}.*"):
        try:
            if open(d + "/report_descriptor", "rb").read(3) == desc:
                return d, "/dev/" + os.listdir(d + "/hidraw")[0]
        except OSError:
            pass
    return None, None

def usb_dev(pid):
    d, _ = find(pid, VIA)
    if not d:
        return None
    p = os.path.realpath(d)
    while p != "/" and not os.path.exists(p + "/idVendor"):
        p = os.path.dirname(p)
    return p if os.path.exists(p + "/authorized") else None

def kb_level():
    _, node = find(0x0018, VIA)
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

def udev(*a):
    p = subprocess.run(["udev-hid-bpf", *a], capture_output=True, text=True)
    return p.returncode, p.stderr + p.stdout

class Fake:
    def __init__(self):
        self.fd = os.open("/dev/uhid", os.O_RDWR | os.O_NONBLOCK)
        self.mode = "silent"
        self.last_set = None
        self.requests = []
        name = b"fake numpad (w5via test)"
        self.w(ev(UHID_CREATE2, struct.pack("<128s64s64sHHIIII4096s", name, b"", b"",
                                            len(VIA_DESC), 3, 0x32ac, 0x0014, 0, 0,
                                            VIA_DESC)))

    def w(self, b):
        os.write(self.fd, b)

    def reply(self, data):
        self.w(ev(UHID_INPUT2, struct.pack("<H4096s", 32, data.ljust(32, b"\0")[:32])))

    def handle(self, req):
        off = next((o for o in (0, 1) if req[o:o + 3] in (b"\x07\x01\x01", b"\x08\x01\x01")), None)
        self.requests.append((self.mode, req[:6].hex()))
        if off is None or self.mode == "silent":
            return
        cmd = req[off:off + 32]
        if cmd[0] == 7:
            self.last_set = cmd[3]
        if self.mode == "wrong":
            self.reply(bytes([0xee, 0xee, 0xee, 0]))
        else:
            self.reply(cmd)

    def pump(self, secs):
        end = time.time() + secs
        while time.time() < end:
            r, _, _ = select.select([self.fd], [], [], 0.05)
            while r:
                try:
                    b = os.read(self.fd, EVSZ)
                except BlockingIOError:
                    break
                t = struct.unpack_from("<I", b)[0]
                if t == UHID_OUTPUT:
                    data, size, _rt = struct.unpack_from("<4096sHB", b, 4)
                    self.handle(data[:size])
                elif t == UHID_SET_REPORT:
                    rid, _rn, _rt, size, data = struct.unpack_from("<IBBH4096s", b, 4)
                    self.w(ev(UHID_SET_REPORT_REPLY, struct.pack("<IH", rid, 0)))
                    self.handle(data[:size])

    def destroy(self):
        try:
            self.w(ev(UHID_DESTROY))
        except OSError:
            pass
        os.close(self.fd)

def svc_lines():
    return [l for l in open(SVCLOG).read().splitlines() if l.strip()]

np_dev = fake = p = None
try:
    if not os.path.exists("/dev/uhid"):
        out("FAIL /dev/uhid missing: run `sudo modprobe uhid` and retry")
        raise SystemExit
    np_dev = usb_dev(0x0014)
    if not np_dev:
        out("FAIL could not locate the real numpad")
        raise SystemExit
    d, _ = find(0x0018, CON)
    udev("remove", d)
    time.sleep(1)
    d, _ = find(0x0018, CON)
    rc, txt = udev("add", d, obj)
    if rc != 0 or "Failed" in txt:
        out("FAIL filter did not load")
        raise SystemExit
    time.sleep(1)

    open(np_dev + "/authorized", "w").write("0")
    time.sleep(1)
    fake = Fake()
    node = None
    for _ in range(100):
        fake.pump(0.05)
        node = find(0x0014, VIA)[1]
        if node:
            break
    out(f"fake numpad node: {node}")
    if not node:
        out("FAIL fake numpad did not appear")
        raise SystemExit

    fake.mode = "silent"
    p = subprocess.Popen([svc], stderr=open(SVCLOG, "w"))
    fake.pump(3)
    out(f"RESULT start with a silent numpad: log={svc_lines()} alive={p.poll() is None}")

    out("PHASE A (silent numpad) press Fn+Space TWICE, about 2 s apart (9 s)")
    fake.pump(9)
    out(f"RESULT A: log lines={len(svc_lines())} (want 1) {svc_lines()} alive={p.poll() is None}")

    fake.mode = "wrong"
    out("PHASE B (numpad replies with the wrong echo) press Fn+Space ONCE (6 s)")
    fake.pump(6)
    out(f"RESULT B: log lines={len(svc_lines())} (want 2) {svc_lines()[1:]} alive={p.poll() is None}")

    fake.mode = "good"
    n0 = len(svc_lines())
    out("PHASE C (numpad replies correctly) press Fn+Space ONCE (6 s)")
    fake.pump(6)
    k = kb_level()
    out(f"RESULT C: keyboard level={k}, level the numpad was set to={fake.last_set}, "
        f"match={k == fake.last_set}, new log lines={len(svc_lines()) - n0} (want 0), "
        f"alive={p.poll() is None}")

    fake.mode = "silent"
    n0 = len(svc_lines())
    out("PHASE D (silent again after a success) press Fn+Space ONCE (6 s)")
    fake.pump(6)
    out(f"RESULT D: new log lines={len(svc_lines()) - n0} (want 1: logged again after recovery) "
        f"{svc_lines()[n0:]} alive={p.poll() is None}")
    out(f"requests seen by the fake (mode, first bytes): {fake.requests}")
    out(f"full service log: {svc_lines()}")
finally:
    if p and p.poll() is None:
        p.terminate()
        p.wait()
    if fake:
        fake.destroy()
    if np_dev:
        try:
            open(np_dev + "/authorized", "w").write("1")
        except OSError:
            pass
    d, _ = find(0x0018, CON)
    if d:
        udev("remove", d)
    out("DONE")
