# AQSD — Anime QB Smart Downloader

## 目标

一个完整的动漫下载管家，基于 qBittorrent + RSS（动漫花园）实现精准的动漫资源自动下载。

## 核心能力

### 1. 精准搜索与匹配
- 输入中文标题，从 dmhy（动漫花园）RSS 搜索匹配资源
- 支持按集数、分辨率、字幕类型（内嵌/外挂/RAW）、字幕组过滤
- 支持单集/合集/不限三种资源类型
- 标题解析器自动提取结构化信息（集数、分辨率、字幕组、字幕类型、季度等）

### 2. 智能评分与排序
- 多维度评分：做种数、发布时间、字幕组偏好、分辨率偏好、标题匹配度
- 对合集施加惩罚，优先单集资源
- 支持 v2/v3 修订版加分

### 3. 死种应对
- **Probe 机制**：添加多个候选到 qBittorrent，观察速度/可用性后保留最佳
- **Fallback 机制**：监控下载进度，发现死种自动换下一个候选
- 预先评分降低选到死种的概率（高做种数 + 新鲜发布）

### 4. 自动下载（Daemon 模式）
- 定时扫描 RSS，匹配已配置的追番规则
- 自动添加匹配的资源到 qBittorrent
- 跳过已下载的集数

### 5. 本地 Web 工作台
- 实时搜索与结果浏览
- 评分原因透明展示
- 搜索诊断（过滤条件影响分析、放宽建议）

## 架构

```
config.yaml  →  AppConfig (Pydantic)
                    │
                    ▼
              discovery.py  ←──  rss.py (dmhy keyword RSS)
                    │              parser.py (标题结构化解析)
                    │              matcher.py (规则匹配)
                    │              scorer.py (多维度评分)
                    ▼
              qbittorrent  ←──  probe.py (候选探测)
                    │              monitor.py (下载监控)
                    │              fallback.py (死种切换)
                    ▼
              Web UI (FastAPI + vanilla JS)
```

### 数据流
1. 用户输入标题 → RSS 关键词搜索（dmhy `?keyword=`）
2. RSS 条目 → parser 提取结构化字段
3. 候选 → filter（集数/分辨率/字幕等）→ 评分排序
4. 最佳候选 → 添加 qBittorrent → probe/monitor 保障下载完成

## 相比传统下载路径的优势

| 传统路径 | AQSD |
|---------|------|
| 手动访问 tracker 网站搜索 | 本地一键搜索 |
| 逐个检查标题、字幕、分辨率 | 自动解析 + 过滤 |
| 盲选 torrent，不知死活 | 评分排序 + probe/falback |
| 下载完手动整理 | 自动分类 + 标签 |

## 技术栈

- Python 3.11+ / Pydantic v2 / FastAPI
- qBittorrent Web API
- dmhy RSS (动漫花园)
- Vanilla JS Web UI
