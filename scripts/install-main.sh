#!/usr/bin/env bash
# Run via ../install.sh as the desktop user; no downloaded installer is executed.
set -Eeuo pipefail
umask 022
export LC_ALL=C.UTF-8
base=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd -P)
payload="$base/payload"
check=0
skip_default=0
with_hibernation=0
with_forticlient=0
scale=150
usage() {
    cat <<'HELP'
Usage: sh install.sh [--check] [--full] [--scale PERCENT] [--skip-default-session]

Supported: Ubuntu Desktop 24.04 or 26.04, amd64 or arm64, a regular sudo user.
  --check                 Verify this checkout and report the host; change nothing.
  --skip-default-session  Install DWM without changing the login-session preference.
  --scale PERCENT         Desktop scale: 100, 125, 150 (default), 175 or 200.
  --with-hibernation      Configure disk hibernation on supported ext4/GRUB hosts.
  --with-forticlient      Install the pinned FortiClient VPN-only client (amd64).
  --full                  Include both optional modules above.
  --help                  Show this help.

The installer installs apt packages and pinned official shell/font releases,
backs up existing managed files, builds DWM/st/dmenu/dwmblocks as your user,
and sets Zsh and (by default) DWM for your next login. It does not log you out.
Sudo may request your password. Run without sudo before sh.
HELP
}
die() { printf 'Error: %s\n' "$*" >&2; exit 1; }
while (( $# )); do
    case "$1" in
        --check) check=1 ;;
        --skip-default-session) skip_default=1 ;;
        --with-hibernation) with_hibernation=1 ;;
        --with-forticlient) with_forticlient=1 ;;
        --full) with_hibernation=1; with_forticlient=1 ;;
        --scale) [[ $# -ge 2 ]] || die '--scale requires a percentage'; scale=$2; shift ;;
        --scale=*) scale=${1#*=} ;;
        --help|-h) usage; exit 0 ;;
        *) usage >&2; exit 2 ;;
    esac
    shift
done
case "$scale" in 100|125|150|175|200) ;; *) die 'Scale must be 100, 125, 150, 175 or 200.' ;; esac
export DWM_SETUP_SCALE="$scale"
command -v python3 >/dev/null || die 'python3 is required (included in Ubuntu Desktop).'
# The check command stays read-only even inside restricted agent environments.
if (( check )); then
    python3 "$base/scripts/verify.py"
    bash -n "$base/scripts/install-main.sh"
    sh -n "$base/install.sh"
    if (( with_forticlient )); then python3 "$base/scripts/install-forticlient.py" --check; fi
    if (( with_hibernation )); then python3 "$base/scripts/hibernate/configure.py" --check; fi
    if [[ -r /etc/os-release ]]; then
        . /etc/os-release
        printf 'Host: %s; architecture: %s\n' "${PRETTY_NAME:-unknown}" "$(dpkg --print-architecture 2>/dev/null || uname -m)"
    fi
    printf 'NoNewPrivs: %s\n' "$(awk '/^NoNewPrivs:/ {print $2}' /proc/self/status 2>/dev/null || true)"
    printf 'Read-only verification complete; nothing was installed or changed.\n'
    exit 0
fi
[[ $EUID != 0 ]] || die 'Run as the desktop user: sh install.sh (do not prefix sudo).'
if [[ $(awk '/^NoNewPrivs:/ {print $2}' /proc/self/status) == 1 ]]; then
    printf 'This environment sets NoNewPrivs=1, so sudo cannot elevate.\nRun in an ordinary Ubuntu terminal:\n  sh %q\nNo user or system files have been changed.\n' "$base/install.sh" >&2
    exit 77
