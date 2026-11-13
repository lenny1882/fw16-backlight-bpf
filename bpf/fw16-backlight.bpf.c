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

static const char pattern[PATTERN_LEN] = "backlight step: ";
static __u32 matched;

SEC(HID_BPF_DEVICE_EVENT)
int BPF_PROG(fw16_backlight_event, struct hid_bpf_ctx *hctx)
{
	__u8 *data = hid_bpf_get_data(hctx, 0, REPORT_SIZE);
	int i;

	if (!data)
		return 0;

	for (i = 0; i < REPORT_SIZE; i++) {
		__u8 c = data[i];

		if (c == 0)
			continue;

		if (matched == PATTERN_LEN) {
			matched = 0;
			if (c >= '0' && c <= '3') {
				bpf_printk("fw16-backlight: step %d", c - '0');
				continue;
			}
		}

		if (c == pattern[matched & (PATTERN_LEN - 1)])
			matched++;
		else
			matched = c == pattern[0] ? 1 : 0;
	}

	return 0;
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
