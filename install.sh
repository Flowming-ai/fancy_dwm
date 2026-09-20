#!/bin/sh
# POSIX entry point: both ./install.sh and sh install.sh are supported.
set -eu
installer_dir=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd -P)
if ! command -v bash >/dev/null 2>&1; then
    printf '%s\n' 'Bash is required (included with supported Ubuntu Desktop releases).' >&2
    exit 1
fi
exec bash "$installer_dir/scripts/install-main.sh" "$@"
