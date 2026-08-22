#!/usr/bin/env bash
#
# Read a PiTrac memory card on another computer, when the enclosure itself
# cannot be reached.
#
# An enclosure that will not come back after a power cut cannot be asked what
# happened. The card can. Take it out, put it in a reader, and run this.
#
#   ./packaging/pi/read-card.sh                  # find the card automatically
#   ./packaging/pi/read-card.sh /Volumes/rootfs  # or say where it is
#
# macOS cannot read the Linux partition without extra software, so on a Mac
# this reports what it can from the boot partition and says plainly what it
# cannot see. On Linux, mount the root partition and point this at it for the
# full picture.
#
set -uo pipefail

say()  { printf '  %s\n' "$*"; }
head2() { printf '\n\033[1m%s\033[0m\n' "$*"; }

find_card() {
    for candidate in "$@"; do
        [ -d "$candidate" ] && { printf '%s' "$candidate"; return 0; }
    done
    for candidate in /Volumes/rootfs /Volumes/writable /media/*/rootfs /mnt/rootfs \
                     /Volumes/bootfs /Volumes/boot /media/*/bootfs; do
        [ -d "$candidate" ] && { printf '%s' "$candidate"; return 0; }
    done
    return 1
}

CARD="$(find_card "${1:-}")" || {
    echo "No PiTrac card found."
    echo
    echo "Put the microSD card in a reader and try again, or pass the path:"
    echo "    $0 /Volumes/rootfs"
    exit 1
}
printf '\nReading %s\n' "$CARD"

# --- Which partition is this? ---------------------------------------------
if [ -d "$CARD/var/lib/pitrac-easy-connect" ] || [ -d "$CARD/etc" ]; then
    KIND=root
else
    KIND=boot
fi
say "This looks like the ${KIND} partition."

if [ "$KIND" = boot ]; then
    head2 "What the boot partition can tell us"
    [ -f "$CARD/cmdline.txt" ] && say "cmdline.txt: $(head -c 200 "$CARD/cmdline.txt")"
    if [ -f "$CARD/config.txt" ]; then
        say "config.txt overrides:"
        grep -vE '^\s*(#|$)' "$CARD/config.txt" 2>/dev/null | sed 's/^/      /' | head -20
    fi
    ls "$CARD"/*.txt >/dev/null 2>&1 && say "files: $(ls "$CARD" | tr '\n' ' ' | cut -c1-160)"
    head2 "What it cannot"
    cat <<'NOTE'
  The logs, the network settings and Easy-Connect's own state all live on the
  Linux partition, which macOS cannot read without extra software.

  Three ways on from here, cheapest first:

  1. Plug the Pi into your router with an ethernet cable and try again. Wi-Fi
     may be the only thing that is broken.
  2. Look for a Wi-Fi network called PiTrac- followed by four characters. If it
     is there, the Pi booted fine and fell back to its own setup signal --
     join it with the password from the owner card and open http://10.42.0.1
  3. Put the card in any Linux machine, or a Raspberry Pi that does boot, and
     run this script against the mounted root partition.
NOTE
    exit 0
fi

# --- The root partition, which is where the answers are -------------------
head2 "Did Easy-Connect start, and what did it decide?"
JOURNAL="$CARD/var/log/journal"
if [ -d "$JOURNAL" ]; then
    if command -v journalctl >/dev/null 2>&1; then
        journalctl -D "$JOURNAL" -u pitrac-easy-connect -n 80 --no-pager 2>/dev/null \
            | sed 's/^/      /' || say "journalctl could not read it"
    else
        say "Journal present at var/log/journal, but journalctl is not on this computer."
        say "Copy that directory to a Linux machine and run:"
        say "    journalctl -D journal -u pitrac-easy-connect -n 200"
    fi
else
    say "No persistent journal on this card."
    say "It was installed before persistent logging was turned on, so the"
    say "record of what happened was erased when the power went."
fi

head2 "What network did it think it was on?"
STATE="$CARD/var/lib/pitrac-easy-connect"
for file in network.json network.json.bak settings.json; do
    if [ -f "$STATE/$file" ]; then
        say "$file:"
        sed 's/^/      /' "$STATE/$file" 2>/dev/null | head -20
    fi
done
[ -f "$STATE/device.json" ] && say "device.json is present (identity intact)"

head2 "Was a network change interrupted?"
if grep -q '"pending"' "$STATE/network.json" 2>/dev/null; then
    say "YES. A change was in progress when the power went."
    say "Easy-Connect should undo it on the next boot and go back to the"
    say "previous network. If it did not, that is the bug to chase."
else
    say "No interrupted change recorded."
fi

head2 "What Wi-Fi does the Pi actually know?"
NM="$CARD/etc/NetworkManager/system-connections"
if [ -d "$NM" ]; then
    for profile in "$NM"/*; do
        [ -f "$profile" ] || continue
        name=$(basename "$profile")
        ssid=$(grep -m1 '^ssid=' "$profile" 2>/dev/null | cut -d= -f2-)
        auto=$(grep -m1 '^autoconnect=' "$profile" 2>/dev/null | cut -d= -f2-)
        say "$name  ssid=${ssid:-?}  autoconnect=${auto:-yes (default)}"
    done
else
    say "No NetworkManager profiles readable at etc/NetworkManager/system-connections"
fi
[ -d "$CARD/etc/netplan" ] && say "netplan files: $(ls "$CARD/etc/netplan" | tr '\n' ' ')"

head2 "Did the filesystem take damage?"
if [ -d "$CARD/lost+found" ] && [ -n "$(ls -A "$CARD/lost+found" 2>/dev/null)" ]; then
    say "lost+found is NOT empty, which means fsck recovered orphaned files."
    say "That is a sign of an unclean shutdown corrupting the card."
else
    say "lost+found is empty or absent, which is the healthy case."
fi

head2 "Was it shut down cleanly?"
if [ -f "$CARD/var/lib/systemd/random-seed" ]; then
    say "random-seed present (written on clean shutdown, so this is a good sign)"
fi

printf '\nDone.\n\n'
