# WorkBuddy 每日积分自动签到

每天自动领取 WorkBuddy 每日积分（**100 分/天，连续第 7 天 1000 分**），
通过 WorkBuddy **Agent 定时任务**运行，全机器通用，不依赖固定路径 / PID。

> 核心逻辑全部集中在 `scripts/workbuddy_checkin.py` 一个文件，仅用 Python 标准库，
> Windows / Linux / macOS 三平台通用，已实测通过。

---

## 快速使用（1 分钟上手）

### 前置条件（唯一硬要求）

- 本机已安装并**登录** WorkBuddy 桌面端。
- 设定时间点**机器是开机的**（脚本从运行中的 WorkBuddy 内存读取令牌）。
- 可选的：系统装有 **Python 3**（用于跑脚本）。

### 一步：手动测试（先跑通）

```bash
cd scripts

# ① 环境自检：确认能读到账号 + 找到 WorkBuddy 进程 + 拿到 token（不发起签到）
python workbuddy_checkin.py --check

# ② 正式签到（幂等：当天已签会跳过）
python workbuddy_checkin.py

# ③ 可选：指定日志文件
python workbuddy_checkin.py --log /path/to/checkin.log
```

退出码：`0` 成功 / 今日已签；`1` 未登录；`2` WorkBuddy 未运行或无有效令牌；`4` 接口失败。

### 如何配置每日自动签到（Agent 定时任务）

在 WorkBuddy 里新建一个**循环定时任务（recurring）**，粘贴以下提示词并设为**每天 09:00**：

```text
执行 WorkBuddy 每日积分自动签到。

1. 自检：用命令行的方式运行 `python workbuddy_checkin.py --check`，
   若报错（未登录 / WorkBuddy 未运行 / 内存找不到令牌）就直接告知用户先登录并打开 WorkBuddy。
2. 自检通过后正式签到：运行 `python workbuddy_checkin.py`。
3. 汇报：输出“签到成功！本次获得 X 分”为成功；输出“今日已签到（幂等，跳过）”为已签成功；
   否则报告失败原因。
```

> 更完整的多时间点 / 排障 / 安全说明见 [`WorkBuddy-Agent定时签到-全流程（分享版）.md`](WorkBuddy-Agent定时签到-全流程（分享版）.md)。

---

## 它怎么工作（原理）

WorkBuddy 桌面端把登录令牌用自定义 AES-GCM 加密存盘，解析很麻烦。本方案**绕开磁盘解密**：
直接从**运行中的 WorkBuddy 进程内存**里动态提取当前账号的明文 `access_token`，再调用腾讯官方签到接口领取积分。

```
每天 09:00，Agent 定时任务触发
   │
   ▼
① 自检环境（WorkBuddy 是否登录并运行）
   ▼
② 从运行中的 WorkBuddy 内存提取本账号 access_token（RS256、sub=账号uid）
   ▼
③ 调用官方签到接口 POST https://copilot.tencent.com/v2/billing/meter/daily-checkin
   ▼
④ 幂等汇报：code=0 成功 / code=10001 今日已签 / 其他 失败
```

- 令牌**只在内存中使用一次、用完即丢，不落盘、不写日志**。
- 网络仅发往 `copilot.tencent.com` 官方接口，无任何第三方。

---

## 文件结构

```
workbuddy-checkin/
├── README.md                              # 本说明
├── scripts/
│   └── workbuddy_checkin.py               # 核心签到脚本（唯一需要配置的入口）
├── WorkBuddy-Agent定时签到-全流程（分享版）.md   # 详细全流程 / 分享文档
└── logs/                                 # 运行日志（自动生成，不入库）
```

---

## 常见问题

| 现象 | 处理 |
|------|------|
| 自检「未找到登录账号」 | 先登录 WorkBuddy 桌面端 |
| 自检「未检测到 WorkBuddy 进程」 | 定时前先打开 WorkBuddy |
| 自检「内存找不到令牌」 | 令牌过期/掉登录，退出并重启 WorkBuddy 再试 |
| 退出码 4 | 网络异常或令牌失效，检查网络/代理，重启 WorkBuddy 重登 |
| 定时跑但没日报 | 定时账户与登录账户不一致，改用同一账户运行 |

---

## 安全与许可（请勿用于违规用途）

- 本脚本**仅向你自己的 WorkBuddy 账号**发起官方签到请求，属于对自身账号的常规自动化。
- 令牌不落盘、不回显、不写日志，日志仅记结果与积分。
- 勿用于他人账号、批量刷分或任何违反 WorkBuddy 用户协议的行为。
- 发布本项目的使用者需自行确保其使用场景符合 applicable laws / 平台条款。

## License

MIT