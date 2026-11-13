# Protocol notes

Everything here was observed on a Framework Laptop 16 with an ISO keyboard module (`32AC:0018`) and a numpad module (`32AC:0014`), 2026-11-12. Both are RP2040 boards running Framework's QMK fork with VIA.

## Interfaces

Each module exposes four USB HID interfaces. hidraw numbers change per boot; match on product id and interface number.

| Interface | Descriptor starts | Role |
|---|---|---|
| 0 | `05 01 09` | key reports |
| 1 | `06 60 ff` | VIA raw HID (usage page 0xFF60) |
| 2 | `05 01 09` | more key reports |
| 3 | `06 31 ff` | QMK debug console (usage page 0xFF31) |

HID modalias of every interface: `hid:b0003g0001v000032ACp0000<PID>`.

The console descriptor is one input report of 32 bytes and one output report of 32 bytes, no report id.

## VIA (interface 1)

Write 33 bytes: a leading `00` report id, then the 32-byte payload, zero padded. The reply is a 32-byte report with no report id.

| Action | Payload | Reply |
|---|---|---|
| Read brightness | `08 01 01` | `08 01 01 <level>` |
| Set brightness | `07 01 01 <level>` | `07 01 01 <level>` |

Channel 1 is the QMK white backlight, used by both the keyboard and the numpad here. Levels are 0, 85, 170, 255. A level set this way holds on the numpad and is not saved to EEPROM.

## Backlight key

The backlight key (Fn+Space) sends nothing on the key interfaces or VIA, and the kernel exposes no LED or backlight device for it. The only signal is the console line

    backlight step: N

with N cycling 0, 1, 2, 3, exactly one line per press. The console also prints every key position as text (`Col 4 - Keypress at KSO4, KSI1 - Row 1 - State: 1, Voltage: ...`), which is why the console must not be readable by userspace.

Framework's QMK fork has a branch that builds with no debug output (`fl16-nodebug`), so the console line is a firmware build option, not a contract.

## Report boundaries

Measured on 2026-11-13 over 20,295 console reports and 40 Fn+Space presses. Every report is 32 bytes. The step number cycled 0,1,2,3 with no break.

- The line `backlight step: N` straddles two reports about as often as not: 17 of 40 presses were split (for example `...backlight ste` then `p: 0.Col 4 ...`), 23 were whole in one report. The split falls at any offset. A matcher must carry its state across reports.
- Text is packed contiguously across reports. Lines end with a newline-like non-printable byte, then the next line follows in the same report.
- NUL bytes appear in 487 of 20,295 reports (2.4%). 144 have only trailing padding; in 343 a NUL is not only trailing (leading or interior, not broken down further). The matcher skips NULs.
- One gap in the program's report counter (955 reports) fell in a stretch with no presses; the trace buffer drops lines under load, which does not affect the program itself.

## Console reports only flow while the node is open

With the BPF program attached but nothing holding the console hidraw node open, no `backlight step` line was seen. With `cat` holding the node open, every press was matched, one per press (5 of 5, steps 0, 1, 2, 3, 0). Most likely the USB HID driver only polls the interrupt endpoint while the device is open. The service must keep the console node open, which it does anyway by reading it.

## Vendored headers

`bpf/include/hid_bpf.h`, `hid_bpf_helpers.h` and `hid_report_descriptor_helpers.h` are copied unchanged from udev-hid-bpf at commit bbaad63 (GPL-2.0-only, Copyright (c) 2022 Benjamin Tissoires). `vmlinux.h` is generated at build time from `/sys/kernel/btf/vmlinux`.