fi
[[ -r /etc/os-release ]] || die 'Cannot identify this OS.'
. /etc/os-release
[[ ${ID:-} == ubuntu ]] || die 'Only Ubuntu Desktop is supported.'
case ${VERSION_ID:-} in 24.04|26.04) ;; *) die 'Supported Ubuntu versions are 24.04 and 26.04.' ;; esac
arch=$(dpkg --print-architecture)
case "$arch" in amd64|arm64) ;; *) die "Unsupported architecture: $arch" ;; esac
command -v sudo >/dev/null || die 'sudo is required; use an Ubuntu administrator account.'
command -v flock >/dev/null || die 'flock (util-linux) is required.'
task_user=$(id -un)
# Never redirect a root install into SUDO_USER's home or trust a mismatched HOME.
python3 - "$HOME" <<'PY'
import os, pwd, sys
from pathlib import Path
actual = pwd.getpwuid(os.getuid())
if Path(sys.argv[1]).resolve() != Path(actual.pw_dir).resolve():
    raise SystemExit('HOME must be the current desktop user\'s home directory.')
if '\n' in actual.pw_dir or '\n' in sys.argv[1]:
    raise SystemExit('Home paths containing newlines are unsupported.')
for relative in ('.local', '.local/state', '.local/state/ubuntu-dwm-setup'):
    if (Path(sys.argv[1]) / relative).is_symlink():
        raise SystemExit('Installer state directory parents must not be symlinks.')
PY
python3 "$base/scripts/verify.py"
python3 "$base/scripts/install-assets.py" check "$HOME"
python3 "$payload/apply-user.py" --check "$payload" "$HOME"
if (( with_forticlient )); then python3 "$base/scripts/install-forticlient.py" --check; fi
if (( with_hibernation )); then python3 "$base/scripts/hibernate/configure.py" --check; fi
# This project targets Desktop installations with an existing login manager.
if [[ ! -s /etc/X11/default-display-manager ]] \
&& ! command -v gdm3 >/dev/null && ! command -v gdm >/dev/null \
&& ! command -v lightdm >/dev/null && ! command -v sddm >/dev/null; then
    die 'No display manager found. Install Ubuntu Desktop with GDM, LightDM or SDDM first.'
fi
printf '\nInstalling Ubuntu DWM setup for %s (%s).\nSudo will ask for your local password when needed.\n' "$task_user" "$arch"
sudo -v
# Complete the privileged hardware preflight before apt or desktop changes.
if (( with_hibernation )); then sudo python3 "$base/scripts/hibernate/configure.py" --check --user "$task_user"; fi

state="$HOME/.local/state/ubuntu-dwm-setup"
mkdir -p "$state"
chmod 700 "$state"
exec 9>"$state/install.lock"
flock -n 9 || die 'Another installation is already running for this user.'
backup="$state/$(date +%Y%m%d-%H%M%S)-$$"
mkdir -m 700 "$backup"
stage=$(mktemp -d "${TMPDIR:-/tmp}/ubuntu-dwm-setup.XXXXXXXX")
cleanup() {
    local rc=$?
    trap - EXIT
    rm -rf -- "$stage"
    if (( rc )); then
        printf '\nInstallation stopped (exit %s). Backup and log: %s\n' "$rc" "$backup" >&2
        printf 'Review or restore: bash %q %q\n' "$backup/rollback.sh" "$backup" >&2
    fi
    exit "$rc"
}
trap cleanup EXIT
trap 'exit 130' INT
trap 'exit 143' TERM
exec > >(tee -a "$backup/install.log") 2>&1
cp -- "$base/scripts/rollback.sh" "$backup/rollback.sh"
chmod 755 "$backup/rollback.sh"
python3 - "$backup/identity.json" <<'PY'
import json, os, pwd, sys
from pathlib import Path
p = pwd.getpwuid(os.getuid())
Path(sys.argv[1]).write_text(json.dumps(dict(user=p.pw_name, uid=p.pw_uid,
    home=p.pw_dir, shell=p.pw_shell), indent=2) + '\n')
PY
printf 'Backup directory: %s\n' "$backup"

