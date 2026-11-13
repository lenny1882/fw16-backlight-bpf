# Requirements and TODO

The working list. Tick items as they are verified on hardware, not when written.

## Progress (as of 2026-11-13)

| Item | State |
|---|---|
| W1 Build prerequisites | Packages installed and `make` builds. Dependency checks (B1) written; checked by naming a missing tool, not on a machine that lacks one. |
| W2 Step 1 on hardware | Done. |
| W3 Report boundaries | Done. The line straddles two reports in 17 of 40 presses; the matcher handles it. |
| W4 Filter and event report | Done. Verified on hardware (8 presses, 8 event reports, nothing else). |
| W5 Service | Done. Start sync, press sync, idle CPU, simulated re-enumeration and VIA failure handling verified on hardware (kernel 7.2.15 and again on 7.3.4). |
| W6 Confinement and install | Done, except suspend/resume (optional, not tested; a physical module pull was deliberately skipped). Verified on hardware: permissions, service identity, sandbox score, fail closed, uninstall and repeat install, reboot with changed hidraw numbers, software re-enumeration of both modules. |
| W7 Repo housekeeping | Done. |

Next, after the reboot onto 7.3.4 (verification so far was on 7.2.15):
1. `make clean && make` (a plain `make` may keep the old `vmlinux.h`).
2. Re-run `test/hw/w4test.py` and `test/hw/w5test.py` as a regression on 7.3.4.
3. Run `test/hw/w5via.py` (needs `sudo modprobe uhid`) to finish W5; then W6.
The throwaway hardware test scripts are in `test/hw/` in the working tree and are deliberately not committed; each needs root and its docstring gives the command. If that directory is gone, they have to be rewritten.

Next, W6 (the install is in place; the scripts are untracked in `test/hw/`, each needs root):
1. Done: reboot check (`w6boot.py before` and `after`).
2. Done: software re-enumeration of both modules (`w6hotplug.py`). Physical re-seat skipped on purpose; suspend/resume optional (`w6hotplug.py suspend`).
3. Done: numpad re-sync documented as a limit. Next: W7.

Facts learned that affect later work:
- Regression on kernel 7.3.4 (2026-11-13), after the 7.2.15 verification: the W4 test (8 presses, 8 valid event reports, none other; detached shows raw) and the W5 test (unequal and equal start, 4 presses within 0.16 s, 0 idle CPU) both passed again. The hidraw numbers had swapped by then (keyboard hidraw1 to 4, numpad hidraw5 to 8, the reverse of earlier runs) and the service synced the right way round.
- At 13:13:05 on 2026-11-13, during the first W4 run on 7.3.4, both modules disconnected together and re-enumerated (the numpad logged `Device not responding to setup address`, error -71 first). The test's read failed with EIO. Not reproduced in the next two runs; cause unknown, nothing from this project in the kernel log beforehand.
- Console reports only arrive while the console hidraw node is held open.
- The module can re-enumerate (console went from `0003:32AC:0018.0009` / `hidraw8` to `.000F` / `hidraw4`). An attachment does not survive that, and the service must not rely on ids or hidraw numbers.
- A numpad that is deauthorized and restored keeps its backlight level, and the service does not notice it coming back, so it stays out of sync until the next press. A physical re-seat probably resets it; not tested. Fixing this needs the service to watch for the node returning (netlink or udev), which is entangled with W6 permissions.
- On this machine tracing is at `/sys/kernel/tracing/trace_pipe`, not under `debug`.
- `udev-hid-bpf add` needs an absolute path to the object file when not run from the project directory.
- The vendored `hid_bpf_helpers.h` also needs `hid_report_descriptor_helpers.h`.
- The probe was checked on the key interface `.0005` only. The VIA interface, the other key interface and the numpad were not.
- Nothing is attached or installed at the moment; the program was loaded by hand and does not survive a reboot or re-enumeration.

## 1. Goal

Keep the Framework Laptop 16 keyboard and numpad backlights in step on Linux (Arch).

## 2. Scope

In scope:
- Sync the numpad to the keyboard once at service start.
- Re-sync when the keyboard backlight changes (Fn+Space), triggered by an event.
- Keystroke positions from the keyboard's debug console never reach a userspace process.

Out of scope:
- NumLock handling, ambient light sensing, anything else in `framework-keyboard-toolkit`.
- A `uleds` / UPower / sysfs backlight device.
- Syncing numpad to keyboard in the other direction.
- Firmware changes, kernel modules, filing upstream requests.

