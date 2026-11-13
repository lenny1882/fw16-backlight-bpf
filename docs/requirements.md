# Requirements and TODO

The working list. Tick items as they are verified on hardware, not when written.

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
- [ ] `sudo pacman -S udev-hid-bpf bpf` done; `make` produces `build/fw16-backlight.bpf.o` with no errors.
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
- [ ] Recorded in `docs/protocol.md`: whether `backlight step: N` ever straddles two reports, and how NUL padding appears.
- [ ] If it can straddle, a test press sequence that does so is detected correctly; if not, the matcher's cross-report state is still kept and the finding is noted.
- [ ] Temporary logging removed.

### W4 Filter and event report (step 2)
Covers: F3, S1.
Acceptance:
- [ ] Event report format is written down in `docs/protocol.md`.
- [ ] With the filter attached, `cat` on the console hidraw node while typing for 30 s shows no key positions, no matrix dump, nothing but event reports.
- [ ] One Fn+Space press yields exactly one event report with the correct step.
- [ ] With the filter detached, the raw console is visible again (proves the filter is what hides it).

### W5 Service (step 3)
Covers: F4, F5, F6, F7.
Acceptance:
- [ ] At start the numpad level equals the keyboard level, from both an unequal starting state and an already equal one.
- [ ] Fn+Space four times: after each press the numpad matches the keyboard within 1 s, and CPU use between presses is zero (blocked in `read()`, no timer).
- [ ] Nodes are found by product id and interface; reboot with different hidraw numbers works unchanged.
- [ ] Unplugging and re-seating the modules, or suspend/resume, leaves the service running and syncing.
- [ ] A VIA read or write failure logs once and the service continues.

### W6 Confinement and install (step 4)
Covers: S1 to S4, B2, B3, B4.
Acceptance:
- [ ] udev rule gives the group access to the filtered console node and the two VIA nodes only; no other `32AC` node.
- [ ] Systemd unit runs as `DynamicUser`; `systemd-analyze security` reports no exposure for network or filesystem writes beyond what is needed.
- [ ] Fail-closed check implemented and shown working: unload the filter, the service refuses to read and logs the reason. The approach is recorded (the root-only `/sys/fs/bpf` rules out a direct check by an unprivileged service).
- [ ] The udev `MODE` / logind ACL issue is handled; a fresh boot and a live re-seat both give working access.
- [ ] `make install` then reboot: the program loads, the service starts, sync works, with no manual step.
- [ ] `make uninstall` leaves no udev rule, object, unit or loaded program.

### W7 Repo housekeeping
Acceptance:
- [ ] `LICENSE` file with GPL-2.0-only text.
- [ ] README status table and requirements updated (D1).

## 7. Open questions (each blocks a work item)

| Question | Blocks |
|---|---|
| Does `backlight step` ever straddle a report boundary, and how is padding laid out? | W3, W4 |
| What is the event report's format, and can the program rewrite and pass one while dropping the rest? | W4 |
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
