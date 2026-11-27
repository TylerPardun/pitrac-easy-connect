#!/usr/bin/env bash
#
# Install PiTrac Easy Connect on a Raspberry Pi running PiTrac.
#
# Safe to run more than once: it replaces the application files and restarts the
# service, and never touches the device identity, saved networks, pairings, or
# PiTrac's own calibration.
#
#   sudo ./install.sh                 install or upgrade
#   sudo ./install.sh --set-hostname  accepted for compatibility; now automatic
#   sudo ./install.sh --uninstall     remove the service, keep the settings
#
# Every enclosure uses its identity-derived pitrac-<device id> hostname. The
# UDP beacon remains the primary discovery path; this stable .local name is the
# fallback after DHCP changes the address.
#
set -euo pipefail

APP_ROOT=/usr/lib/pitrac-easy-connect-releases
# The live symlink, inside APP_ROOT because that is the only part of /usr the
# service may write: an update swaps it by creating its replacement beside it.
CURRENT=$APP_ROOT/current
# A fixed pointer to CURRENT, kept so older paths still resolve. It used to be
# the live symlink itself, and beside it is /usr/lib, so no update could swap it.
APP_DIR=/usr/lib/pitrac-easy-connect
# The update guard lives outside both of those on purpose: it is what puts the
# previous release back when a new one will not run, and restarting the
# service ends the process that would otherwise do that.
GUARD_DIR=/usr/lib/pitrac-easy-connect-guard
GUARD_UNIT=/etc/systemd/system/pitrac-easy-connect-update-guard.service
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
    systemctl disable --now pitrac-easy-connect-update-guard.service 2>/dev/null || true
    rm -f "$UNIT" "$GUARD_UNIT" /etc/avahi/services/pitrac-easy-connect.service
    rm -rf "$APP_DIR" "$APP_ROOT" "$GUARD_DIR" /usr/share/doc/pitrac-easy-connect

    # Ours to remove: a drop-in that changed logging for the whole system.
    # This used to sit after the exit below, so it never ran.
    rm -f /etc/systemd/journald.conf.d/pitrac-easy-connect.conf
    rmdir /etc/systemd/journald.conf.d 2>/dev/null || true
    systemctl restart systemd-journald >/dev/null 2>&1 || true

    systemctl daemon-reload
    say "Removed, including the journal size limits this installer had set."
    say "Settings were kept in $STATE_DIR."
    say "PiTrac still lists a simulator named Easy-Connect. Delete it in PiTrac's"
    say "dashboard if you are not going to install this again."
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
if ! command -v avahi-daemon >/dev/null; then
    say "WARNING: avahi-daemon is not installed, so the .local fallback will not work."
elif ! systemctl is-active --quiet avahi-daemon; then
    say "WARNING: avahi-daemon is not running, so the .local fallback will not work."
else
    say "Avahi: active"
fi
say "UDP discovery remains available independently of Avahi."

if ! nmcli -t -f DEVICE,TYPE device status | grep -q ':wifi$'; then
    die "No Wi-Fi device was found."
fi

# The enclosure's setup signal needs the radio to support access-point mode.
if command -v iw >/dev/null && ! iw list 2>/dev/null | grep -qE '^\s+\* AP$'; then
    say "WARNING: this Wi-Fi adapter may not support the setup hotspot."
fi

step "Finding the PiTrac installation"
# Whoever PiTrac's own service runs as, when it is installed. The account this
# was run from is only a guess, and a wrong one finds the wrong home directory.
PITRAC_USER="$(systemctl show -p User --value pitrac-web.service 2>/dev/null || true)"
if [ -z "$PITRAC_USER" ] || [ "$PITRAC_USER" = root ]; then
    PITRAC_USER="${SUDO_USER:-pitracuser}"
fi
PITRAC_HOME="$(getent passwd "$PITRAC_USER" | cut -d: -f6)"
[ -n "$PITRAC_HOME" ] || die "Could not find the home directory for $PITRAC_USER."
PITRAC_CONFIG_DIR="$PITRAC_HOME/.pitrac/config"
say "PiTrac user:   $PITRAC_USER"
say "PiTrac config: $PITRAC_CONFIG_DIR"

if [ ! -x /usr/lib/pitrac/pitrac_lm ]; then
    say "WARNING: /usr/lib/pitrac/pitrac_lm was not found. Install PiTrac first"
    say "         if you want shots forwarded to your simulator."
fi

# Ask PiTrac itself, because that is how shots will be connected. Not fatal:
# PiTrac may still be starting, and Easy-Connect keeps checking.
PITRAC_URL="http://127.0.0.1:8080"
if curl -fs -m 5 "$PITRAC_URL/api/sims" >/dev/null 2>&1 \
    && curl -fs -m 5 "$PITRAC_URL/api/setup/status" >/dev/null 2>&1; then
    say "PiTrac is running and can be connected"
elif curl -s -m 5 -o /dev/null "$PITRAC_URL/health" 2>/dev/null; then
    say "WARNING: PiTrac is running, but is too old (or too new) for this release."
    say "         Install the PiTrac revision named in README.md, then run this again."
else
    say "WARNING: PiTrac's dashboard is not answering yet. Easy-Connect will"
    say "         connect to it when it does."
fi

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