## 3. Constraints

- No polling. The re-sync must be driven by the `backlight step: N` console line.
- Languages: BPF C for the program, bash for the service. Ask before adding any other language or runtime.
- Code comments are rare: one short line, only for a non-obvious why.
- Licence: GPL-2.0-only (required for HID-BPF programs).

## 4. Dependencies

| Package | Needed for | Where |
|---|---|---|
| `clang` | compiling the BPF object | build |
| `bpf` (bpftool) | `vmlinux.h` from BTF, `gen object` | build |
| `udev-hid-bpf` | loading and pinning the program on device add; `make install` | runtime and install |

Kernel: `CONFIG_HID_BPF=y` and `/sys/kernel/btf/vmlinux`.

## 5. Requirements

Each has an ID, referenced by the work items below.

### Functional
- **F1** The BPF program attaches only to keyboard modules `32AC:0012`, `0018`, `0019`, and only to the interface whose report descriptor starts `06 31 ff`.
- **F2** The program recognises `backlight step: N` (N = 0..3), including when the line straddles two 32-byte reports.
- **F3** The program drops every console report. The only data that reaches the hidraw node is a short event report that carries the step.
- **F4** At start, the service reads the keyboard level over VIA (`08 01 01`) and sets the numpad (`07 01 01 <level>`).
- **F5** On each event, the service re-reads the keyboard level over VIA and sets the numpad. It does not derive the level from the step number.
- **F6** The service finds nodes by product id and interface number, never by hidraw number.
- **F7** The service survives module hot-plug: if a node disappears and returns, it resumes without a restart.

### Security
- **S1** No process other than root's loader can read raw console text. The node a service can open carries only filtered events.
- **S2** Fail closed. If the filter is not attached, the service must not read from the console node and must report why.
- **S3** The service runs unprivileged and sandboxed: system unit, `DynamicUser`, `DeviceAllow=char-hidraw rw`, no network, no writes outside what it needs.
- **S4** Group access covers only the filtered console node and the VIA nodes of the keyboard and numpad.

### Build and install
- **B1** `make` fails early with a clear message naming the missing tool and its Arch package when `clang` or `bpftool` is missing, or `/sys/kernel/btf/vmlinux` does not exist. `make install` does the same for `udev-hid-bpf`.
- **B2** `make install` installs everything needed to load the program at boot, the udev rule, the service unit and its device rule, and is idempotent.
- **B3** `make uninstall` removes everything `make install` added and leaves no loaded program.
- **B4** Installation never writes to EEPROM-backed module settings (the VIA set used is volatile).

### Documentation
- **D1** README status table matches reality.
- **D2** `docs/protocol.md` records anything newly observed (report boundaries, event report format, step-to-level mapping).

## 6. Work items

### W1 Build prerequisites and build check
Install `udev-hid-bpf` and `bpf`; add the dependency checks.
Covers: B1.
Acceptance:
- [x] `sudo pacman -S udev-hid-bpf bpf` done; `make` produces `build/fw16-backlight.bpf.o` with no errors.
- [ ] With `bpftool` hidden from `PATH`, `make` exits non-zero and prints the tool name and `pacman -S bpf`; no raw `command not found`.
- [ ] Same for `clang`, for a missing `/sys/kernel/btf/vmlinux`, and for `udev-hid-bpf` on `make install`.

### W2 Step 1 on hardware
Attach the existing program and confirm detection.
Covers: F1, F2 (partly).
Acceptance:
- [x] The console device is identified by descriptor `06 31 ff` on `32AC:0018.*` (`.0009` on 2026-11-13).
- [x] `udev-hid-bpf add` attaches without error.
- [x] Fn+Space produces exactly one `fw16-backlight: step N` in `trace_pipe` per press, N cycling 0,1,2,3 (33 consecutive presses, no gaps or repeats). Needs the console node held open.
- [x] The probe refuses other interfaces (key interface `.0005` tested: `probe() ... Invalid argument`). The VIA interface `.0007`, key interface `.0008` and the numpad modules were not tested; the probe checks only the descriptor, so the same result is expected.

