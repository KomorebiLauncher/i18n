# KomorebiLauncher 翻译源

Komorebi Launcher 的启动器界面翻译仓库，供启动器在运行时下载语言包使用。产出站点：
https://komorebilauncher.github.io/i18n/ ，启动器读取的入口是其中的 index_v2.json 。

本仓库是 [PrismLauncher/Translations](https://github.com/PrismLauncher/Translations) 的 fork，
翻译内容本身由 [Hosted Weblate](https://hosted.weblate.org/projects/prismlauncher/launcher/) 维护，
授权为 Apache License 2.0，见 LICENSE 。

## 与上游的差异

- 构建脚本允许单个语言的 msgfmt 校验失败，只记录统计数字而不中断整批构建，一门语言有问题不会让其余一百种语言发不出去。
- 没有 .github/CNAME ，站点由 GitHub Pages 的项目地址提供。
- update.yml 已停用，因为它需要上游的 weblate 凭据。同步上游改动请使用 git merge 或仓库页面上的 Sync fork 。

## 目录与产物

仓库里是各语言的 .ts 文件（Qt 翻译源格式）。本地克隆请用 git clone --depth 1 ：完整历史约 1.3 GB，
是上游 Weblate 长期自动提交堆出来的，而工作区只有 73 MB。历史本身要保留——它是与上游翻译仓库做
git merge 的唯一锚点，删掉之后每次同步上游都得手工比对一百多个文件。

构建流程为：每个 .ts 先用 lconvert 转出 .po 以便统计，
再用 lrelease 编译成 .qm，然后以该 .qm 自身的 sha1 作为文件名复制一份并加上 .class 后缀，
同时写出 index_v2.json 记录每种语言的文件名、sha1、大小与已译、模糊、未译数量。

启动器会校验下载文件的 sha1，所以文件名与索引必须一致。

## 本地重建

安装 Qt 的 lconvert 、 lrelease 、lupdate 与 gettext 的 msgfmt 后执行：

    nix develop . -c ./release.sh

或者不用 nix，直接：

    ./release.sh

产物出现在 build 目录。日常发布不需要本地跑，但见下一节：推送不会自动发布。

## 发布注意事项

**推送不会触发 Build Pages。** 实测 2026-10-22：直接 git push 一个改过的 zh.ts 到 master，远端提交已更新，
但 Actions 里没有任何对应的运行记录；用 GitHub 的 Contents API 提交同样没有。所以工作流虽然写了
push 触发条件，实际不能指望它。

每次改完 .ts 之后必须做两件事：手动执行一次 workflow_dispatch，然后确认站点上的
index_v2.json 里该语言的 sha1 与 translated 数量已经变化。少了这一步，站点会停留在旧内容上，
而旧文件的 sha1 仍然自洽，启动器不会报任何错——看起来就像"翻译没生效"。
