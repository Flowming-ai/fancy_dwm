# Luke / LARBS Ubuntu adaptation

This package is used by the adjacent install-larbs-ubuntu.sh installer. It contains the pinned sources, curated user configuration, and DWM session launcher. See SOURCES.txt and the preserved source licenses.

## DWM system tray update

DWM includes an XEmbed system tray on the geometrically rightmost monitor. It shares the bar with dwmblocks without covering status text. Tray icons are application-provided notification icons, not a list of every open window. StatusNotifier-only applications may need a bridge.

The tray follows the host bar visibility and preserves existing client windows during Super+Shift+Backspace restart. The complete installer includes the same tray sources as dwm-systray.tar.gz.

Validation: Xvfb single-screen and simulated Xinerama dual-screen tests passed, covering focus on either monitor, fixed tray placement, bar hide/show, icon resize/remove, and restart. Real Flameshot and Fcitx5 Classic UI XEmbed icons docked and returned after restart. The isolated Fcitx test loaded X11/Classic UI addons only; Chinese input and physical display hotplug were not tested by these checks.

Upstream tray patch: https://dwm.suckless.org/patches/systray/