### W3 Report boundaries
Temporary logging of raw report text.
Covers: F2, D2.
Acceptance:
- [x] Recorded in `docs/protocol.md`: the line straddles two reports in 17 of 40 presses, and NUL padding is occasional (2.4% of reports).
- [x] A test sequence that straddles was detected correctly: all 17 straddled lines produced the right STEP, with each report's start state equal to the previous report's end state.
- [x] Temporary logging removed.

### W4 Filter and event report (step 2)
Covers: F3, S1.
Acceptance:
- [x] Event report format is written down in `docs/protocol.md` (4-byte high-bit magic, checked against 27,219 raw reports).
- [x] With the filter attached, reading the console node while typing for 30 s gave 8 reports, all valid event reports (2026-11-13). Read with a script that validates every report, not with `cat`.
- [x] One Fn+Space press yields exactly one event report: 8 presses gave 8 reports, steps 2,3,0,1,2,3,0,1 in order. The step values were checked for cycling, not against an independent reading of the keyboard level.
- [x] With the filter detached, the raw console is visible again: 2,951 raw reports in 5 s, none with the magic.

### W5 Service (step 3)
Covers: F4, F5, F6, F7.
Acceptance:
- [x] At start the numpad level equals the keyboard level, from both an unequal starting state and an already equal one (numpad forced to 0 against keyboard 85, then equal; both ended at 85, 2026-11-13).
- [x] Fn+Space four times: after each press the numpad matched the keyboard within one 50 ms poll in 3 cases and 0.16 s in 1; idle CPU was 0 ticks over 5 s (blocked in `read()`, no timer).
- [x] Nodes are found by product id and descriptor, never by hidraw number: `find_node()` in `src/fw16-backlight-sync.c` takes only a product id and a descriptor prefix, and it found the right nodes on every run. (The change-of-number case is checked in W6, after a reboot.)
- [x] Simulated re-enumeration of each module (USB `authorized` 0 then 1) leaves the service running; the next press syncs. One `console read failed` was logged for the keyboard.
- [x] A VIA failure logs once and the service continues (2026-11-13, kernel 7.3.4, virtual numpad made with `uhid`; the real numpad was deauthorized for the test). A silent numpad gave one log line across the start sync and two presses; a correct reply then set the right level with no new line; going silent again logged again, once. A wrong echo was reported as a timeout, with the same text, so it was not logged twice; the separate `did not match` message needs four wrong replies in a row. The other error paths were exercised without hardware by calling `via_xfer()` on `/dev/full` (write fails: one message across two calls, returns -1), `/dev/null` (write succeeds, read returns nothing: `did not match`) and a missing path (`cannot open`). That harness is throwaway and not in the repo.

