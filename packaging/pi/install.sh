#!/usr/bin/env bash
#
# Install PiTrac Easy Connect on a Raspberry Pi running PiTrac.
#
# Safe to run more than once: it replaces the application files and restarts the
# service, and never touches the device identity, saved networks, pairings, or
# PiTrac's own calibration.
#
#   sudo ./install.sh                 install or upgrade
#   sudo ./install.sh --set-hostname  also rename this Pi to pitrac-<device id>
#   sudo ./install.sh --uninstall     remove the service, keep the settings
#
# The hostname is left alone by default. Renaming would change the .local
# address the owner already uses to reach this Pi. Pass --set-hostname when a
# second enclosure joins the same network and the two would otherwise collide.
#
set -euo pipefail

APP_ROOT=/usr/lib/pitrac-easy-connect-releases
APP_DIR=/usr/lib/pitrac-easy-connect
VERSION="$(python3 -c "import re,pathlib,sys; print(re.search(r'__version__ = \"([^\"]+)\"', pathlib.Path(sys.argv[1]).read_text()).group(1))" "$(dirname "$0")/../../src/pitrac_easy_connect/__init__.py" 2>/dev/null || echo unknown)"
STATE_DIR=/var/lib/pitrac-easy-connect
UNIT=/etc/systemd/system/pitrac-easy-connect.service
SERVICE=pitrac-easy-connect.service
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

say()  { printf '  %s\n' "$*"; }
step() { printf '\n\033[1m%s\033[0m\n' "$*"; }
die()  { printf '\nERROR: %s\n' "$*" >&2; exit 1; }

[ "$(id -u)" -eq 0 ] || die "Run this with sudo."

SET_HOSTNAME=no
UNINSTALL=no
for argument in "$@"; do
    case "$argument" in
        --set-hostname) SET_HOSTNAME=yes ;;
        --uninstall) UNINSTALL=yes ;;
        *) die "Unknown option: $argument" ;;
    esac
done

# Only the first argument used to be checked, so "--set-hostname --uninstall"
# quietly installed instead of uninstalling.
if [ "$UNINSTALL" = yes ] && [ "$SET_HOSTNAME" = yes ]; then
    die "--set-hostname and --uninstall cannot be used together."
fi

if [ "$UNINSTALL" = yes ]; then
    step "Removing PiTrac Easy Connect"
    systemctl disable --now "$SERVICE" 2>/dev/null || true
    rm -f "$UNIT" /etc/avahi/services/pitrac-easy-connect.service
    rm -rf "$APP_DIR" "$APP_ROOT" /usr/share/doc/pitrac-easy-connect

    # Ours to remove: a drop-in that changed logging for the whole system.
    # This used to sit after the exit below, so it never ran.
    rm -f /etc/systemd/journald.conf.d/pitrac-easy-connect.conf
    rmdir /etc/systemd/journald.conf.d 2>/dev/null || true
    systemctl restart systemd-journald >/dev/null 2>&1 || true

    systemctl daemon-reload
    say "Removed, including the journal size limits this installer had set."
    say "Settings were kept in $STATE_DIR."
    say "PiTrac's simulator address still points at the relay; set it in PiTrac's"
    say "dashboard if you want to send shots somewhere else."
    exit 0
fi

step "Checking this Raspberry Pi"
MODEL="$(tr -d '\0' < /proc/device-tree/model 2>/dev/null || echo unknown)"
say "Model: $MODEL"
case "$MODEL" in
    *"Raspberry Pi 5"*) ;;
    *) say "WARNING: this release is tested on a Raspberry Pi 5." ;;
esac

ARCH="$(uname -m)"
[ "$ARCH" = "aarch64" ] || die "Easy Connect needs 64-bit Raspberry Pi OS (found $ARCH)."

command -v python3 >/dev/null || die "python3 is not installed."
PY_OK=$(python3 -c 'import sys; print(1 if sys.version_info >= (3, 9) else 0)')
[ "$PY_OK" = "1" ] || die "Easy Connect needs Python 3.9 or newer."
say "Python: $(python3 -V 2>&1)"

