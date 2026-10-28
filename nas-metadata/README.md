# 远程绿联 NAS：一次性读取视频元数据

目标是在 NAS 本机读取《Hacks》五季的视频信息，只下载小型结果目录回 Mac。无需把 NAS 挂载到 Mac，也无需传输完整视频。

## 使用现有绿联远程连接

绿联官方说明：Mac 客户端可使用 UGREENlink 远程访问；Docker 提供容器详情中的“终端”和“项目”Compose 配置。这里优先使用一次性 Compose 任务，执行完退出，不依赖持续打开的交互终端。

- [UGREENlink 远程访问](https://support.ugnas.com/detail/article/zh-CN/86)
- [Docker 容器终端与项目入口](https://support.ugnas.com/detail/article/zh-CN/236)
- [Docker 项目 Compose 指南](https://support.ugnas.com/knowledgecenter/detail/article/zh-CN/411)

“控制面板 → 终端机”是 SSH 服务开关，不等于内置命令行窗口。UGREENlink 登录成功也不代表 `ssh` 可以直接连接该地址。本方案不需要开启 SSH 或配置路由器端口转发。

## 需要准备的三个 NAS 目录

通过绿联文件管理操作：

1. 已有的《Hacks》五季总目录，之后只读挂载到容器 `/media`。不要选整个存储池或其他私人资料目录。
2. 新建一个工具目录，将本仓库 `collect-media-info.sh` 上传进去，之后只读挂载到 `/scripts`。
3. 新建独立的空输出目录，之后读写挂载到 `/output`。

Compose 中的 `source` 是 NAS 上的真实文件系统路径，不是 Mac 路径、UG.link 地址或文件分享链接。可通过绿联文件夹属性及 Docker 的路径选择器核对；不要照抄猜测的 `/volume1/...`。路径不明时先定位目录，不部署模板占位路径。

## 在 Docker 中运行

1. 打开 **Docker → 项目 → 创建**，输入项目名，例如 `hacks-metadata`。
2. 粘贴 `compose.template.yaml` 内容，将三个 `source: /REPLACE_WITH_...` 改成对应实际路径。保留只读挂载与网络限制。
3. 模板使用 LinuxServer 维护的 `lscr.io/linuxserver/ffmpeg:latest`，不是 FFmpeg 项目官方镜像。[维护者说明](https://docs.linuxserver.io/images/docker-ffmpeg/)及[Dockerfile](https://github.com/linuxserver/docker-ffmpeg/blob/master/Dockerfile)显示提供 ffprobe；模板覆盖镜像默认入口，用 Bash 执行脚本。实际运行前核对来源，记录本次拉取的镜像 ID/digest；`latest` 可变，需要复现时应改成当次已核验的 digest。
4. 部署后查看容器日志。正常完成会打印 `Result directory`、文件数和失败数，然后容器退出；一次性任务处于“已停止/Exited (0)”是预期结果。
5. 通过绿联文件管理下载输出目录里的整个 `hacks-metadata-日期-随机串` 文件夹，放到 Mac 工作目录。不要只取某一集 JSON；`files.nul` 保留失败条目与原文件名的对应关系。

执行容器设置了 `network_mode: none`。Docker 服务拉取镜像本身仍需要 NAS 联网；采集进程运行时没有网络连接。视频目录和脚本目录只读，输出目录可写；不挂载宿主根目录或 Docker socket、不映射端口、不启用 privileged。容器仍受宿主 Docker 管理，不代表绝对安全；这些配置将任务范围限制在所选媒体及输出目录。

若出现 `Permission denied`，先核对这三个目录的权限；不要通过开启特权、挂载宿主根目录或给整个存储池设置全员可写解决。可以在核对 NAS 权限后，为容器指定已有且有权限的 UID/GID。

## 输出是什么

```text
hacks-metadata-.../
  ffprobe-version.txt
  files.nul                 按顺序记录扫描文件；NUL 分隔
  summary.txt               文件数和失败数
  probes/
    0001.json               第1个文件的 ffprobe JSON
    0001.status.txt
    0001.stderr.txt
    0002.json
    ...
```

JSON 包含文件名、容器/流时长、起始时间、帧率、编码、分辨率、音轨、字幕轨及已有章节信息。媒体时长的准确性受原文件元数据和封装影响；如有异常需进一步分析，不能把每个 `duration` 都当成经过解码测量的真值。

脚本只运行 ffprobe，不转码、不改名、不写入视频。单个文件读取失败会记录错误并继续；发现失败或没有视频时最终返回非零退出码。每次运行创建独立结果目录，不覆盖上一次结果。

**总时长信息仍不足以精确推导每个 B 站分 P 的重叠/删减区间。** 本步骤先建立 NAS 原片清单，后续根据实际字幕、片段或其他可比对锚点确定时间映射。

输出中可能包含私人文件名、媒体标签和容器内路径；留在本机分析，不推送到公开 Git 仓库。若原视频旁有外置字幕，后续可单独选取相关字幕作对齐依据，不扫描其他目录。

## 现有其他终端也可用

如果以后已有安全的 NAS 终端且安装了 Bash、ffprobe，可以直接运行：

```bash
bash collect-media-info.sh '/实际Hacks目录' '/实际输出目录'
```

此直接运行方式不自动施加容器的只读挂载和网络隔离；脚本本身没有修改视频或联网的命令。输出目录必须预先存在。

## 验证范围

本地可验证 Bash 语法与脚本的文件名处理、错误处理和输出格式。当前 Mac 未安装 Docker/ffprobe，尚未在用户 NAS 上部署，也未实际验证所选镜像和 UGOS 版本的运行兼容性；应以一次实际运行及日志为准。
