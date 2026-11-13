# fw16-backlight-bpf

Keep the Framework Laptop 16 keyboard and numpad backlights in step without polling.

The modules handle their backlight key in firmware and tell the host nothing. The only trace is a line on the keyboard's QMK debug console, `backlight step: N`. That console also prints every key position, so it must not be readable by a normal process. A HID-BPF program attached to the console interface reads it inside the kernel, keeps only the backlight event, and drops everything else. A small service then blocks on the filtered node and copies the keyboard's level to the numpad over VIA.

Protocol facts and how they were found: [docs/protocol.md](docs/protocol.md).

## Status

Steps 1 and 2 of 4 done and verified on hardware. Step 3 verified on hardware for start sync, press sync and VIA failure handling; physical re-seat and suspend/resume are checked in step 4. Step 4 not started.

| Step | What | State |
|---|---|---|
| 1 | Match `backlight step: N` across 32-byte reports and log it with `bpf_printk` | works on the module: one match per Fn+Space (33 of 33); needs the console node held open |
| 2 | Drop every other console report and rewrite the match to a short event report | works on the module: 8 presses gave 8 event reports and nothing else |
| 3 | Service: blocking read of the filtered node, read keyboard level, set numpad over VIA, one sync at start | start sync, press sync, 0 idle CPU, re-enumeration and VIA failure handling verified on hardware |
| 4 | udev rule, systemd unit, install script, fail-closed check that the filter is loaded | not started |

## Requirements

- Kernel with `CONFIG_HID_BPF=y` and BTF (`/sys/kernel/btf/vmlinux`)
- `clang`, `bpftool` (Arch package `bpf`), `make`
- [`udev-hid-bpf`](https://libevdev.pages.freedesktop.org/udev-hid-bpf/) (Arch package `udev-hid-bpf`)

## Try step 1

    make
    sudo udev-hid-bpf --verbose add /sys/bus/hid/devices/<keyboard console device> $PWD/build/fw16-backlight.bpf.o
    sudo sh -c 'cat /dev/$(ls /sys/bus/hid/devices/<keyboard console device>/hidraw) > /dev/null'
    sudo cat /sys/kernel/tracing/trace_pipe

The console device is the keyboard's HID device whose report descriptor starts `06 31 ff`. Run the last two commands in separate terminals: the console node must be held open or no reports arrive. Press Fn+Space and look for `fw16-backlight: step N`.

`make install` installs the object and a udev rule so it loads when the module appears; `make uninstall` removes both.

## Layout

    bpf/fw16-backlight.bpf.c      the HID-BPF program
    bpf/include/                  headers vendored from udev-hid-bpf
    src/fw16-backlight-sync.c     the sync service
    docs/protocol.md              interfaces, VIA bytes, console line
    Makefile                      build and install

## Known limits

- The console line is a firmware debug print. A firmware build without debug output removes it.
- `/sys/fs/bpf` is root-only, so an unprivileged service cannot check that the filter is attached; step 4 has to solve that.
- Only the keyboard modules (`32AC:0012`, `0018`, `0019`) are matched. The numpad is a sync target, not a source.

## License

GPL-2.0-only, as required for HID-BPF programs.
