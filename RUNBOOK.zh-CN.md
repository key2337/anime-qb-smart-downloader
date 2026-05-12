# anime-qb-smart-downloader 运行工具书

这是一份面向实际操作的中文手册，目标是让你从零开始把项目跑起来，并知道每个命令会做什么。

项目作用很明确：

1. 从你配置的 RSS 源拉取动画发布信息。
2. 解析标题里的集数、字幕、分辨率、字幕组等元数据。
3. 按 `config.yaml` 里的规则筛选并打分。
4. 把每一集得分最高的候选项提交给 qBittorrent Web API。
5. 把下载任务、候选历史和已完成记录写入本地 SQLite。

注意：当前版本已经能“自动筛选并提交下载”，但“自动切换备用种子”还没有完整实现，只会先把可疑任务标记为 `fallback_pending`。

## 1. 项目结构怎么理解

你最常接触的是这几个文件：

- `config.example.yaml`：完整示例配置。
- `config.minimal.yaml`：最小配置模板。
- `config.yaml`：你本机实际使用的配置文件，需要你自己创建。
- `src/aqsd/main.py`：CLI 入口，安装后命令名是 `aqsd`。
- `data/app.db`：程序首次运行后自动创建的 SQLite 数据库。

## 2. 运行前准备

### 2.1 必要条件

- Python 3.11 或更高版本
- 一台可访问的 qBittorrent，并且开启了 Web UI
- 至少一个可访问的动漫 RSS 源

### 2.2 建议的目录状态

在项目根目录下操作：

```powershell
cd F:\a_课件\anime-qb-smart-downloader
```

## 3. 安装步骤

### 3.1 创建虚拟环境

```powershell
python -m venv .venv
```

### 3.2 激活虚拟环境

```powershell
.venv\Scripts\Activate.ps1
```

如果 PowerShell 拒绝执行脚本，可以先在当前终端放宽策略：

```powershell
Set-ExecutionPolicy -Scope Process Bypass
```

然后再执行激活命令。

### 3.3 安装项目

```powershell
pip install -e .
```

安装完成后，命令行里会有一个可执行命令：

```powershell
aqsd
```

你也可以用等价方式运行：

```powershell
python -m aqsd.main
```

## 4. qBittorrent 需要怎么设置

这个项目不是直接把磁力发给桌面程序，而是调用 qBittorrent 的 Web API，所以 Web UI 必须先开好。

在 qBittorrent 里设置：

1. 打开 `Tools -> Options -> Web UI`
2. 勾选 `Web User Interface (Remote control)`
3. 设置监听地址和端口，例如 `127.0.0.1:8080`
4. 设置用户名和密码
5. 确认运行本项目的机器能访问这个地址

如果你本机和 qBittorrent 在同一台机器上，通常 `http://127.0.0.1:8080` 最直接。

## 5. 配置文件怎么写

### 5.1 先复制一份本地配置

```powershell
Copy-Item config.example.yaml config.yaml
```

项目默认读取根目录下的 `config.yaml`。如果你想使用别的文件名，可以通过 `--config` 指定。

### 5.2 一个可运行的最小配置

先从最小可用配置开始最稳妥：

```yaml
app:
  database: "./data/app.db"
  log_level: "INFO"

qbittorrent:
  base_url: "http://127.0.0.1:8080"
  username: "你的qB用户名"
  password: "你的qB密码"

rss_sources:
  - name: "mikan"
    url: "这里换成你真实可用的RSS地址"
    enabled: true

profiles: {}
anime: []
```

这份配置能用于连通性检查，但还不能自动下载任何番剧，因为 `anime` 规则还是空的。

### 5.3 配置项逐段解释

#### `app`

```yaml
app:
  database: "./data/app.db"
  interval_seconds: 300
  log_level: "INFO"
```

- `database`：SQLite 数据库路径。首次运行会自动创建目录和库文件。
- `interval_seconds`：守护模式轮询间隔，单位秒。
- `log_level`：日志级别，常用 `INFO` 或 `DEBUG`。

#### `qbittorrent`

```yaml
qbittorrent:
  base_url: "http://127.0.0.1:8080"
  username: "change-me"
  password: "change-me"
  default_category: "Anime"
  default_save_path: "/downloads/anime"
```

- `base_url`：qB Web UI 地址。
- `username` / `password`：qB Web UI 登录凭据。
- `default_category`：默认分类。
- `default_save_path`：默认保存目录。

注意：`default_category` 和 `default_save_path` 只是默认值。真正提交下载时，单个番剧规则可以覆盖它们。

#### `rss_sources`

```yaml
rss_sources:
  - name: "mikan"
    url: "https://example.com/rss.xml"
    enabled: true
```

- `name`：来源名字，只用于日志和识别。
- `url`：RSS 地址，必须是可访问且可解析的真实链接。
- `enabled`：是否启用。

可以配置多个 RSS 源，程序会拉取所有启用项。

#### `fallback_policy`

```yaml
fallback_policy:
  enabled: true
  check_after_minutes: 10
  min_download_speed_kbps: 100
  min_progress_delta: 0.001
  max_retry_candidates: 5
  delete_failed_torrent: true
```

