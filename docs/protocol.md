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

## Event report (filter output)

The BPF filter replaces console output with this 32-byte report (the console input report is 32 bytes with no report id, so the size is fixed).

| Byte | Value | Meaning |
|---|---|---|
| 0-3 | `FB 96 B1 E1` | Magic, all four bytes >= 0x80. |
| 4 | `01` | Format version. |
| 5 | `01` | Event type: backlight step. |
| 6 | `00`-`03` | Step N. |
| 7-31 | `00` | Reserved. |

Filter: keeps matcher state across reports, rewrites the report in which `backlight step: N` completes into the event report, and drops every other report. One Fn+Space press gives one event report. Dropping works by returning a negative errno from the `hid_device_event` program: verified on 7.2.15 on 2026-11-13 with a program that returned `-EINVAL` for every report (0 reports in 15 s of typing, against 6,005 in 10 s and 6,256 in 10 s with it detached before and after).

Service: accepts a report only if all four magic bytes and the version match. A report whose byte 0 is below 0x80 is raw console text, meaning the filter is not loaded; the service refuses to run (fail closed, W6). The step is a signal to re-read the keyboard level over VIA, not the brightness value itself.

Why the magic is high bytes: over 27,219 keyboard console reports (871,008 bytes, 60 s of typing and Fn+Space, 2026-11-13) no byte was >= 0x80. Only NUL and LF occurred as control bytes; the highest byte was 0x79. Raw console text is plain ASCII, so it cannot carry the magic. A second run with typing on both modules gave the same result: keyboard 8,963 reports (286,816 bytes) and numpad console (`32AC:0014`) 6,940 reports (222,080 bytes), no byte >= 0x80, only NUL and LF as control bytes, highest byte 0x79. The first run's 0 numpad reports were because nothing was typed on the numpad.

## Filter implementation notes

- The match state is read and written through memory on every byte. Keeping it in a register made the verifier track exact values and fork a path per value per position, hitting its 1,000,000-instruction limit (`E2BIG`, seen twice before this form loaded).
- After the digit of a match, the rest of that report is dropped without being matched. A `backlight step:` line starting in that tail would be missed; this does not happen at the rate presses occur.

## Vendored headers

`bpf/include/hid_bpf.h`, `hid_bpf_helpers.h` and `hid_report_descriptor_helpers.h` are copied unchanged from udev-hid-bpf at commit bbaad63 (GPL-2.0-only, Copyright (c) 2022 Benjamin Tissoires). `vmlinux.h` is generated at build time from `/sys/kernel/btf/vmlinux`.
