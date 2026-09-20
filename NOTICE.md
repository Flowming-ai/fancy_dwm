# 来源与许可证

此仓库是当前 Ubuntu 桌面的可迁移配置快照，包含经过适配的第三方源码。

- DWM、st、dmenu、dwmblocks 的原始提交列于 [payload/SOURCES.txt](payload/SOURCES.txt)，许可证分别保留在各源码目录中。
- 系统托盘协议参考 [suckless systray 补丁](https://dwm.suckless.org/patches/systray/)，已适配当前 Luke DWM 的状态栏、窗口吞并和重载行为。
- Oh My Zsh、zsh-autosuggestions、zsh-syntax-highlighting、Starship、fastfetch 与 Nerd Fonts 的固定下载来源见 [scripts/downloads.json](scripts/downloads.json)。安装时从官方仓库获取，各自适用上游许可证。
- 当前壁纸取自 Luke Smith voidrice，作品为 Thomas Thiemeyer 的 *Road to Samarkand*；保留原来源说明，不将它声明为本项目原创或授予新的作品许可。
- Ubuntu 软件包由已配置的软件源安装，适用各包自身许可证。

支持版本以 [Ubuntu 官方发行列表](https://ubuntu.com/project/docs/release-team/list-of-releases/) 为参考。这里只针对 Ubuntu Desktop 24.04 与 26.04 设置依赖与架构检查，不代表在所有硬件上完成了验证。

本仓库新编写的安装、备份与测试脚本使用 MIT 许可证：

Copyright (c) 2026 ubuntu-dwm-setup contributors

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in
all copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN
THE SOFTWARE.
