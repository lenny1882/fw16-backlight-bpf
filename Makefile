CLANG   ?= clang
BPFTOOL ?= bpftool
CC      ?= cc
SUDO    ?= sudo
BUILD   := build
NAME    := fw16-backlight
OBJ     := $(BUILD)/$(NAME).bpf.o
SYNC    := $(BUILD)/$(NAME)-sync
CFLAGS  := -std=gnu11 -fno-stack-protector -O2 -target bpf -g -c -fms-extensions -Wno-microsoft-anon-tag -Wall

PREFIX     ?= /usr/local
LIBEXECDIR ?= $(PREFIX)/lib/$(NAME)
UNIT       := $(NAME)-sync.service
RULES      := 70-$(NAME).rules
RULES_DIR  := /etc/udev/rules.d
UNIT_DIR   := /etc/systemd/system
SYSUSERS   := /etc/sysusers.d/$(NAME).conf
KB_PID     := 0018

all: check-build $(OBJ) $(SYNC) $(BUILD)/$(UNIT) $(BUILD)/$(RULES)

# B1: name the missing tool and its Arch package instead of a raw error.
check-build:
	@command -v $(CC) >/dev/null || { echo "missing C compiler '$(CC)' (Arch package: gcc)"; exit 1; }
	@command -v $(CLANG) >/dev/null || { echo "missing '$(CLANG)' (Arch package: clang)"; exit 1; }
	@command -v $(BPFTOOL) >/dev/null || { echo "missing '$(BPFTOOL)' (Arch package: bpf)"; exit 1; }
	@test -e /sys/kernel/btf/vmlinux || { echo "/sys/kernel/btf/vmlinux is missing: the kernel needs CONFIG_DEBUG_INFO_BTF=y"; exit 1; }

check-install:
	@command -v udev-hid-bpf >/dev/null || { echo "missing 'udev-hid-bpf' (Arch package: udev-hid-bpf)"; exit 1; }
	@command -v systemd-sysusers >/dev/null || { echo "missing 'systemd-sysusers' (Arch package: systemd)"; exit 1; }

$(BUILD):
	mkdir -p $@

$(SYNC): src/$(NAME)-sync.c | $(BUILD)
	$(CC) -std=gnu11 -O2 -Wall -Wextra -o $@ $<

$(BUILD)/vmlinux.h: /sys/kernel/btf/vmlinux | $(BUILD)
	$(BPFTOOL) btf dump file $< format c > $@

$(BUILD)/$(NAME).raw.o: bpf/$(NAME).bpf.c $(BUILD)/vmlinux.h $(wildcard bpf/include/*.h)
	$(CLANG) $(CFLAGS) -I$(BUILD) -Ibpf/include $< -o $@

$(OBJ): $(BUILD)/$(NAME).raw.o
	$(BPFTOOL) gen object $@ $<

$(BUILD)/$(UNIT): dist/$(UNIT).in Makefile | $(BUILD)
	sed 's|@LIBEXECDIR@|$(LIBEXECDIR)|g' $< > $@

$(BUILD)/$(RULES): dist/$(RULES).in Makefile | $(BUILD)
	sed 's|@LIBEXECDIR@|$(LIBEXECDIR)|g' $< > $@

# Idempotent: every file is overwritten, enable --now is safe to repeat.
# The filter and permissions apply to a module when it next appears (reboot or
# re-seat); `make reload` applies them to the modules that are already attached.
install: all check-install $(BUILD)/$(UNIT) $(BUILD)/$(RULES)
	$(SUDO) udev-hid-bpf install --force $(OBJ)
	$(SUDO) install -Dm755 $(SYNC) $(LIBEXECDIR)/$(NAME)-sync
	$(SUDO) install -Dm755 dist/grant-console $(LIBEXECDIR)/grant-console
	$(SUDO) install -Dm644 dist/$(NAME).sysusers $(SYSUSERS)
	$(SUDO) install -Dm644 $(BUILD)/$(RULES) $(RULES_DIR)/$(RULES)
	$(SUDO) install -Dm644 $(BUILD)/$(UNIT) $(UNIT_DIR)/$(UNIT)
	$(SUDO) systemd-sysusers $(SYSUSERS)
	$(SUDO) udevadm control --reload
	$(SUDO) systemctl daemon-reload
	$(SUDO) systemctl enable --now $(UNIT)

# Apply the installed rules to keyboard modules that are already attached.
reload:
	@for d in /sys/bus/hid/devices/0003:32AC:$(KB_PID).*; do \
		[ -e "$$d" ] && $(SUDO) udev-hid-bpf remove "$$d" || true; \
	done
	$(SUDO) udevadm trigger --action=add --subsystem-match=hid --property-match=MODALIAS=hid:b0003g0001v000032ACp0000$(KB_PID)
	$(SUDO) udevadm settle
	$(SUDO) udevadm trigger --action=change --subsystem-match=hidraw
	$(SUDO) udevadm settle

uninstall:
	-$(SUDO) systemctl disable --now $(UNIT)
	@for d in /sys/bus/hid/devices/0003:32AC:$(KB_PID).*; do \
		[ -e "$$d" ] && $(SUDO) udev-hid-bpf remove "$$d" || true; \
	done
	# udev does not reset ownership on a change event, so nodes granted to the
	# group would keep a dangling group id; reset them before the group goes.
	@if getent group $(NAME) >/dev/null; then \
		$(SUDO) find /dev -maxdepth 1 -name 'hidraw*' -group $(NAME) -exec chgrp root {} + -exec chmod 0600 {} +; \
	fi
	$(SUDO) rm -f /etc/udev-hid-bpf/$(NAME).bpf.o /etc/udev/rules.d/99-hid-bpf-$(NAME).rules \
		$(RULES_DIR)/$(RULES) $(UNIT_DIR)/$(UNIT) $(SYSUSERS) \
		$(LIBEXECDIR)/$(NAME)-sync $(LIBEXECDIR)/grant-console
	-$(SUDO) rmdir $(LIBEXECDIR)
	-$(SUDO) groupdel $(NAME)
	$(SUDO) udevadm control --reload
	$(SUDO) systemctl daemon-reload
	$(SUDO) udevadm trigger --action=change --subsystem-match=hidraw

clean:
	rm -rf $(BUILD)

.PHONY: all check-build check-install install reload uninstall clean
