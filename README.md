# Fancy DWM: Ubuntu Desktop Setup

Deploy a Luke Smith-style DWM desktop, terminal environment, Chinese input method, and system tray on another Ubuntu computer. The installer reads the destination machine's username, home directory, and hardware configuration. It does not copy passwords, browser profiles, SSH keys, shell history, or personal input-method dictionaries.

## Install on a new computer

Clone the repository and install the complete setup, including FortiClient and disk hibernation:

```sh
git clone https://github.com/Flowming-ai/fancy_dwm.git
cd fancy_dwm
sh install.sh --full
```

`--full` checks hardware and boot requirements first. Automatic hibernation setup currently requires an unencrypted ext4 root filesystem on a plain disk or partition, GRUB, disabled Secure Boot and kernel lockdown, and support for ACPI platform hibernation. Unsupported configurations stop with an explanation rather than using guessed disk offsets. The pinned FortiClient package is available for amd64 only. To install just the desktop, 150% scaling, and Teams launcher, run `sh install.sh` without `--full`.

The installer targets **Ubuntu Desktop 24.04 and 26.04, on amd64 or arm64**. It requires an existing graphical login manager, internet access, and a regular user with sudo privileges. Other Ubuntu releases are rejected. Compatibility with every hardware configuration or graphics driver is not guaranteed. Downloads come from Ubuntu package repositories, official GitHub releases, and Fortinet's official download server for the optional VPN client.

Alternatively, copy the portable archive to the new computer and run:

```sh
tar -xzf ubuntu-dwm-setup.tar.gz
cd ubuntu-dwm-setup
sh install.sh
```

Run these commands as your regular desktop user. **Do not put `sudo` before `sh`.** The installer requests the destination computer's sudo password when needed. Initial font, plugin, and package downloads require internet access; the archive is a portable online installer, not an offline Ubuntu image.

After installation, save your work, log out, and sign in again. The installer sets DWM as the current user's default session. If the login manager still shows the previous selection, choose **DWM** once from its session menu. The installer does not log you out or reboot automatically. GNOME remains available from the login screen.

Check the archive and host requirements without installing, downloading, or hibernating:

```sh
sh install.sh --check
# Also check local requirements for the optional VPN and hibernation modules.
sh install.sh --check --full
```

Keep your current default login session:

```sh
sh install.sh --skip-default-session
```

Choose individual options:

```sh
sh install.sh --scale 125                 # 100/125/150/175/200; default: 150
sh install.sh --with-forticlient          # Desktop + VPN client
sh install.sh --with-hibernation          # Desktop + disk hibernation
```

## Included components

| Component | Installation and configuration |
| --- | --- |
| Desktop | Pinned Luke DWM, st, dmenu, and dwmblocks sources, compiled on the destination machine |
| System tray | Adapted XEmbed tray on the rightmost monitor, preserving clickable status text and DWM restarts |
| Terminals | st; Kitty with JetBrainsMono Nerd Font and 0.85 background opacity |
| Shell | Zsh as the default shell, Oh My Zsh, autosuggestions, syntax highlighting, and a colorful Starship prompt |
| Command-line tools | fastfetch, eza, bat, and btop; `ls` uses eza and `cat` uses bat |
| Launchers and notifications | Rofi, dmenu, Dunst, and Papirus icons |
| Chinese input | Fcitx5 Pinyin, GTK/Qt frontends, Chinese fonts, and candidate prediction; toggle with Ctrl+Space |
| Desktop effects | Picom transparency, shadows, and fading; the bundled wallpaper is preserved |
| Screenshots | Flameshot tray icon; existing maim shortcuts on Print and Shift+Print |
| Screensaver and locking | XScreenSaver starts with the DWM session; locking is available from the session menu |
| Everyday tools | lf, Neovim, and utilities for audio, brightness, networking, and displays |
| Display scaling | 150% by default for Xft/GTK/Qt/Rofi, cursor sizing, and XSettings; xsettingsd is installed on the destination machine |
| Teams | Launcher for Microsoft's official Teams website; prefers a standalone Chrome/Edge/Chromium app window and falls back to a browser page |
| Disk hibernation (optional) | Calculates swap size, UUID, and resume offset on the destination machine; detects Dracut/initramfs-tools; uses platform/S4 and the minimal-memory snapshot fix |
| FortiClient (optional) | Official VPN-only package, SHA-256 verification, automatic dependency resolution through APT including libnss3-tools, and an enabled background service |

The status bar uses **dwmblocks**. The earlier slstatus setup is not started alongside it. Chinese input uses open-source Fcitx5 Pinyin; the proprietary Sogou installer is not included. Existing personal dictionaries are preserved.

## Keyboard shortcuts

**Super is the Windows key.**