# Ubuntu Desktop normally enables universe already. Enable it explicitly for
# clean installations; no PPA or third-party apt repository is added.
sudo apt-get update
sudo apt-get --no-remove install -y --no-install-recommends ca-certificates curl git gh \
    software-properties-common python3 xz-utils
sudo add-apt-repository -y universe
sudo apt-get update
has_candidate() {
    apt-cache policy "$1" | awk '$1 == "Candidate:" && $2 != "(none)" { found=1 } END { exit !found }'
}
packages=(
    build-essential pkg-config libx11-dev libxft-dev libxinerama-dev libxrender-dev
    libfontconfig-dev libfreetype-dev libharfbuzz-dev libx11-xcb-dev libxcb1-dev libxcb-res0-dev
    xserver-xorg-core xserver-xorg-input-libinput xinit xauth rofi kitty picom dunst xwallpaper xclip x11-utils x11-xserver-utils
    fcitx5 fcitx5-chinese-addons fcitx5-config-qt fcitx5-frontend-gtk3 fcitx5-frontend-qt5 im-config
    dbus-x11 xdg-utils xdg-desktop-portal-gtk desktop-file-utils xsettingsd fontconfig fonts-noto-cjk fonts-noto-color-emoji papirus-icon-theme
    lf btop neovim bc ncal less file maim slop flameshot playerctl pamixer pulsemixer
    arandr brightnessctl suckless-tools pulseaudio-utils network-manager libnotify-bin
    ncurses-bin zsh util-linux e2fsprogs bat eza xscreensaver xscreensaver-data-extra xscreensaver-gl-extra
)
# Frontends vary between Ubuntu releases; GTK3 and Qt5 are always installed.
for optional in fcitx5-frontend-gtk2 fcitx5-frontend-gtk4 fcitx5-frontend-qt6; do
    if has_candidate "$optional"; then packages+=("$optional"); fi
done
need_starship=1
need_fastfetch=1
if has_candidate starship; then packages+=(starship); need_starship=0; fi
if has_candidate fastfetch; then packages+=(fastfetch); need_fastfetch=0; fi
for package in "${packages[@]}"; do
    has_candidate "$package" || die "No apt candidate for $package. Check Ubuntu universe and your configured mirrors."
done
sudo apt-get --no-remove install -y --no-install-recommends "${packages[@]}"

# Network archives are checked against committed SHA256 values before use.
# Git repositories are checked out at full, fixed commit IDs. Build as user.
python3 "$base/scripts/install-assets.py" prepare "$arch" "$stage" "$need_starship" "$need_fastfetch"
cp -- "$stage/downloads-used.json" "$backup/downloads-used.json"
cp -a -- "$payload" "$stage/payload"
staged_payload="$stage/payload"
for project in dwm st dmenu dwmblocks; do
    make -C "$staged_payload/src/$project" clean
    make -C "$staged_payload/src/$project" -j"$(nproc)"
done
tic -c -x "$staged_payload/src/st/st.info"
for binary in dwm/dwm st/st dmenu/dmenu dmenu/stest dwmblocks/dwmblocks; do
    dependencies=$(ldd "$staged_payload/src/$binary")
    [[ $dependencies != *'not found'* ]] || die "Missing runtime library: $binary"
done
sh -n "$staged_payload/system/dwm-session"
zsh -n "$staged_payload/home/.config/dwm-shell/zshrc"

