# fw16-backlight-bpf

Keeps the keyboard and numpad backlights of a Framework Laptop 16 in step on
Linux. Press Fn+Space on the keyboard module and the numpad module follows,
without anything polling the hardware.

The two modules handle their backlight key in firmware and tell the host
nothing: no key event, no LED device, no VIA message. The only trace is a debug
line on the keyboard's QMK console, `backlight step: N`. That console also
prints the position of every key you press, so it must not be readable by an
ordinary process.

A small HID-BPF program attached to the console interface reads the line inside
the kernel, keeps only the backlight event, and drops everything else. A
sandboxed service then blocks on the filtered node, and on each event copies the
keyboard's level to the numpad over VIA.

```
Fn+Space ──> keyboard firmware prints "backlight step: N" on its debug console
               │
               ▼
        HID-BPF filter (in the kernel): keeps the event, drops every other
        console report, so key positions never reach a userspace process
               │
               ▼
        fw16-backlight-sync (unprivileged, sandboxed): blocks in read();
        on an event, reads the keyboard's level and sets the numpad to it
```

This is the unusual way to do it, with real costs: a kernel-side program, a
root-owned udev helper, and a dependency on a firmware debug print. Read
[Known risks](#known-risks) before installing.

Protocol facts and how they were found are in
[docs/protocol.md](docs/protocol.md).

## Contents

- [Prior work](#prior-work)
- [Hardware support](#hardware-support)
- [Linux support](#linux-support)
- [Requirements](#requirements)
- [Install](#install)
- [Using it](#using-it)
  - [Troubleshooting](#troubleshooting)
- [Update](#update)
- [Uninstall](#uninstall)
- [How it works](#how-it-works)
- [Known risks](#known-risks)
- [Known limits](#known-limits)
- [Local development](#local-development)
  - [Layout](#layout)
  - [Tests](#tests)
  - [Releasing](#releasing)
- [Licence](#licence)

## Prior work

This project was inspired by
[framework-keyboard-toolkit](https://github.com/alejandroqh/framework-keyboard-toolkit),
which keeps the Framework Laptop 16 modules' backlights in step by polling them
over VIA. This project uses the same VIA interface to set the numpad, and
learns of a change from the keyboard's debug console instead of polling.

## Hardware support

Tested on one machine: a Framework Laptop 16 with the ISO keyboard module and
the numpad module. Both modules are RP2040 boards running Framework's QMK fork
with VIA.

| Module | USB id | State |
| --- | --- | --- |
| Keyboard, ISO | `32AC:0018` | tested; handled by the filter, the service and the udev rule |
| Numpad | `32AC:0014` | tested; the module that is synced |
| Keyboard, ANSI | `32AC:0012` | the filter matches it; the service and udev rule do not; untested |
| Keyboard, JIS | `32AC:0019` | the filter matches it; the service and udev rule do not; untested |
| RGB macropad | not known | not supported |
| Other Framework models | not applicable | not supported |

What the hardware has to provide:

- **A keyboard module whose firmware prints `backlight step: N` on its QMK debug
  console.** That line is a firmware debug print, not a documented interface.
  A firmware build without debug output removes it and this project stops
  working. Framework's QMK fork has a branch built that way. The firmware
  version of the tested modules was not recorded.
- **Four backlight levels**: 0, 85, 170 and 255, set on VIA channel 1 (the white
  backlight). A level set this way is not saved to the module's EEPROM.

Fn+Space is the only key handled. The numpad's own backlight key is not
mirrored to the keyboard.

## Linux support

Tested on Arch Linux, kernels 7.2.15 and 7.3.4, with udev-hid-bpf 2.3.0.

| Needs | Notes |
| --- | --- |
| A kernel with `CONFIG_HID_BPF=y` and BTF (`/sys/kernel/btf/vmlinux`) | the program uses the kernel's struct_ops HID-BPF interface, so it is tied to kernels that have it; nothing older than 7.2 was tried |
| [`udev-hid-bpf`](https://libevdev.pages.freedesktop.org/udev-hid-bpf/) | loads the filter whenever the keyboard module appears |
| systemd | the service is a system unit with `DynamicUser=` and a sysusers group |
| udev | for the access rule and the helper that opens the console |
| `sudo` | `make install` and `make uninstall` use it |

Arch is the only distribution tried. On another one, `make` will still name
what is missing, but its messages give Arch package names, and `udev-hid-bpf`
may not be packaged. A system without systemd is not supported. There is no
desktop-environment integration, so it works the same under X11, Wayland, a
console or a headless session.

## Requirements

- A Framework Laptop 16 with the modules listed above, on a kernel and
  distribution as described above
- To build: `gcc`, `clang`, `bpftool` (Arch package `bpf`) and `make`
- To install: `sudo`, systemd and `udev-hid-bpf`

## Install

Installing changes the system: it loads a program into the kernel, adds a udev
rule and a systemd unit under `/etc`, creates a group, and puts two files under
`/usr/local/lib`. Read [Known risks](#known-risks) first. Everything is removed
again by `make uninstall`.

    git clone https://github.com/lenny1882/fw16-backlight-bpf
    cd fw16-backlight-bpf

Or, without cloning, from the newest release:

    curl -fsSL https://github.com/lenny1882/fw16-backlight-bpf/releases/latest/download/fw16-backlight-bpf.tar.gz | tar -xz
    cd fw16-backlight-bpf

Then build and install:

    make
    make install     # asks for sudo
    make reload      # applies it to modules that are already attached

A reboot does what `make reload` does. `make` names any missing tool and its
Arch package instead of failing with a compiler error. `make install` is safe to
run again.

What `make install` does:

- installs the filter through `udev-hid-bpf`, so it loads whenever the keyboard
  module appears
- installs the service and a console-access helper under
  `/usr/local/lib/fw16-backlight`
- installs the udev rule `70-fw16-backlight.rules`, the systemd unit
  `fw16-backlight-sync.service` and a sysusers file that creates the group
  `fw16-backlight`
- starts the service and enables it at boot

There is nothing else to do: press Fn+Space and the numpad follows the keyboard.

## Using it

The service logs nothing while all is well. To look at it:

    systemctl status fw16-backlight-sync
    journalctl -u fw16-backlight-sync

On start it sets the numpad to the keyboard's level, and again on every Fn+Space.
There is no configuration.

### Troubleshooting

A line in the log means something was wrong. Each problem is logged once, not on
every press.

- `numpad VIA node not found`: the numpad module is not attached. The service
  recovers by itself when it returns, but the numpad is only synced again on the
  next Fn+Space press.
- `console is not filtered (raw text); refusing to run`: the filter is not
  loaded, so the service stopped on purpose and stays stopped. Run `make reload`,
  then `sudo systemctl restart fw16-backlight-sync`.
- Nothing happens on Fn+Space and the log is empty: the firmware may not print
  the debug line. That is a hardware or firmware limit, not something to fix
  here. Compare [Hardware support](#hardware-support).

## Update

    git pull
    make
    make install

Re-running the install over an existing one is how you upgrade it. A reboot or
`make reload` makes a new filter apply to modules that are already attached.

## Uninstall

    make uninstall

This removes the filter, the service, the rule, the unit and the group, and
resets the console and VIA nodes to root-only first. It is safe to run twice.

## How it works

Four pieces, each small.

1. **The filter** (`bpf/fw16-backlight.bpf.c`) is a HID-BPF program loaded by
   `udev-hid-bpf`. It attaches to the keyboard's console interface only (the
   interface whose report descriptor starts `06 31 ff`). It matches
   `backlight step: N` across the console's 32-byte reports, since the line
   splits across two reports about as often as not, rewrites the report that
   completes it into a fixed event report, and drops every other report.
2. **The service** (`src/fw16-backlight-sync.c`) blocks in `read()` on the
   filtered node. It finds the keyboard and numpad by product id and interface,
   never by hidraw number, because those change per boot and per re-enumeration.
   An event is only a signal; the service reads the keyboard's level over VIA
   and sets the numpad to it.
3. **The udev rule and helper** (`dist/`) give the service's group access to the
   two VIA nodes, and open the keyboard's console node to that group only while
   the filter is confirmed loaded on it. If it is not, the helper sets the node
   back to root-only.
4. **The unit** runs the service as a dynamic user with no capabilities, no
   network and a tight sandbox (`systemd-analyze security` scores it 0.6, SAFE).

The service also checks the data itself. A report that does not start with the
filter's four-byte magic is raw console text, which means the filter is not
loaded, and the service exits and stays stopped. The packet formats and the
measurements behind each choice are in [docs/protocol.md](docs/protocol.md).

## Known risks

Read these before installing. The first four are properties of the design.

**The console shows what you type.** The keyboard's debug console prints the
matrix position of every key, which maps to characters on a known layout. Anything
that can read that node can log your typing. The design keeps that out of
userspace: the filter drops those reports in the kernel, and the node is
root-only except while the filter is confirmed loaded. Gaps remain:

- If the filter is not loaded, the service reads one raw report into memory
  before it notices and exits. It is never logged.
- `/sys/fs/bpf` is root-only, so the unprivileged service cannot check for the
  filter itself. The root helper checks, and the service's raw-text check is the
  backstop.
- If the filter is removed without a udev event on the console node, the
  group's access stays until the next event.
- Root can always read the console, and the filter does not change that.

**The service can talk to both modules, not just set brightness.** The udev rule
gives the service's group read and write access to the VIA interface of the
keyboard and the numpad. VIA can do more than set a backlight level: it can, for
example, remap keys. The service only ever sends the two VIA commands that read
and set brightness, but the access is not limited to them. Do not add users to
the `fw16-backlight` group, and treat a compromise of the service as a compromise
of the module's configuration. The unit's sandbox is there to make that
unlikely.

**It runs code in the kernel.** The filter is a BPF program, checked by the
kernel's verifier and loaded by `udev-hid-bpf`, and it only attaches to the
console interface, not the key interfaces. It is still code running in the
kernel on every console report, and its own source is GPL-2.0-only for that
reason.

**It depends on undocumented behaviour, and either part can change.**

- The console line is a firmware debug print. A different or debug-free firmware
  removes it.
- The HID-BPF interface in the kernel and in `udev-hid-bpf` can change between
  versions. The vendored headers are from `udev-hid-bpf` commit `bbaad63`. A
  newer kernel may need the program rebuilt or changed.

**An unexplained disconnect happened once in testing.** During one run on kernel
7.3.4 both modules dropped off USB together and re-enumerated (the numpad logged
`Device not responding to setup address`, error -71). It did not recur in later
runs, and nothing from this project appeared in the kernel log beforehand. The
cause is unknown, so it cannot be ruled out that this project played a part.

**Some situations are untested.**

- suspend and resume
- physically removing and re-seating a module (re-enumeration forced in software
  by toggling USB `authorized` works)
- the ANSI and JIS keyboard modules
- any distribution other than Arch, and any kernel other than 7.2.15 and 7.3.4

**There is no warranty.** This is not from Framework and not endorsed by them. It
comes from observing the modules, not from a specification.

## Known limits

- One direction only: keyboard to numpad. The numpad's own backlight key is not
  mirrored.
- A numpad that returns after a re-seat is not re-synced until the next Fn+Space
  press, so it can sit at an old level. Fixing that needs the service to watch for
  the module returning, and the unit blocks netlink
  (`RestrictAddressFamilies=none`), so it cannot.
- Only the ISO keyboard (`32AC:0018`) is handled by the service and the udev
  rule.
- No desktop brightness integration (no UPower or sysfs backlight device).
- Four levels, set on VIA channel 1; other lighting on the modules is untouched.
- Console reports only flow while the console node is held open. The service
  holds it open by reading it, so do not rely on anything else reading it.

## Local development

### Layout

    LICENSE, LICENSES/            which licence covers which files, and the texts
    bpf/fw16-backlight.bpf.c      the HID-BPF program
    bpf/include/                  headers vendored from udev-hid-bpf
    src/fw16-backlight-sync.c     the sync service
    dist/                         udev rule, console-access helper, sysusers file, systemd unit
    docs/protocol.md              interfaces, VIA bytes, console line, event report
    docs/requirements.md          the working checklist and the test results
    docs/releasing.md             how a release is cut
    .github/workflows/            the release workflow
    Makefile                      build, install, reload, uninstall

`make` builds everything into `build/`, including the generated unit and rule.
`vmlinux.h` is generated from `/sys/kernel/btf/vmlinux` at build time, so a
build is tied to the running kernel.

### Tests

There is no automated test suite. The checks are hardware scripts in
[`test/hw/`](test/hw/), run by hand as root with the real modules attached. The
docstring at the top of each gives its command and what it needs. Several ask you
to type or press Fn+Space while they run, and each writes a log beside itself,
which git ignores.

| Script | What it checks |
| --- | --- |
| `w4test.py` | the filter: attached, only event reports appear; detached, the raw console is back |
| `w5test.py` | the service: start sync, press sync and its latency, idle CPU |
| `w5via.py` | VIA failure handling, using a virtual numpad (needs `uhid`) |
| `w6check.py` | an installed system: node permissions, service identity, `systemd-analyze`, fail closed |
| `w6uninstall.py` | uninstall leaves nothing, and install is idempotent |
| `w6hotplug.py` | re-enumeration of each module, and suspend/resume |
| `w6boot.py` | a reboot with changed hidraw numbers (run `before`, reboot, run `after`) |

The numbers they produced are in [docs/requirements.md](docs/requirements.md).

### Releasing

See [docs/releasing.md](docs/releasing.md). A tag `vX.Y.Z` pushed from its
`release/vX.x` branch publishes a source tarball as a GitHub Release.

## Licence

Two licences, split by directory. Details are in [`LICENSE`](LICENSE) and the
texts are in [`LICENSES/`](LICENSES/).

- `bpf/` (the HID-BPF program and the vendored headers): **GPL-2.0-only**. The
  headers come from `udev-hid-bpf` under that licence, and the kernel requires a
  GPL-compatible licence for HID-BPF programs.
- Everything else (the service, helper script, unit, udev rule, Makefile, docs):
  **MIT with the Commons Clause**. You may use, copy, change and share it, but not
  sell it or sell a service whose value comes mainly from it. That is not an
  open-source licence in the usual sense, and it does not cover `bpf/`, which
  anyone may sell under the GPL's terms.