command -v nmcli >/dev/null || die "NetworkManager (nmcli) is required."
say "NetworkManager: $(nmcli --version | awk '{print $NF}')"
systemctl is-active --quiet NetworkManager || die "NetworkManager is not running."

if ! nmcli -t -f DEVICE,TYPE device status | grep -q ':wifi$'; then
    die "No Wi-Fi device was found."
fi

# The enclosure's setup signal needs the radio to support access-point mode.
if command -v iw >/dev/null && ! iw list 2>/dev/null | grep -qE '^\s+\* AP$'; then
    say "WARNING: this Wi-Fi adapter may not support the setup hotspot."
fi

step "Finding the PiTrac installation"
PITRAC_USER="${SUDO_USER:-pitracuser}"
PITRAC_HOME="$(getent passwd "$PITRAC_USER" | cut -d: -f6)"
[ -n "$PITRAC_HOME" ] || die "Could not find the home directory for $PITRAC_USER."
PITRAC_CONFIG_DIR="$PITRAC_HOME/.pitrac/config"
say "PiTrac user:   $PITRAC_USER"
say "PiTrac config: $PITRAC_CONFIG_DIR"

if [ ! -x /usr/lib/pitrac/pitrac_lm ]; then
    say "WARNING: /usr/lib/pitrac/pitrac_lm was not found. Install PiTrac first"
    say "         if you want shots forwarded to your simulator."
fi

install -d -o "$PITRAC_USER" -g "$PITRAC_USER" "$PITRAC_CONFIG_DIR"

step "Installing the application"
[ -d "$HERE/../../src/pitrac_easy_connect" ] || die "Run this from the repository's packaging/pi directory."

# Build the new copy beside the running one, then swap. Deleting the working
# installation before copying its replacement meant a power cut, a full card
# or a bad copy during an upgrade left an enclosure with no software at all
# and no way to reach it.
STAGING="${APP_DIR}.incoming"
rm -rf "$STAGING"
install -d -m 0755 "$STAGING"
cp -r "$HERE/../../src/pitrac_easy_connect" "$STAGING/"

# The licence and notices belong on the machine, not only in the repository
# somebody built this from.
install -d -m 0755 /usr/share/doc/pitrac-easy-connect
install -m 0644 "$HERE/../../LICENSE" /usr/share/doc/pitrac-easy-connect/ 2>/dev/null || true
install -m 0644 "$HERE/../../NOTICE.md" /usr/share/doc/pitrac-easy-connect/ 2>/dev/null || true
find "$STAGING" -name '__pycache__' -type d -prune -exec rm -rf {} + 2>/dev/null || true
# Source copied from a Mac carries AppleDouble sidecars. Python ignores them,
# but they clutter the install and confuse anyone reading it.
find "$STAGING" -name '._*' -type f -delete 2>/dev/null || true

# Check the staged copy actually runs before it becomes the installed one.
python3 -c "import sys; sys.path.insert(0, '$STAGING'); import pitrac_easy_connect" \
    || die "The copied software did not load. The existing installation was left alone."

# Versioned directories behind a symlink. Two renames left a moment with no
# application directory at all, and a power cut in that moment leaves a Pi
# with no software and no way to reach it. A symlink swap is one atomic
# operation: it either points at the old version or the new one, never at
# nothing.
RELEASES="${APP_ROOT}/releases"
THIS_RELEASE="${RELEASES}/${VERSION}-$(date +%s)"
install -d -m 0755 "$RELEASES"
mv "$STAGING" "$THIS_RELEASE"

PREVIOUS_TARGET=""
if [ -L "$APP_DIR" ]; then
    PREVIOUS_TARGET="$(readlink -f "$APP_DIR")"
elif [ -d "$APP_DIR" ]; then
    # Upgrading from a layout that had a real directory here.
    PREVIOUS_TARGET="${RELEASES}/before-symlinks"
    rm -rf "$PREVIOUS_TARGET"
    mv "$APP_DIR" "$PREVIOUS_TARGET"
fi

ln -sfn "$THIS_RELEASE" "${APP_DIR}.new"
mv -Tf "${APP_DIR}.new" "$APP_DIR"
say "Installed to $THIS_RELEASE"

