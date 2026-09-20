#!/bin/sh
# Build only in a temporary directory; never install or restart a desktop.
set -eu
root=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
stage=$(mktemp -d "${TMPDIR:-/tmp}/ubuntu-dwm-build.XXXXXX")
trap 'rm -rf -- "$stage"' EXIT HUP INT TERM
cp -R "$root/payload/src" "$stage/src"
for project in dwm st dmenu dwmblocks; do
    make -C "$stage/src/$project" clean
    make -C "$stage/src/$project" -j"$(getconf _NPROCESSORS_ONLN)"
done
tic -c -x "$stage/src/st/st.info"
for program in dwm/dwm st/st dmenu/dmenu dmenu/stest dwmblocks/dwmblocks; do
    if ldd "$stage/src/$program" | grep -q 'not found'; then
        printf 'Missing runtime library: %s\n' "$program" >&2
        exit 1
    fi
done
printf '\nDWM、st、dmenu、dwmblocks 编译与动态库检查通过；未安装。\n'
