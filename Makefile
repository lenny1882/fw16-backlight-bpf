CLANG   ?= clang
BPFTOOL ?= bpftool
BUILD   := build
NAME    := fw16-backlight
OBJ     := $(BUILD)/$(NAME).bpf.o
SYNC    := $(BUILD)/$(NAME)-sync
CC      ?= cc
CFLAGS  := -std=gnu11 -fno-stack-protector -O2 -target bpf -g -c -fms-extensions -Wno-microsoft-anon-tag -Wall

all: $(OBJ) $(SYNC)

$(SYNC): src/$(NAME)-sync.c | $(BUILD)
	$(CC) -std=gnu11 -O2 -Wall -Wextra -o $@ $<

$(BUILD):
	mkdir -p $@

$(BUILD)/vmlinux.h: /sys/kernel/btf/vmlinux | $(BUILD)
	$(BPFTOOL) btf dump file $< format c > $@

$(BUILD)/$(NAME).raw.o: bpf/$(NAME).bpf.c $(BUILD)/vmlinux.h $(wildcard bpf/include/*.h)
	$(CLANG) $(CFLAGS) -I$(BUILD) -Ibpf/include $< -o $@

$(OBJ): $(BUILD)/$(NAME).raw.o
	$(BPFTOOL) gen object $@ $<

install: $(OBJ)
	sudo udev-hid-bpf install --force $(OBJ)

uninstall:
	sudo rm -f /etc/udev-hid-bpf/$(NAME).bpf.o /etc/udev/rules.d/99-hid-bpf-$(NAME).rules
	sudo udevadm control --reload

clean:
	rm -rf $(BUILD)

.PHONY: all install uninstall clean
