// SPDX-License-Identifier: GPL-2.0-only
/*
 * Keep the Framework Laptop 16 numpad backlight level equal to the
 * keyboard's. Blocks in read() on the filtered console node; on each event
 * report it reads the keyboard level over VIA and sets the numpad.
 *
 * Event report and VIA formats: docs/protocol.md.
 */
#define _GNU_SOURCE
#include <dirent.h>
#include <errno.h>
#include <fcntl.h>
#include <poll.h>
#include <stdarg.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>

#define VID		0x32ac
#define PID_KEYBOARD	0x0018	/* ISO; 0x0012 ANSI and 0x0019 JIS also exist */
#define PID_NUMPAD	0x0014

#define REPORT_SIZE	32
#define VIA_TIMEOUT_MS	1000
#define RETRY_SECONDS	2

static const uint8_t desc_console[3] = { 0x06, 0x31, 0xff };
static const uint8_t desc_via[3]     = { 0x06, 0x60, 0xff };
static const uint8_t magic[4]        = { 0xfb, 0x96, 0xb1, 0xe1 };

/* Log a message only when it differs from the previous one. */
static char last_msg[256];

static void report(const char *fmt, ...)
{
	char msg[256];
	va_list ap;

	va_start(ap, fmt);
	vsnprintf(msg, sizeof(msg), fmt, ap);
	va_end(ap);

	if (strcmp(msg, last_msg) == 0)
		return;
	strcpy(last_msg, msg);
	fprintf(stderr, "%s\n", msg);
	fflush(stderr);
}

static void report_clear(void)
{
	last_msg[0] = '\0';
}

/*
 * Find the hidraw node of the device with this product id whose report
 * descriptor starts with desc. Matches on ids and descriptor, never on the
 * hidraw number.
 */
static int find_node(unsigned int pid, const uint8_t desc[3], char *path, size_t len)
{
	DIR *d = opendir("/sys/class/hidraw");
	struct dirent *e;
	int found = -1;

	if (!d)
		return -1;

	while (found < 0 && (e = readdir(d))) {
		char p[512], line[256];
		unsigned int bus, v, prod;
		uint8_t rd[3];
		int match = 0;
		FILE *f;

		if (strncmp(e->d_name, "hidraw", 6) != 0)
			continue;

		snprintf(p, sizeof(p), "/sys/class/hidraw/%s/device/uevent", e->d_name);
		f = fopen(p, "r");
		if (!f)
			continue;
		while (fgets(line, sizeof(line), f)) {
			if (sscanf(line, "HID_ID=%x:%x:%x", &bus, &v, &prod) == 3 &&
			    v == VID && prod == pid)
				match = 1;
		}
		fclose(f);
		if (!match)
			continue;

		snprintf(p, sizeof(p), "/sys/class/hidraw/%s/device/report_descriptor", e->d_name);
		f = fopen(p, "rb");
		if (!f)
			continue;
		if (fread(rd, 1, 3, f) == 3 && memcmp(rd, desc, 3) == 0) {
			snprintf(path, len, "/dev/%.32s", e->d_name);
			found = 0;
		}
		fclose(f);
	}
	closedir(d);
	return found;
}

/*
 * One VIA request/reply on the node at path. req is 3 or 4 bytes; the reply
 * must echo the first three. Writes are 33 bytes (leading report id 0).
 * Returns 0 on success with the 32-byte reply in rep, else -1.
 */
static int via_xfer(const char *path, const uint8_t *req, size_t reqlen, uint8_t rep[REPORT_SIZE])
{
	uint8_t out[REPORT_SIZE + 1] = { 0 };
	struct pollfd pfd;
	int fd, ret = -1, tries;

	fd = open(path, O_RDWR | O_CLOEXEC | O_NONBLOCK);
	if (fd < 0) {
		report("cannot open %s: %s", path, strerror(errno));
		return -1;
	}

	memcpy(out + 1, req, reqlen);
	if (write(fd, out, sizeof(out)) != (ssize_t)sizeof(out)) {
		report("VIA write to %s failed: %s", path, strerror(errno));
		goto out;
	}

	pfd.fd = fd;
	pfd.events = POLLIN;
	for (tries = 0; tries < 4; tries++) {
		if (poll(&pfd, 1, VIA_TIMEOUT_MS) <= 0) {
			report("VIA reply from %s timed out", path);
			goto out;
		}
		if (read(fd, rep, REPORT_SIZE) != REPORT_SIZE)
			continue;
		if (memcmp(rep, req, 3) == 0) {
			ret = 0;
			goto out;
		}
	}
	report("VIA reply from %s did not match the request", path);
out:
	close(fd);
	return ret;
}

/* Copy the keyboard's backlight level to the numpad. */
static void sync_once(void)
{
	static const uint8_t get[3] = { 0x08, 0x01, 0x01 };
	uint8_t set[4] = { 0x07, 0x01, 0x01, 0 };
	uint8_t rep[REPORT_SIZE];
	char kb[64], np[64];

	if (find_node(PID_KEYBOARD, desc_via, kb, sizeof(kb)) < 0) {
		report("keyboard VIA node not found");
		return;
	}
	if (find_node(PID_NUMPAD, desc_via, np, sizeof(np)) < 0) {
		report("numpad VIA node not found");
		return;
	}
	if (via_xfer(kb, get, sizeof(get), rep) < 0)
		return;
	set[3] = rep[3];
	if (via_xfer(np, set, sizeof(set), rep) < 0)
		return;

	report_clear();
}

/*
 * Read event reports until the node goes away. Returns 0 when the node
 * disappears (retry), or exits the process if the console is unfiltered.
 */
static void run_console(const char *path)
{
	uint8_t buf[64];
	int fd = open(path, O_RDONLY | O_CLOEXEC);

	if (fd < 0) {
		report("cannot open %s: %s", path, strerror(errno));
		return;
	}

	/* Cover start, re-enumeration and resume: copy the level now. */
	sync_once();

	for (;;) {
		ssize_t n = read(fd, buf, sizeof(buf));

		if (n < 0 && errno == EINTR)
			continue;
		if (n < 0) {
			report("console read failed: %s", strerror(errno));
			break;
		}
		if (n != REPORT_SIZE)
			continue;

		if (memcmp(buf, magic, sizeof(magic)) != 0) {
			if (buf[0] < 0x80) {
				/* Raw console text: the filter is not attached. */
				fprintf(stderr, "console is not filtered (raw text); refusing to run\n");
				exit(2);
			}
			report("unrecognised report on the console");
			continue;
		}
		if (buf[4] != 0x01) {
			report("unsupported event report version %u", buf[4]);
			continue;
		}
		if (buf[5] == 0x01)
			sync_once();
	}
	close(fd);
}

int main(void)
{
	char path[64];

	for (;;) {
		if (find_node(PID_KEYBOARD, desc_console, path, sizeof(path)) < 0)
			report("keyboard console node not found");
		else
			run_console(path);
		sleep(RETRY_SECONDS);
	}
}