| Shortcut | Action |
| --- | --- |
| **Win+Space** | Promote the focused tiled window to the master area |
| Win+Shift+Space | Toggle floating mode for the focused window |
| Win+t | Switch to the side-by-side tiling layout |
| Win+j / k | Focus the next / previous window |
| Win+h / l | Shrink / expand the master area |
| Win+Enter | Open st |
| Alt+Shift+Enter / Ctrl+Alt+t | Alternative terminal shortcuts |
| Win+Shift+d | Open Kitty |
| Alt+d | Open the Rofi application launcher |
| Ctrl+Space | Toggle Chinese / English input |
| Ctrl+Shift+c / v | Copy / paste in the terminal |
| Win+Shift+Backspace | Restart DWM while keeping open windows |
| Win+Backspace | Open the session menu: lock, disk hibernation, and logout |
| Win+F1 | Show the full shortcut reference |

For a floating window, press Win+Shift+Space first, then Win+Space to promote it to the tiled master area. If the current layout has no master area, press Win+t first.

## Hibernation and VPN requirements

The hibernation module does not copy the original computer's UUID, swap offset, fixed 36 GiB swap size, or username. It allocates a dedicated swap file based on the destination machine's RAM, keeps existing swap active, and backs up boot configuration and initramfs files before making changes. On failure, it restores configuration and retains any newly created swap file to avoid memory exhaustion from `swapoff`. Reboot normally once after setup, run `~/.local/bin/dwm-hibernate --check`, and then confirm hibernation through the Win+Backspace menu. On an unconfigured machine, the helper explains what is missing; it does not substitute suspend-to-RAM for disk hibernation.

The current policy is **ACPI S4/platform with image_size=0**. Keyboard and mouse wake support depends on firmware, USB ports, and standby power. The installer does not guarantee this behavior on every motherboard or enable wakeup indiscriminately for unknown devices. NVIDIA hibernation services, video-memory preservation, and temporary storage also depend on the destination machine's driver configuration. See the [hibernation module documentation](scripts/hibernate/README.md).

FortiClient is pinned to the VPN-only **7.4.3.5411** release used on the original machine. Any healthy existing installation is preserved, avoiding automatic upgrades, downgrades, or package scripts that could interrupt an active VPN. The pinned release reproduces this setup; it is not a promise to always install the latest version. Future updates require checking the download and its hash again. After installation, enter your organization's VPN gateway and complete SAML login yourself. VPN databases, passwords, and certificates are not copied. Local use on Ubuntu 26.04/DWM is not vendor certification; see the [Fortinet 7.4.3 support documentation](https://docs.fortinet.com/document/forticlient/7.4.3/linux-release-notes/136392/product-integration-and-support).

The Teams launcher uses an existing browser on the destination computer. It does not copy browser accounts or require Chrome to be installed. Grammarly and LanguageTool were not deployed and are not included. Smart Academic Reader is a separate project and is also outside this desktop repository.

## Configuration and backups

- Editable sources: `~/.local/src/larbs-ubuntu/`.
- Shell configuration: `~/.config/dwm-shell/zshrc`; put personal additions in `~/.zshrc.local`.
- Input method: `~/.config/fcitx5/`.
- Kitty, Picom, and Rofi: their respective directories under `~/.config/`.
- Installation backups and logs: `~/.local/state/ubuntu-dwm-setup/TIMESTAMP/`; the installer prints the exact path.
- Scaling: `~/.Xresources`, `~/.config/xsettingsd/`, and `~/.config/dwm-scale/`.
- Teams: `~/.local/bin/teams-web`.
- Hibernation system backups and independent rollback: `/var/backups/dwm-hibernate/portable-TIMESTAMP/`.
- DWM session logs: `~/.local/state/dwm/`.

Reinstalling backs up and reapplies the desktop settings managed by this repository. Add any customizations you want to keep to the repository first. Existing `.zshrc` and `.profile` files are connected through managed blocks, preserving other content. Desktop rollback does not uninstall APT packages or undo the optional hibernation boot configuration. Hibernation has separate root-owned backups and a rollback script, described in its module documentation. The FortiClient package and background service remain installed; their previous status is recorded in `extras/forticlient-before.json` inside the installation backup, without VPN account data.

```sh
# Preview the files to be restored; replace YOUR_BACKUP_DIRECTORY with the actual directory.
sh scripts/rollback.sh "$HOME/.local/state/ubuntu-dwm-setup/YOUR_BACKUP_DIRECTORY"
# After reviewing the preview, apply the rollback.
sh scripts/rollback.sh "$HOME/.local/state/ubuntu-dwm-setup/YOUR_BACKUP_DIRECTORY" --apply
```

## Validation and sources

See the [validation record](VALIDATION.md), [sources and licenses](NOTICE.md), and [pinned downloads](scripts/downloads.json). Upstream source licenses are preserved. Pinned downloads are checked with SHA-256, plugins use fixed Git commits, and Ubuntu packages receive updates from the configured repositories.

For development, build in a temporary directory and run the tests without installing anything:

```sh
sh scripts/build-check.sh
python3 -m unittest discover -s tests -v
```
