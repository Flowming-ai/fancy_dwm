#!/bin/sh
export GTK_IM_MODULE=fcitx
export QT_IM_MODULE=fcitx
export XMODIFIERS=@im=fcitx
# Kitty talks to Fcitx5 through its IBus-compatible frontend.
export GLFW_IM_MODULE=ibus
