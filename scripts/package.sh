#!/bin/sh
# Export the committed portable setup and its Git history; do not install it.
set -eu
root=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd -P)
[ "$#" -le 1 ] || { echo 'Usage: sh scripts/package.sh [OUTPUT_DIRECTORY]' >&2; exit 2; }
[ -z "$(git -C "$root" status --porcelain)" ] || { echo 'Commit all intended changes before packaging.' >&2; exit 1; }
python3 "$root/scripts/verify.py"
destination=${1:-"$root/../outputs"}
mkdir -p "$destination"
destination=$(CDPATH= cd -- "$destination" && pwd -P)
case "$destination/" in "$root/"*) echo 'Choose an output directory outside the repository.' >&2; exit 1;; esac
stage=$(mktemp -d "$destination/.dwm-package.XXXXXXXX")
trap 'rm -rf -- "$stage"' EXIT HUP INT TERM
git -C "$root" archive --format=tar.gz --prefix=ubuntu-dwm-setup/ -o "$stage/ubuntu-dwm-setup.tar.gz" HEAD
git -C "$root" bundle create "$stage/ubuntu-dwm-setup.bundle" --all
git -C "$root" bundle verify "$stage/ubuntu-dwm-setup.bundle"
(
    cd "$stage"
    sha256sum ubuntu-dwm-setup.tar.gz >ubuntu-dwm-setup.tar.gz.sha256
    sha256sum ubuntu-dwm-setup.bundle >ubuntu-dwm-setup.bundle.sha256
)
for name in ubuntu-dwm-setup.tar.gz ubuntu-dwm-setup.bundle ubuntu-dwm-setup.tar.gz.sha256 ubuntu-dwm-setup.bundle.sha256; do
    mv -f -- "$stage/$name" "$destination/$name"
done
printf 'Exported commit %s to %s\n' "$(git -C "$root" rev-parse --short HEAD)" "$destination"
