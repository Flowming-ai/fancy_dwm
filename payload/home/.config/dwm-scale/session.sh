#!/bin/sh
# One Xft DPI source; no additional QT_SCALE_FACTOR or GDK_SCALE multiplier.
export QT_SCALE_FACTOR_ROUNDING_POLICY=PassThrough
if [ -n "${DISPLAY:-}" ] && [ "${XDG_SESSION_TYPE:-}" != wayland ]; then
    "$HOME/.local/bin/dwm-scale-apply" || :
fi
