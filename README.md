# Fancy DWM: Ubuntu Desktop Setup

Deploy a Luke Smith-style DWM desktop, terminal environment, Chinese input method, and system tray on another Ubuntu computer. The installer reads the destination machine's username, home directory, and hardware configuration. It does not copy passwords, browser profiles, SSH keys, shell history, or personal input-method dictionaries.

## Install on a new computer

Clone the repository and install the desktop setup:

```sh
git clone https://github.com/Flowming-ai/fancy_dwm.git
cd fancy_dwm
sh install.sh
```

The installer targets **Ubuntu Desktop 24.04 and 26.04, on amd64 or arm64**. It requires an existing graphical login manager, internet access, and a regular user with sudo privileges. Other Ubuntu releases are rejected. Compatibility with every hardware configuration or graphics driver is not guaranteed. Downloads come from Ubuntu package repositories and official project releases.

Alternatively, copy the portable archive to the new computer and run:

```sh
tar -xzf ubuntu-dwm-setup.tar.gz
cd ubuntu-dwm-setup
sh install.sh
```

Run these commands as your regular desktop user. **Do not put `sudo` before `sh`.** The installer requests the destination computer's sudo password when needed. Initial font, plugin, and package downloads require internet access; the archive is a portable online installer, not an offline Ubuntu image.

After installation, save your work, log out, and sign in again. The installer sets DWM as the current user's default session. If the login manager still shows the previous selection, choose **DWM** once from its session menu. The installer does not log you out or reboot automatically. GNOME remains available from the login screen.

Check the archive and host requirements without making changes:

```sh
sh install.sh --check
```

Keep your current default login session:

```sh
sh install.sh --skip-default-session
```

Choose individual options:

```sh
sh install.sh --scale 125                 # 100/125/150/175/200; default: 150
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
| Disk hibernation (optional) | Calculates swap size, UUID, and resume offset on the destination machine; detects Dracut/initramfs-tools; uses platform/S4 and the minimal-memory snapshot fix |

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

## Configuration and backups

- Editable sources: `~/.local/src/larbs-ubuntu/`.
- Shell configuration: `~/.config/dwm-shell/zshrc`; put personal additions in `~/.zshrc.local`.
- Input method: `~/.config/fcitx5/`.
- Kitty, Picom, and Rofi: their respective directories under `~/.config/`.
- Installation backups and logs: `~/.local/state/ubuntu-dwm-setup/TIMESTAMP/`; the installer prints the exact path.
- Scaling: `~/.Xresources`, `~/.config/xsettingsd/`, and `~/.config/dwm-scale/`.
- Hibernation system backups and independent rollback: `/var/backups/dwm-hibernate/portable-TIMESTAMP/`.
- DWM session logs: `~/.local/state/dwm/`.

Reinstalling backs up and reapplies the desktop settings managed by this repository. Add any customizations you want to keep to the repository first. Existing `.zshrc` and `.profile` files are connected through managed blocks, preserving other content. Desktop rollback does not uninstall APT packages or undo the optional hibernation boot configuration. Hibernation has separate root-owned backups and a rollback script, described in the [module documentation](scripts/hibernate/README.md).

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