# Development tools. Useful here, and no business on a machine somebody bought:
# a stand-in launch monitor and a fake Raspberry Pi are confusing at best on a
# unit whose real hardware is the point. The service does not import them.
for tool in demo.py ballmachine.py mock_simulators.py pi/simulated.py; do
    rm -f "$STAGING/pitrac_easy_connect/$tool"
done
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
if [ -L "$CURRENT" ]; then
    PREVIOUS_TARGET="$(readlink -f "$CURRENT")"
elif [ -L "$APP_DIR" ]; then
    # The layout before CURRENT existed: the live link was APP_DIR itself.
    PREVIOUS_TARGET="$(readlink -f "$APP_DIR")"
elif [ -d "$APP_DIR" ]; then
    # Migrating from the old layout, which had a real directory here. Copy it
    # aside rather than move it: a move leaves nothing at $APP_DIR until the
    # symlink lands, and a power cut in that gap leaves a Pi with no software.
    # A copy costs a few megabytes and keeps a working install throughout.
    PREVIOUS_TARGET="${RELEASES}/before-symlinks"
    rm -rf "$PREVIOUS_TARGET"
    cp -a "$APP_DIR" "$PREVIOUS_TARGET"
    MIGRATING_FROM_DIRECTORY=yes
fi

# The live link first, then the fixed pointer to it. Each is one atomic
# replacement, and the running service still resolves to the old release until
# it restarts below, so there is no moment where nothing is there.
ln -sfn "$THIS_RELEASE" "${CURRENT}.new"
mv -Tf "${CURRENT}.new" "$CURRENT"
if [ "${MIGRATING_FROM_DIRECTORY:-no}" = yes ]; then
    rm -rf "$APP_DIR"
fi
if [ "$(readlink "$APP_DIR" 2>/dev/null)" != "$CURRENT" ]; then
    ln -sfn "$CURRENT" "${APP_DIR}.new"
    mv -Tf "${APP_DIR}.new" "$APP_DIR"
fi
say "Installed to $THIS_RELEASE"

# Settings, pairings, and the device identity live here and survive upgrades.
install -d -m 0750 "$STATE_DIR"

# The update guard, placed now rather than only when an update needs it: a
# mechanism that installs itself at the moment it is required is a mechanism
# that has never been seen to work. It stays disabled; an update enables it
# for the duration of that update and disables it again afterwards.
install -d -m 0755 "$GUARD_DIR"
install -m 0755 "$THIS_RELEASE/pitrac_easy_connect/pi/update_guard.py" \
    "$GUARD_DIR/pitrac-update-guard.py"
say "Update guard installed to $GUARD_DIR"

step "Installing the service"
HOSTNAME_FLAG=""
say "The stable .local hostname will match this enclosure's device ID."
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
# Running is not the same as working. Ask it what version it is, which proves
# the service is answering and that the release that answered is this one.
#
# Given time, because a Pi that is busy or on a slow card takes a while to start
# Python, and concluding too early puts a working release back.
answer() {
    curl -s -m 5 -H 'X-PiTrac-Portal: 1' http://127.0.0.1/api/status 2>/dev/null \
        | python3 -c 'import json,sys; print(json.load(sys.stdin).get("version",""))' 2>/dev/null || true
}
HEALTHY=no
REPORTED=""
for _ in $(seq 1 45); do
    REPORTED="$(answer)"
    [ -n "$REPORTED" ] && break
    sleep 2
done
if [ -z "$REPORTED" ]; then
    say "The service did not answer within ninety seconds"
elif [ "$REPORTED" != "$VERSION" ] && [ "$VERSION" != unknown ]; then
    say "The service answered as $REPORTED, expected $VERSION"
else
    # Sustained health, not the first moment it spoke. A service that starts and
    # dies seconds later used to pass this and take the only working copy with it.
    sleep 6
    if systemctl is-active --quiet "$SERVICE" && [ "$(answer)" = "$REPORTED" ]; then
        HEALTHY=yes
        say "Answering as version $REPORTED"
    else
        say "The service answered once and then stopped"
    fi
fi

if [ "$HEALTHY" = yes ]; then
    # Keep exactly this release and the one it replaced. Disk is cheap; a Pi
    # with no way back is not. Chosen by name, not by date: the two newest
    # folders are not always these two -- an abandoned update leaves a newer
    # folder behind, and sorting by date then deleted the real way back.
    for old in "${RELEASES}"/*; do
        [ -d "$old" ] || continue
        case "$(readlink -f "$old")" in
            "$(readlink -f "$THIS_RELEASE")"|"${PREVIOUS_TARGET:-/nonexistent}") ;;
            *) rm -rf "$old" ;;
        esac
    done
else
    journalctl -u "$SERVICE" -n 30 --no-pager || true
    if [ -n "$PREVIOUS_TARGET" ] && [ -d "$PREVIOUS_TARGET" ]; then
        say "Putting the previous version back"
        ln -sfn "$PREVIOUS_TARGET" "${CURRENT}.new"
        mv -Tf "${CURRENT}.new" "$CURRENT"
        systemctl restart "$SERVICE" 2>/dev/null || true
    fi
    die "The service did not start. The log above says why; the previous version was restored."
fi

sleep 3
printf '\n'
if PYTHONPATH="$CURRENT" python3 - <<'PYEOF'
import sys
sys.path.insert(0, "/usr/lib/pitrac-easy-connect-releases/current")
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