当前版本的现实含义是：

- 会监控下载状态。
- 如果发现速度过低、无做种、进度几乎不动，会把任务标记成可疑。
- 但不会自动完整切换到备用候选项。

所以这一段先保留默认值即可，不要把它理解成“已经有完整自动补种”。

#### `profiles`

`profiles` 是复用规则模板。番剧条目可以通过 `profile` 引用它。

示例：

```yaml
profiles:
  fastest:
    prefer:
      resolution: ["1080p", "2160p", "720p"]
      subtitle: "any"
    allow_fallback: true
```

你可以把它理解成“公共偏好设置”。

#### `anime`

`anime` 是最关键的部分，决定哪些番剧会被匹配、筛选和提交下载。

示例：

```yaml
anime:
  - name: "Example Anime"
    aliases:
      - "Example"
      - "Example Anime S1"
    profile: "fastest"
    include:
      - "1080p"
    reject:
      - "Batch"
      - "Complete"
    prefer_groups:
      - "LoliHouse"
      - "SubsPlease"
    save_path: "/downloads/anime/Example Anime"
    category: "Anime"
```

字段含义：

- `name`：番剧主名称。
- `aliases`：别名，解决 RSS 标题命名不统一的问题。
- `profile`：引用 `profiles` 中的模板。
- `include`：必须包含的关键词。
- `reject`：命中就排除的关键词。
- `prefer_groups`：更偏好的字幕组。
- `save_path`：这个番剧单独的下载目录。
- `category`：这个番剧单独的 qB 分类。

另外，代码里还支持这两个可选字段：

- `allow_hevc`
- `allow_dual_audio`

如果你后面扩展规则时看到它们，不用奇怪。

## 6. 推荐的首次配置方式

第一次不要一上来就开自动下载，建议按这个顺序：

1. 先填好 `qbittorrent` 和真实 RSS。
2. 先跑 `--check`。
3. 再补一条 `anime` 规则。
4. 再跑 `--dry-run` 看匹配结果。
5. 确认无误后再执行默认下载模式或 `download` 子命令。

## 7. 常用命令怎么用

## 7.1 连通性检查

检查 RSS 和 qB 是否可连，不提交任何下载：

```powershell
aqsd --config config.yaml --check
```

适用场景：

- 想先验证 qB 用户名密码是否正确
- 想确认 RSS 地址能拉到内容
- 配置刚改完，先做冒烟测试

## 7.2 试跑模式

只做 RSS 拉取、解析、匹配和打分，不向 qB 添加任务：

```powershell
aqsd --config config.yaml --dry-run
```

这是最重要的调试命令。你应该优先用它来确认：

- 别名是否能匹配到目标番剧
- `include` / `reject` 是否写对
- 程序是否优先选中了你想要的字幕组和分辨率

注意：当前 `dry-run` 默认只保留“最新一集”的候选项来展示日志。

## 7.3 默认运行一次

如果你直接执行：

```powershell
aqsd --config config.yaml
```

程序会：

1. 拉取启用的 RSS 源
2. 按 `anime` 规则匹配
3. 跳过数据库里已下载或已有任务的集数
4. 对每个“番剧 + 集数”挑分数最高的一项
5. 直接提交到 qBittorrent

这不是预览命令，而是正式下载命令。

## 7.4 持续守护运行

按 `app.interval_seconds` 持续轮询：

```powershell
aqsd --config config.yaml --daemon
```

这个模式会循环做两件事：

1. 执行一次下载发现流程
2. 扫描 qB 里的活动任务并更新状态

适合长期挂机。

## 7.5 手动搜索候选项

只搜索，不下载：

```powershell
aqsd search "Example Anime"
```

常见过滤参数：

```powershell
aqsd search "Example Anime" --episode 01 --resolution 1080p --group LoliHouse --subtitle embedded --min-seeders 5 --limit 10
```

如果要多个集数或多个字幕组，可以重复参数：

```powershell
aqsd search "Example Anime" --episode 01 --episode 02 --group LoliHouse --group SubsPlease
```

只看 RAW：

```powershell
aqsd search "Example Anime" --raw-only
```

返回结果会按表格行输出，字段包括：

- 标题
- 集数
- 分辨率
- 字幕组
- 字幕类型
- 做种数
- 发布时间
- 分数
- 来源

## 7.6 手动下载某一集的最佳候选项

如果你不想让程序按 `anime` 全量规则跑，而是临时手动下某一集，用这个命令：

```powershell
aqsd download "Example Anime" --episode 01 --resolution 1080p --group LoliHouse --subtitle embedded
```

它的行为是：

1. 在已配置的 RSS 源里搜索候选项
2. 按当前搜索过滤条件收敛结果
3. 选择得分最高的一项
4. 立即提交给 qBittorrent
5. 在数据库里写入一条 `submitted` 任务记录

注意：`download` 子命令只会搜索你配置好的 `rss_sources`，不会去外部站点额外检索。

## 8. 一套最稳的实际使用流程

假设你要开始追一部新番，推荐按下面执行：

### 第一步：写配置

