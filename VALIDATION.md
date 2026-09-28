# Configuration integration validation: 2026-09-28

The build host was Ubuntu 26.04 amd64. This update changed the repository and distribution artifacts only. The full installer was not used to reinstall the current desktop, modify its boot configuration, or trigger hibernation. GitHub CLI was installed separately to push the repository using device authorization approved by the user.

## Completed checks

- All 86 automated tests passed, using temporary directories, fixtures, or mocked commands. The tests did not execute real sudo, APT installation, or hibernation commands.
- New coverage includes 150% and alternative scaling values, preservation of personal GTK/Xresources settings, removal of duplicate legacy startup blocks, Teams launcher path escaping and browser selection, rejection of FortiClient hash mismatches, and preservation of installed versions without automatic upgrades or downgrades.
- Hibernation tests cover RAM-based swap sizing, FIEMAP and filefrag offsets, rejection of unsupported storage layouts, Dracut/initramfs-tools resume paths, GRUB parameters across installed kernels, rejection of custom GRUB defaults, rollback scope, read-only checks as root, and Python 3.12 permission handling for polkit paths.
- Desktop hibernation helper tests cover swap-file identity and permissions, running and next-boot kernel versions, incorrect or duplicate resume parameters, noresume, checks before and after confirmation, and cancellation without hibernating.
- DWM, st, dmenu, and dwmblocks were rebuilt in temporary directories. Dynamic-library and terminfo checks passed. Only the existing unused termcmd warning remained.
- Syntax checks passed for 40 Shell/Python files, and git diff --check passed.
- The new hibernation module passed a read-only check on the host and correctly recognized its existing configuration. The menu helper's static check reported READY.
- An HTTP HEAD request to the official FortiClient download URL succeeded. The local package's SHA-256, name, architecture, and version matched the pinned download manifest.
- The configuration snapshot contains no real home-directory paths, root-filesystem UUIDs, fixed resume offsets, VPN account data, or authentication credentials from the source machine.

## Scope of testing

The complete installer was not run in a fresh Ubuntu 24.04/26.04 virtual machine or on an ARM device, and no new hardware hibernation cycle was performed. Automated tests and static checks cannot establish power-off and resume compatibility for every motherboard, USB port, or GPU. Local FortiClient use on Ubuntu 26.04/DWM does not imply vendor certification.

The original desktop snapshot's validation record is preserved below as background for existing code. It does not imply that every earlier check was repeated for this update.

# Original desktop snapshot validation: 2026-09-21

Validation date: 2026-09-21. Build host: Ubuntu 26.04 amd64.

## Completed checks

- DWM, st, dmenu, and dwmblocks compiled successfully in temporary directories, with no missing dynamic libraries. The st terminfo check passed. DWM retained the existing upstream warning for an unused `termcmd` variable.
- APT installation was simulated using an empty installed-package database against both the official Ubuntu 24.04 main/universe indexes and the host's 26.04 indexes. Core dependencies and available GTK/Qt frontends resolved successfully. These were simulations, not actual installations.
- Pinned font, Starship, and fastfetch archives for amd64/arm64 were downloaded and verified. Version commands ran successfully for amd64 binaries. ARM binaries were checked for their ELF architecture only and were not run on ARM hardware.
- The installer's asset preparation step ran successfully, including SHA-256 checks, font extraction, and retrieval of three plugin repositories at fixed commits.
- Configuration and assets were installed in a temporary home directory, then loaded by a real Zsh process. Oh My Zsh, autosuggestions, syntax highlighting, Starship, eza/bat aliases, and input-method environment variables loaded successfully.
- User-configuration tests covered fresh and repeated installation, legacy configuration migration, preservation of the first backup, personal settings and dictionaries, Pinyin groups, shortcut conflicts, and symlink handling.
- Default-session and rollback tests used a mocked AccountsService API and temporary files, covering old and new APIs, backups, path restrictions, and safe restoration.
- Shell/Python syntax checks, read-only package integrity checks, and verification of the installer entry point after archive extraction all passed.

The included system tray code retains the results of earlier independent Xvfb checks: a single screen, simulated dual screens, icon resizing and hiding, DWM restarts, and docking/restoration of real Flameshot and Fcitx5 Classic UI icons.

## Scope of testing

The complete sudo/APT installation was not run in a fresh virtual machine. Actual ARM desktop operation, physical monitor hotplugging, and every graphics driver were not tested. Tray-icon tests do not establish Chinese input functionality in every application.

The current desktop was not reinstalled or restarted while preparing this repository. Run the installer in a regular terminal on the destination Ubuntu computer. Environments restricted by `NoNewPrivs` exit before installation begins.
