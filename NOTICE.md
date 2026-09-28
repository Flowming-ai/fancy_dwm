# Sources and licenses

This repository is a portable configuration snapshot of an Ubuntu desktop. It includes adapted third-party source code.

- The original DWM, st, dmenu, and dwmblocks commits are listed in [payload/SOURCES.txt](payload/SOURCES.txt). Their licenses are preserved in the respective source directories.
- The system tray is based on the [suckless systray patch](https://dwm.suckless.org/patches/systray/), adapted to the current Luke DWM status bar, window swallowing, and restart behavior.
- Pinned download sources for Oh My Zsh, zsh-autosuggestions, zsh-syntax-highlighting, Starship, fastfetch, and Nerd Fonts are listed in [scripts/downloads.json](scripts/downloads.json). The installer retrieves them from their official repositories; their upstream licenses apply.
- The wallpaper comes from Luke Smith's voidrice repository and depicts Thomas Thiemeyer's *Road to Samarkand*. The original attribution is preserved. This project does not claim authorship or grant a new license for the artwork.
- Ubuntu packages are installed from the configured repositories and remain subject to their respective licenses.
- The Teams launcher opens Microsoft's official website and does not distribute the Teams application. Its icon comes from Papirus; copyright information and the GPL-3 license are included in `payload/home/.local/share/larbs-ubuntu/licenses/teams-icon/`.
- FortiClient is an optional Fortinet VPN-only client downloaded from the official filestore HTTPS endpoint and checked against a pinned SHA-256 hash. This repository does not redistribute the proprietary installer or user VPN configuration.
- The hibernation module generates GRUB/initramfs settings for the destination machine. References: the Linux kernel's [platform hibernation documentation](https://docs.kernel.org/power/basic-pm-debugging.html) and [USB power management documentation](https://docs.kernel.org/driver-api/usb/power-management.html). Actual hardware power-off and wake behavior still require testing.

Supported releases are based on the [official Ubuntu release list](https://ubuntu.com/project/docs/release-team/list-of-releases/). Dependency and architecture checks target Ubuntu Desktop 24.04 and 26.04; this does not imply validation on every hardware configuration.

The installation, backup, and test scripts written for this repository are licensed under the MIT License:

Copyright (c) 2026 ubuntu-dwm-setup contributors

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in
all copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN
THE SOFTWARE.
