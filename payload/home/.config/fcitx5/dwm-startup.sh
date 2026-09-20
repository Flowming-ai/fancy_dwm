#!/bin/sh
. "$HOME/.config/fcitx5/dwm-env.sh"
if fcitx5-remote --check >/dev/null 2>&1; then
    fcitx5-remote --check -x >/dev/null 2>&1 || :
else
    fcitx_state="${XDG_STATE_HOME:-$HOME/.local/state}/fcitx5"
    mkdir -p "$fcitx_state"
    fcitx5 -d >>"$fcitx_state/dwm.log" 2>&1 &
    attempt=0
    while [ "$attempt" -lt 30 ]; do
        fcitx5-remote --check >/dev/null 2>&1 && break
        sleep 0.1
        attempt=$((attempt + 1))
    done
fi
