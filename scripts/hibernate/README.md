# Portable hibernation module

Run a read-only eligibility check from the repository:

```sh
python3 scripts/hibernate/configure.py --check
python3 scripts/hibernate/configure.py --check --json
```

An eligible result describes a supported layout, not a successful physical
sleep/resume test. Checks need no sudo and do not write files. Errors, including
unreadable boot metadata, are returned in the report instead of a traceback.
An unreadable final polkit rule is reported and deferred to the mandatory root
preflight; its directory ancestors are still checked before reporting eligibility.

To configure an eligible host, use a regular Ubuntu administrator account:

```sh
sudo python3 scripts/hibernate/configure.py --apply --user "$(id -un)"
```

The script targets Ubuntu 24.04/26.04 with GRUB and an unencrypted ext4 root on a
plain block device. It refuses unsupported filesystems, LVM/RAID/device-mapper,
Secure Boot, kernel lockdown, and conflicting pre-existing resume settings.
It neither disables Secure Boot nor changes firmware or device wake policies.
Other layouts need a separately reviewed setup. A newer Ubuntu/kernel version
is not implicitly supported.

The active `update-initramfs` implementation determines whether Dracut or
initramfs-tools is configured. Do not install or replace a boot generator merely
to satisfy this module. Prerequisites are Python 3, util-linux, e2fsprogs, the
existing GRUB tools, `update-initramfs`, and `unmkinitramfs`; Dracut additionally
uses `lsinitrd`. Ubuntu's `initramfs-tools-core` provides `unmkinitramfs`.

A dedicated `/swap-hibernate.img` is sized from RAM (rounded up to GiB, plus
at least 4 GiB or 10% headroom). `--swap-size-gib N` can increase the size, and
`--swap-file /another-swap.img` selects another simple filename directly under
the root filesystem. Existing swaps remain active. The offset is calculated
from FIEMAP and cross-checked using filefrag in native page-size units. Active
swap plus root-owned metadata prevents silently reusing a recreated file.

The module sets `HibernateMode=platform` and `image_size=0`, validates GRUB and
the generated initramfs, and enables hibernation permission only for the named
active local desktop user. It preserves inhibitor checks. A kernel snapshot
still needs RAM, and swap can fill during normal operation. NVIDIA systems also
require correctly configured vendor hibernate/resume services, video-memory
preservation, and sufficient disk-backed temporary storage; these driver
settings are reported, not replaced. USB keyboard/mouse wake requires firmware
support and standby power. No software check guarantees all lights go dark.

The script never invokes hibernate, suspend, shutdown, or reboot. Save work and
reboot normally after the first installation, then run `dwm-hibernate --check`.
The desktop helper verifies loaded resume parameters, the running/next kernel,
swap identity, and logind capability before offering a confirmation menu. It
rechecks immediately before requesting hibernation. Test actual shutdown and
resume when you can observe the machine. A static READY result is not proof of
hardware compatibility.

Automatic checking assumes Ubuntu's default `GRUB_DEFAULT=0`; saved, named,
or other numbered defaults are refused without executing GRUB configuration.
After hibernation, use that default boot entry. A manual one-time GRUB entry
selection can choose a different kernel and is outside this guard's guarantee.

Root-owned backups under `/var/backups/dwm-hibernate/portable-*` contain all
modified config and boot image files plus an independent `rollback.py`. Preview
with `sudo python3 /var/backups/dwm-hibernate/portable-.../rollback.py`, or add
`--apply` to restore. Failed installation automatically invokes this rollback.
Neither rollback nor setup performs swapoff or deletes the new swap, to avoid
exhausting RAM. If a failed attempt left a valid active swap, the backup's
`retained-swap.json` contains its inode and offset; after review, pass
`--reuse-swap INODE OFFSET` to reuse that exact file without formatting it.
Incomplete/inactive files require manual review.

An existing valid `/var/lib/dwm-hibernate/config.json`, including the earlier
local installer format, is verified without overwriting settings or resizing
swap. Legacy settings that differ from platform plus the per-hibernate minimal
image are explicitly reported and preserved; this path does not claim to have
applied those policies. For state created by this module, a changed effective
policy blocks reapplication pending review. Rollback for this module is
separate from desktop configuration rollback.

## Optional memory preparation for snapshot allocation failures

If the journal reports `Error -12 creating image` or `Cannot allocate memory`,
free swap alone does not prove that enough RAM exists for the temporary copy.
The optional guard below prepares memory **before** NVIDIA switches VTs or
systemd begins the sleep operation. It requires an existing hibernation setup,
a cgroup v2 user slice, and Linux 6.12 or newer. It is not installed automatically
on unrelated machines.

```sh
python3 scripts/hibernate/install-memory-guard.py --user "$(id -un)"
sudo python3 scripts/hibernate/install-memory-guard.py --apply --user "$(id -un)"
```

The first command is a read-only preview. The second installs a root-owned
helper and required, ordered systemd dependencies. It does not initiate sleep,
reboot, or memory reclaim. Its default target is 67% available physical memory;
this is a conservative mitigation based on one machine's successful versus
failed cycles, not a prediction of the kernel image size. Optional
`--available-percent 50..80` and `--max-reclaim-gib 1..16` tune the policy.

At each plain hibernation attempt, it requests reclaim from `user.slice` in
chunks of at most 256 MiB, for at most 45 seconds and 10 GiB of cumulative
requests. The kernel may reclaim more or less than requested. It rechecks RAM
and **the dedicated hibernation swap's** free space after each request. A swap
reserve of half physical RAM plus 2 GiB is retained. Busy applications can
refault pages; failure to reach the threshold cancels hibernation before GPU
preparation and displays a notification. No applications are terminated, no
user processes are frozen, and no persistent memory limits are changed. This
may add disk activity and make subsequent application access briefly slower.

For NVIDIA, installation checks the vendor VT marker contract and adds a
condition to avoid calling the resume unit when no GPU preparation occurred.
The vendor post-sleep hook remains intact. Review/reapply this optional module
after changes to NVIDIA's sleep scripts. Suspend-to-RAM and
suspend-then-hibernate are outside this guard's scope.

Read-only inspection and a **memory-only** preparation test:

```sh
python3 /usr/local/libexec/dwm-hibernate-memory --check
sudo systemctl start dwm-hibernate-memory.service
journalctl -u dwm-hibernate-memory.service -b --no-pager
cat /run/dwm-hibernate-memory.json
```

Starting this guard by itself does not start the hibernation or NVIDIA units.
The service does not retain an active success state: each later sleep attempt
runs fresh checks. Passing preparation is not proof of a successful physical
power-off/resume cycle or of graphics-driver compatibility. Save work before
a real test. The installer prints an independent rollback command under
`/var/backups/dwm-hibernate/portable-*`; it restores the previous hooks and
helper without changing swap layout or starting any power operation.

Implementation references: [kernel memory.reclaim interface](https://docs.kernel.org/admin-guide/cgroup-v2.html#memory-interface-files),
[Linux snapshot allocation](https://github.com/torvalds/linux/blob/v7.0/kernel/power/snapshot.c),
and [systemd dependency semantics](https://www.freedesktop.org/software/systemd/man/latest/systemd.unit.html).
