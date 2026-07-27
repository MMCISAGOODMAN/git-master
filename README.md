# Git 提交整合工具（Web 可视化版）

在浏览器中可视化筛选 Git 提交，并将选中提交从源分支整合到目标分支（cherry-pick / squash），支持自动备份与一键恢复。

## 功能

- 本地仓库路径：启动参数 / 环境变量默认路径，页面可随时切换
- 分支选择、作者筛选、类型 / 时间 / 关键词过滤
- 提交表格：勾选、排序、分页、复制短哈希、查看详情
- 统计：总提交、已选、作者数、+/- 行变更
- 整合：普通 cherry-pick 或 Squash；冲突可暂停 / 跳过 / `--ours`
- 冲突预览（`git merge-tree`，不改工作区）
- 整合前自动备份 `backup-{目标分支}-{YYYYMMDD-HHMMSS}`，支持一键恢复
- 底部实时日志 + 进度条（SSE）

## 环境要求

- Python 3.10+
- 本机已安装 `git`
- 可访问 CDN（Vue 3 / Element Plus）

## 安装与启动

```bash
cd git-master
python3 -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt

# 指定默认仓库
python app.py --repo /path/to/your/repo

# 或使用环境变量
export GIT_REPO_PATH=/path/to/your/repo
python app.py

# 可选：主机与端口（默认 5001；勿用 5000，macOS AirPlay 常占用并返回 403）
python app.py --repo /path/to/repo --host 127.0.0.1 --port 5001
```

浏览器打开：<http://127.0.0.1:5001>

若未传 `--repo`，在页面顶部输入仓库绝对路径并点击「应用」。

## 使用步骤

1. 确认仓库路径与当前分支
2. 选择**源分支**（提交来源）与**目标分支**（写入目标）
3. 按作者 / 类型 / 时间 / 关键词筛选，勾选要整合的提交
4. 可选：点击「预览冲突」
5. 选择整合模式与冲突策略，点击「整合」并确认
6. 关注底部日志与进度；完成后查看结果报告
7. 如需回滚，使用「一键恢复」或执行页面显示的恢复命令

## 整合说明

| 模式 | 行为 |
|------|------|
| 普通 | 按时间从旧到新逐个 `cherry-pick` |
| Squash | 依次 `cherry-pick -n` 累加后生成一次提交 |

| 冲突策略 | 行为 |
|----------|------|
| 暂停 | 停止整合，保留冲突状态，可手动处理或恢复备份 |
| 跳过 | 跳过冲突提交并继续 |
| `--ours` | 采用目标分支版本解决冲突（可能丢失源变更，慎用） |

**注意：** 整合要求工作区干净。操作会切换到目标分支；失败且工作区干净时会尝试切回原分支。

## 备份与恢复

整合开始时自动创建备份分支，例如：

```text
backup-main-20260727-143015
```

恢复命令示例：

```bash
git checkout <目标分支> && git reset --hard <备份分支>
```

页面提供「一键恢复」，效果与上述命令相同（`reset --hard`）。

## API 概览

| 方法 | 路径 | 说明 |
|------|------|------|
| GET/POST | `/api/repo` | 查询 / 设置仓库 |
| GET | `/api/branches` | 本地分支 |
| GET | `/api/authors` | 源分支作者 |
| GET | `/api/commits` | 提交列表（筛选分页） |
| GET | `/api/commits/:hash` | 提交详情 |
| GET | `/api/stats` | 选中提交统计 |
| POST | `/api/integrate/preview` | 冲突预览 |
| POST | `/api/integrate` | 启动整合 |
| GET | `/api/integrate/:id/stream` | SSE 进度 |
| POST | `/api/integrate/:id/abort` | 中止 |
| POST | `/api/backup/restore` | 恢复备份 |

## 项目结构

```text
git-master/
├── app.py
├── git_service.py
├── integrate_service.py
├── requirements.txt
├── README.md
└── static/
    ├── index.html
    ├── css/app.css
    └── js/{api,utils,app}.js
```

## 安全说明

- 所有 Git 操作在服务端执行，禁止 shell 字符串拼接
- 分支名经白名单校验，防止注入与路径遍历
- 默认仅监听 `127.0.0.1`；若对公网开放，请自行加鉴权与网络隔离

## 许可

本地工具，按需使用。