```yaml
app:
  database: "./data/app.db"
  interval_seconds: 300
  log_level: "INFO"

qbittorrent:
  base_url: "http://127.0.0.1:8080"
  username: "你的用户名"
  password: "你的密码"
  default_category: "Anime"
  default_save_path: "D:/Downloads/Anime"

rss_sources:
  - name: "mikan"
    url: "你的真实RSS地址"
    enabled: true

profiles:
  fastest:
    prefer:
      resolution: ["1080p", "720p"]
      subtitle: "any"
    allow_fallback: true

anime:
  - name: "某部番剧"
    aliases:
      - "某部番剧 第二季"
      - "某部番剧 S2"
    profile: "fastest"
    include:
      - "1080p"
    reject:
      - "Batch"
      - "Complete"
    prefer_groups:
      - "LoliHouse"
      - "SubsPlease"
    save_path: "D:/Downloads/Anime/某部番剧"
    category: "Anime"
```

### 第二步：检查连接

```powershell
aqsd --check
```

### 第三步：试跑观察

```powershell
aqsd --dry-run
```

如果日志里没有匹配到你要的资源，先改 `aliases`、`include`、`reject`，不要急着正式下载。

### 第四步：正式执行一次

```powershell
aqsd
```

### 第五步：需要长期自动追番时再开守护

```powershell
aqsd --daemon
```

## 9. 数据库和状态怎么理解

程序会自动创建 `data/app.db`，里面最重要的是这些概念：

- `downloaded`：已完成下载的集数
- `candidates`：历史候选项
- `download_tasks`：已提交到 qB 的任务
- `fallback_candidates`：备用候选池
- `task_events`：任务事件日志

当前代码里常见任务状态包括：

- `queued`
- `submitted`
- `downloading`
- `stalled`
- `fallback_pending`
- `fallback_submitted`
- `completed`
- `failed`
- `cancelled`

其中最重要的现实判断是：

- 任务刚提交到 qB 时，状态不是完成，而是 `submitted`
- 只有监控扫描到 qB 下载进度达到 100% 时，才会标记为 `completed`

## 10. 最容易踩的坑

### 10.1 RSS 地址是示例地址

`config.example.yaml` 里的 RSS URL 是占位符，不可直接使用。你必须换成真实可用链接。

### 10.2 默认运行会真的下种

`aqsd` 或 `aqsd --config config.yaml` 不是预览，而是正式提交下载。第一次务必先跑 `--dry-run`。

### 10.3 `anime` 为空时不会自动匹配任何番剧

即使 RSS 和 qB 都配置正确，如果 `anime: []`，默认下载流程也不会找到要下的内容。

### 10.4 `download` 子命令不会联网搜站

它只在你配置的 RSS 源结果里挑候选项。

### 10.5 备用种子不是全自动切换

当前实现会检测可疑任务并记录备用候选池，但自动 fallback 逻辑还没完整做完。

### 10.6 Windows 路径建议统一写法

在 YAML 里建议这样写路径，避免转义问题：

```yaml
default_save_path: "D:/Downloads/Anime"
save_path: "D:/Downloads/Anime/某部番剧"
```

比起反斜杠，正斜杠更省事。

## 11. 典型排障方法

### 情况 1：`--check` 失败

优先检查：

- `qbittorrent.base_url` 是否能在浏览器打开
- qB Web UI 是否真的启用
- 用户名密码是否正确
- RSS 地址是否能访问

### 情况 2：`--dry-run` 没有候选项

优先检查：

- RSS 源里是否真的有这部番
- `aliases` 是否覆盖了 RSS 里的命名方式
- `include` 是否过严
- `reject` 是否误杀
- 是否用了过严的 profile 偏好

### 情况 3：`aqsd` 没有提交任何下载

优先检查：

- 数据库是否已经把该集记为已下载或已有任务
- `anime` 规则是否能匹配到候选项
- 候选项是否都被过滤掉了

### 情况 4：qB 里有任务，但项目状态没完成

先确认：

- 你是否在运行 `--daemon`
- 或者你是否有定期执行默认流程来触发监控扫描

因为任务完成状态依赖监控层读取 qB 的进度。

## 12. 测试命令

如果你想确认当前代码库本身是否正常，可以运行测试：

```powershell
pytest
```

或者：

```powershell
python -m unittest discover -s tests -v
```

## 13. 最短上手清单

如果你只想快速开始，照这 6 步做：

1. `python -m venv .venv`
2. `.venv\Scripts\Activate.ps1`
3. `pip install -e .`
4. `Copy-Item config.example.yaml config.yaml`
5. 把 `config.yaml` 里的 qB 账号和 RSS 地址改成真实值，并添加至少一条 `anime` 规则
6. 依次执行 `aqsd --check`、`aqsd --dry-run`、`aqsd`

## 14. 结论

这个项目当前最适合的使用方式是：

- 用 `config.yaml` 维护追番规则
- 用 `--check` 做连通性确认
- 用 `--dry-run` 调规则
- 用默认模式或 `--daemon` 做正式下载

如果你后面愿意，我可以继续基于这份手册，直接帮你生成一份“适合你当前环境的可用 `config.yaml` 模板”。
