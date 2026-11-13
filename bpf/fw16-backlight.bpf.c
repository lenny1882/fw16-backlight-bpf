// SPDX-License-Identifier: GPL-2.0-only

#include "vmlinux.h"
#include "hid_bpf.h"
#include "hid_bpf_helpers.h"
#include <bpf/bpf_tracing.h>

#define VID_FRAMEWORK	0x32ac
#define PID_KB_ANSI	0x0012
#define PID_KB_ISO	0x0018
#define PID_KB_JIS	0x0019

#define REPORT_SIZE	32
#define PATTERN_LEN	16

HID_BPF_CONFIG(
	HID_DEVICE(BUS_USB, HID_GROUP_GENERIC, VID_FRAMEWORK, PID_KB_ANSI),
	HID_DEVICE(BUS_USB, HID_GROUP_GENERIC, VID_FRAMEWORK, PID_KB_ISO),
	HID_DEVICE(BUS_USB, HID_GROUP_GENERIC, VID_FRAMEWORK, PID_KB_JIS)
);

/* Event report layout: docs/protocol.md, "Event report". */
#define EVENT_VERSION	0x01
#define EVENT_STEP	0x01

static const char pattern[PATTERN_LEN] = "backlight step: ";
static __u32 matched;

static __always_inline int emit_event(__u8 *data, int step)
{
	int i;

	for (i = 0; i < REPORT_SIZE; i++)
		data[i] = 0;
	data[0] = 0xfb;
	data[1] = 0x96;
	data[2] = 0xb1;
	data[3] = 0xe1;
	data[4] = EVENT_VERSION;
	data[5] = EVENT_STEP;
	data[6] = step;
	return 0;
}

/*
 * The match state lives in memory and is read and written on every byte.
 * Keeping it in a register lets the verifier track exact values and fork a
 * path per value per position, which exceeds its complexity limit.
 */
#define READ_ONCE(x)		(*(volatile typeof(x) *)&(x))
#define WRITE_ONCE(x, v)	(*(volatile typeof(x) *)&(x) = (v))

SEC(HID_BPF_DEVICE_EVENT)
int BPF_PROG(fw16_backlight_event, struct hid_bpf_ctx *hctx)
{
	__u8 *data = hid_bpf_get_data(hctx, 0, REPORT_SIZE);
	int i;

	if (!data)
		return -EINVAL;

	for (i = 0; i < REPORT_SIZE; i++) {
		__u8 c = data[i];
		__u32 m;

		if (c == 0)
			continue;

		m = READ_ONCE(matched);

		if (m == PATTERN_LEN) {
			WRITE_ONCE(matched, 0);
			if (c >= '0' && c <= '3') {
				/*
				 * Match complete: replace this report with the
				 * event report and stop. Any bytes after the
				 * digit in this report are dropped unmatched.
				 */
				return emit_event(data, c - '0');
			}
			m = 0;
		}

		if (c == pattern[m & (PATTERN_LEN - 1)])
			WRITE_ONCE(matched, m + 1);
		else
			WRITE_ONCE(matched, c == pattern[0] ? 1 : 0);
	}

	/* Every report that does not complete a match is dropped. */
	return -EINVAL;
}

HID_BPF_OPS(fw16_backlight) = {
	.hid_device_event = (void *)fw16_backlight_event,
};

SEC("syscall")
int probe(struct hid_bpf_probe_args *ctx)
{
	ctx->retval = -EINVAL;

	if (ctx->rdesc_size > 3 &&
	    ctx->rdesc[0] == 0x06 &&
	    ctx->rdesc[1] == 0x31 &&
	    ctx->rdesc[2] == 0xff)
		ctx->retval = 0;

	return 0;
}

char _license[] SEC("license") = "GPL";