### W6 Confinement and install (step 4)
Covers: S1 to S4, B2, B3, B4.
Acceptance:
- [x] The service cannot open the console node before the filter is attached. By construction: the node stays root-only, and `grant-console` opens it to the group only after `udev-hid-bpf list-loaded` shows the filter on its HID device, and revokes it otherwise (checked by removing the filter and re-triggering: `root:root 0600`, and the restarted service logged `cannot open ... Permission denied`, 2026-11-13). If udev ever ran the hidraw event before the filter attach finished, the cost would be availability (no grant), not exposure; whether the ordering holds is checked by the reboot and re-seat items below. Limit: removing the filter without a udev event on the node leaves the group access in place until the next event; the service's own check (next item) is the backstop.
- [x] udev rule gives the group access to the filtered console node and the two VIA nodes only; no other `32AC` node. Checked on the installed system: of the 10 `32AC` nodes only the keyboard console and the keyboard and numpad VIA nodes were `root:fw16-backlight 0660`; the numpad console and every key interface stayed `root:root 0600`.
- [x] Systemd unit runs as `DynamicUser`; `systemd-analyze security` reports 0.6 SAFE, and `systemd-analyze verify` is clean. The running service had uid 63932, group `fw16-backlight`, `CapEff` 0 and `NoNewPrivs` 1.
- [x] Fail-closed check implemented and shown working, in two layers. (1) The unprivileged service cannot read `/sys/fs/bpf`, so the filter check lives in the root helper `grant-console` (see the access item above). (2) The service refuses raw text: with the filter removed under the running service and one key pressed, it logged `console is not filtered (raw text); refusing to run` and exited 2, and `RestartPreventExitStatus=2` keeps it failed. Limit: layer 2 reads one raw report into memory before it notices; it is never logged.
- [x] The udev `MODE` / logind ACL issue is handled; a fresh boot and a live re-seat both give working access. The logind ACL issue does not apply: these nodes carry only the `seat` tag, not `uaccess`. A fresh boot gave working access. A live re-seat was forced in software (USB `authorized` 0 then 1) for both modules, not by pulling one: the udev rule re-attached the filter and re-granted the console and VIA nodes by itself, the service stayed active with 0 restarts, and the next press synced the numpad.
- [x] `make install` then reboot: the program loads, the service starts, sync works, with no manual step (2026-11-13, kernel 7.3.4). After the reboot the service was started by systemd 7.1 s into the boot with 0 restarts, the filter was loaded on the keyboard, permissions were right, and a press synced the numpad. Levels were already equal at boot, but they had also been equal before the reboot, so this run does not show the start sync (W5 did).
- [x] `make uninstall` leaves no udev rule, object, unit or loaded program (2026-11-13: run twice, both exit 0; no installed file, no group, unit not found, no loaded program, and all `32AC` nodes back to `root:root 0600`). The first attempt exposed a bug: nodes granted to the group kept `0660` with a dangling group id after the group was deleted, because udev does not reset ownership on a change event; uninstall now resets them first. `make install` run twice and `make reload` also exit 0, and press sync works afterwards.
- [x] After the install and a reboot, the service finds its nodes when the hidraw numbers differ from the previous boot: 6 of 8 `32AC` nodes changed (the keyboard and numpad interfaces swapped places: keyboard console `hidraw4` to `hidraw8`, VIA `hidraw2` to `hidraw6`, and the reverse for the numpad), and sync still worked.
- [ ] Suspend/resume: the service keeps running and the next press syncs. Not tested. A physical re-seat was deliberately not tested (it does not happen in normal use); the software re-enumeration in the access item above covers the same udev path. Optional: `sudo python3 -I test/hw/w6hotplug.py suspend`.
- [x] A numpad that returns (re-seat) is re-synced without waiting for a press: not feasible, documented as a limit in the README. The unit sets `RestrictAddressFamilies=none`, so the service cannot listen for uevents. In the software re-enumeration the numpad kept its level (85/85), so the effect may not show up in practice; a real power cycle would probably reset it, untested.

### W7 Repo housekeeping
Acceptance:
- [x] Licences in place. Split licensing: `bpf/` (the program and the vendored headers) stays GPL-2.0-only, because the headers are GPL-2.0-only and HID-BPF programs need a GPL-compatible licence; everything else is MIT with the Commons Clause. `LICENSE` summarises the split, `LICENSES/` holds the two texts (the GPL text is Arch's SPDX copy), and each source file has an SPDX line. The `Software:` line in the Commons Clause text has no repository URL, because this repo has no remote yet.
- [x] README status table and requirements updated (D1), and the stale "Try step 1" section replaced by install and use instructions, the layout and the licence.

## 7. Open questions (each blocks a work item)

| Question | Blocks |
|---|---|
| ~~Does `backlight step` ever straddle a report boundary, and how is padding laid out?~~ Answered in W3 (yes, 17 of 40; sparse NULs). | none |
| ~~What is the event report's format, and can the program rewrite and pass one while dropping the rest?~~ Answered in W4 (yes; see `docs/protocol.md`). | none |
| How does an unprivileged service verify the filter is attached? | W6 |
| Is the step-to-level mapping really step x 85? (Moot if F5 holds, but worth recording.) | D2 |
| Does the numpad's console print `backlight step` for its own key? Not needed for the current scope. | none |

Known risk: a future firmware without console debug output removes the trigger. Fallback: AUR `fw16-kbd-uleds-git` with a longer `--poll-ms`.

## 8. Definition of done

The project is done when all of these hold:

1. Every requirement in section 5 is met and its work-item checklist is ticked, each verified on the real hardware, not just compiled.
2. After a clean install and reboot, with no manual step: the numpad matches the keyboard at start, and follows each Fn+Space within 1 s.
3. No polling anywhere: the service is blocked in `read()` between events, and CPU use is zero.
4. A 30-second typing test shows no key position reachable from any unprivileged process.
5. With the filter unloaded, the service fails closed and says so.
6. `make` and `make install` fail with a clear message when any dependency is missing; `make uninstall` leaves nothing behind.
7. README and `docs/protocol.md` match the shipped behaviour, with the open questions in section 7 answered or recorded as known limits.
8. `LICENSE` is present, and the work is committed.