# Settings, pairings, and the device identity live here and survive upgrades.
install -d -m 0750 "$STATE_DIR"

step "Installing the service"
HOSTNAME_FLAG="--no-hostname"
if [ "$SET_HOSTNAME" = "yes" ]; then
    HOSTNAME_FLAG=""
    say "This Pi will be renamed to match its device ID."
else
    say "Leaving the hostname as '$(hostname)'. Use --set-hostname to change it."
fi
# --- Make the logs survive a reboot ---------------------------------------
#
# Raspberry Pi OS keeps the journal in a tmpfs, so every reboot erases it. That
# is fine until an enclosure fails to come back and the only question worth
# asking is what happened before it went down -- at which point there is
# nothing to read. A capped persistent journal costs a little card space and
# makes that question answerable.
#
# Done before the service starts, so the very first boot is recorded.
step "Making the system journal survive a reboot"
mkdir -p /var/log/journal
systemd-tmpfiles --create --prefix /var/log/journal >/dev/null 2>&1 || true
install -d -m 0755 /etc/systemd/journald.conf.d
cat > /etc/systemd/journald.conf.d/pitrac-easy-connect.conf <<'JOURNAL'
# Keep enough history to explain a failure to come back after a power cut, and
# cap it so a microSD card is neither worn out nor filled by logging.
[Journal]
Storage=persistent
SystemMaxUse=64M
SystemMaxFileSize=8M
MaxRetentionSec=1month
JOURNAL
systemctl restart systemd-journald >/dev/null 2>&1 || true
say "Logs will survive a reboot, capped at 64 MB"

sed -e "s|__PITRAC_CONFIG_DIR__|$PITRAC_CONFIG_DIR|g" \
    -e "s|__HOSTNAME_FLAG__|$HOSTNAME_FLAG|g" \
    "$HERE/pitrac-easy-connect.service" > "$UNIT"
chmod 0644 "$UNIT"
systemctl daemon-reload
systemctl enable "$SERVICE" >/dev/null
systemctl restart "$SERVICE"
say "Enabled and started $SERVICE"

step "Waiting for it to come up"
for _ in $(seq 1 30); do
    if systemctl is-active --quiet "$SERVICE"; then break; fi
    sleep 1
done
# Sustained health, not the first moment systemd says "active". A service that
# starts and dies two seconds later used to pass this and take the only
# working copy with it.
HEALTHY=yes
for _ in 1 2 3 4 5 6; do
    sleep 1
    systemctl is-active --quiet "$SERVICE" || { HEALTHY=no; break; }
done

if [ "$HEALTHY" = yes ]; then
    # Keep the previous release. Disk is cheap; a Pi with no way back is not.
    ls -1dt "${RELEASES}"/* 2>/dev/null | tail -n +3 | xargs -r rm -rf
else
    journalctl -u "$SERVICE" -n 30 --no-pager || true
    if [ -n "$PREVIOUS_TARGET" ] && [ -d "$PREVIOUS_TARGET" ]; then
        say "Putting the previous version back"
        ln -sfn "$PREVIOUS_TARGET" "${APP_DIR}.new"
        mv -Tf "${APP_DIR}.new" "$APP_DIR"
        systemctl restart "$SERVICE" 2>/dev/null || true
    fi
    die "The service did not start. The log above says why; the previous version was restored."
fi

sleep 3
printf '\n'
if PYTHONPATH="$APP_DIR" python3 - <<'PYEOF'
import sys
sys.path.insert(0, "/usr/lib/pitrac-easy-connect")
from pathlib import Path
from pitrac_easy_connect.common.identity import IdentityStore

identity = IdentityStore(Path("/var/lib/pitrac-easy-connect/device.json")).identity
print("=" * 62)
print(identity.owner_card())
print("=" * 62)
PYEOF
then :; else say "(the owner card can be printed later from the setup page)"; fi

step "Done"
say "Print or photograph the card above and keep it with the enclosure."
say "Setup page on your network:  http://$(hostname).local"
say "Setup page on PiTrac's own signal: http://10.42.0.1"
say ""
say "Next: install PiTrac Easy-Connect on your computer and pair it."