# Each overwritten system file is recorded before the first replacement.
declare -A saved_system=()
backup_system() {
    local target=$1
    [[ ${saved_system[$target]:-} == 1 ]] && return 0
    if [[ -d $target && ! -L $target ]]; then die "Expected a file, found directory: $target"; fi
    if [[ -e $target || -L $target ]]; then
        mkdir -p -- "$backup/system$(dirname -- "$target")"
        sudo cp -a -- "$target" "$backup/system$target"
    fi
    printf '%s\n' "$target" >>"$backup/system-files.txt"
    saved_system[$target]=1
}
install_system() {
    local source=$1 target=$2 mode=${3:-755} temporary
    backup_system "$target"
    sudo install -d -m 755 -- "$(dirname -- "$target")"
    temporary=$(sudo mktemp "$(dirname -- "$target")/.dwm-install.XXXXXXXX")
    if ! sudo install -m "$mode" -- "$source" "$temporary"; then
        sudo rm -f -- "$temporary"
        return 1
    fi
    if ! sudo mv -fT -- "$temporary" "$target"; then
        sudo rm -f -- "$temporary"
        return 1
    fi
}
for binary in dwm/dwm st/st dmenu/dmenu dmenu/stest dwmblocks/dwmblocks \
              dmenu/dmenu_run dmenu/dmenu_path st/st-copyout st/st-urlhandler; do
    install_system "$staged_payload/src/$binary" "/usr/local/bin/${binary##*/}"
done
for optional in starship fastfetch; do
    if [[ -f $stage/artifacts/$optional ]]; then
        install_system "$stage/artifacts/$optional" "/usr/local/bin/$optional"
    fi
done
install_system "$staged_payload/system/dwm-session" /usr/local/bin/dwm-session
install_system "$staged_payload/system/dwm.desktop" /usr/share/xsessions/dwm.desktop 644
install_system "$staged_payload/src/dwm/larbs.mom" /usr/local/share/dwm/larbs.mom 644
for page in dwm/dwm.1 st/st.1 dmenu/dmenu.1 dmenu/stest.1; do
    version=$(awk '$1 == "VERSION" && $2 == "=" {print $3}' "$staged_payload/src/${page%%/*}/config.mk")
    sed "s/VERSION/$version/g" "$staged_payload/src/$page" >"$stage/${page##*/}"
    install_system "$stage/${page##*/}" "/usr/local/share/man/man1/${page##*/}" 644
done

python3 "$base/scripts/install-assets.py" apply "$stage" "$HOME" "$backup"
# User source copies are clean and editable; build artifacts stay temporary.
for project in dwm st dmenu dwmblocks; do make -C "$staged_payload/src/$project" clean; done
python3 "$staged_payload/apply-user.py" "$staged_payload" "$HOME" "$backup"
im-config -n fcitx5
tic -x -o "$HOME/.terminfo" "$staged_payload/src/st/st.info"
fc-cache -f "$HOME/.local/share/fonts/JetBrainsMono"
update-desktop-database "$HOME/.local/share/applications"
zsh -n "$HOME/.zshrc"
# Do not launch or replace input-method processes in the running desktop.
current_shell=$(getent passwd "$task_user" | cut -d: -f7)
if [[ $(readlink -f -- "$current_shell") != $(readlink -f /usr/bin/zsh) ]]; then
    sudo chsh -s /usr/bin/zsh "$task_user"
fi
if (( ! skip_default )); then
    python3 "$base/scripts/set-default-session.py" "$task_user" "$backup"
fi
if (( with_forticlient )); then
    python3 "$base/scripts/install-forticlient.py" --apply --state-dir "$backup/extras"
fi
if (( with_hibernation )); then
    sudo python3 "$base/scripts/hibernate/configure.py" --apply --user "$task_user" | tee "$backup/hibernate.log"
fi
printf '\nInstallation complete. Save your work, then log out and sign in to DWM.\n'
printf 'The current desktop has not been restarted.\n'
printf 'Terminal: Super+Enter; launcher: Alt+d; Chinese: Ctrl+Space; help: Super+F1.\n'
printf 'Backup/log: %s\nEditable sources: %s/.local/src/larbs-ubuntu\n' "$backup" "$HOME"
printf 'Restore preview: bash %q %q\n' "$backup/rollback.sh" "$backup"
printf 'Desktop scale: %s%%; Teams: search Microsoft Teams in Rofi.\n' "$scale"
if (( with_hibernation )); then
    printf 'Hibernation has its own root backup/rollback printed above. Save work and reboot normally before testing.\n'
fi
