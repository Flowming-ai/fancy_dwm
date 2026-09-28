Desktop integration notes
=========================

`payload/desktop-extras.py` exposes `configure(read, plan, home, percent=150)`.
It only plans configuration: it does not write to the host, call applications,
or start a settings daemon. `apply-user.py` supplies the existing safe callbacks
so every merged file uses the installer's preflight and rollback manifest.
It retires the old DWM scale and XScreenSaver login blocks together; the caller must not overwrite this planned .xprofile using the original content.

The installer provides xsettingsd from Ubuntu's packages and accepts 100, 125,
150, 175, or 200 percent scaling. No monitor names, positions, EDID, display
resolution, extracted binaries, or user browser profiles are included.

At DWM login, `dwm-scale-apply` merges X resources and starts the packaged
xsettingsd only when no settings manager owns that X screen. Its lock and PID
are per display; SIGHUP is sent only after checking the PID's owner, complete
command line and DISPLAY. The session's ordinary DWM reload remains unchanged.
Existing applications may require reopening to pick up font/DPI changes.

The Teams launcher chooses an installed Chrome, Edge, or Chromium at launch.
With only Firefox or xdg-open it displays a fallback notice and opens a normal
browser window. It installs no browser and does not sign in or connect an
account. The bundled icon is an unmodified Papirus SVG, with its copyright and
GPL-3 license in `payload/home/.local/share/larbs-ubuntu/licenses/teams-icon/`.

Tests: `python3 -m unittest discover -s tests -p test_desktop_extras.py -v`.
All test homes, browser commands, and XSETTINGS ownership are temporary or
mocked; tests do not open the real display or launch a real browser.
