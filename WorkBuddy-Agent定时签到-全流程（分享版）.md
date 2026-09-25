# WorkBuddy 每日积分自动签到 —— 用「Agent 定时任务」的全流程（可分享版）

> 本文教你**在 WorkBuddy 自己内部**配置一个「Agent 定时任务」，
> 让它每天自动替你领取 WorkBuddy 的每日积分（**100 分/天，连续第 7 天 1000 分**）。
> 全程**无需** Windows 任务计划、无需 crontab、无需 launchd，**只需 WorkBuddy 一个对话环境**。
> 本文可直接分享给其他 WorkBuddy 使用者照做。

---

## 0. 对照：这套方案的优点

| 对比项 | 系统级方案（cron/任务计划） | ✅ 本方案（Agent 定时任务） |
|---|---|---|
| 需要装东西 | Node.js / Python / 解密脚本 | **只要 WorkBuddy**（自带运行环境） |
| 配置难度 | 改系统配置，换机要重配 | **在 WorkBuddy 里建一条任务即可** |
| token 获取 | 解密本地文件（依赖版本） | **Agent 从运行中的 WorkBuddy 内存读取**，兼容性最好 |
| 结果反馈 | 只有退出码/日志 | Agent **自动判断并中文汇报**成功/失败原因 |
| 环境依赖 | 固定 Python 路径、固定 PID | **不写死任何路径/PID，通用** |

> 一句话：**别人拿到手，在 WorkBuddy 里粘一段提示词、设一个时间，就完事。**

---

## 1. 原理（听懂就能放心用）

WorkBuddy 桌面端登录后，签到所需的登录令牌（access_token）**就在它自己进程的内存里**。

Agent 定时任务的流程是：

```
每天 09:00 触发 Agent
      │
      ▼
① Agent 自检环境（WorkBuddy 是否登录并运行）
      │
      ▼
② Agent 从运行中的 WorkBuddy 内存里提取本账号的 access_token
      │
      ▼
③ 调用腾讯官方签到接口：POST https://copilot.tencent.com/v2/billing/meter/daily-checkin
      │
      ▼
④ 按返回结果向用户汇报：
    · code=0         → 签到成功，本次 +100 分
    · code=10001     → 今日已签（幂等，跳过）
    · 其他           → 失败及原因
```

**令牌只在内存里用一次、用完即丢，不落盘。** 网络只发往 `copilot.tencent.com` 官方接口，无任何第三方。

---

## 2. 前提（务必先确认）

- ✅ 本机已安装 **WorkBuddy 桌面端**，并**登录**过账号（没登录签不了）。
- ✅ 机器在设定时间点**是开机的**（因为要从内存读 token）。
- ✅ 在 WorkBuddy 里能创建「自动化/定时任务」功能（即本对话所用环境）。

> 若你在别处手动点过一次签到，脚本看到 `code=10001` 会判断"今日已签"，不重复、不报错。

---

## 3. 落地方式（二选一，推荐 A）

### 方式 A：让 Agent 自己完成签到（零脚本，最通用）

在 WorkBuddy 里新建一个**循环定时任务**，一次性填好下面内容即可：

- **名称**：`WorkBuddy 每日积分签到`
- **触发**：循环 → 每天 → `09:00`（可改成你自己习惯的时间）
- **提示词（prompt）**：直接复制下面这段：

```text
帮我执行 WorkBuddy 每日积分自动签到。

步骤：
1. 自检环境——确认本机 WorkBuddy 桌面端已登录并处于运行状态（例如通过进程是否在运行、能否读到本地登录账号信息的 `workbuddy-desktop.info` 来确认，路径通常在 Windows 的 `%LOCALAPPDATA%\CodeBuddyExtension\Data\Public\auth\` 下）。若未登录或未运行，直接告诉我"请先登录并打开 WorkBuddy"，不要继续。
2. 从运行中的 WorkBuddy 进程内存提取当前账号的 access_token（RS256、payload.sub 等于账号 uid 的那一个）。
3. 调用官方签到接口：POST https://copilot.tencent.com/v2/billing/meter/daily-checkin，请求头带 Authorization: Bearer <access_token>。
4. 汇报结果：
   - 接口返回 code=0 且 data 含 credit → 「✅ 签到成功，本次获得 X 分」；
   - 返回 code=10001 → 「ℹ️ 今日已签到（幂等，跳过）」；
   - 其他错误 → 「❌ 签到失败 + 原因」。
```

> 有没有可执行的辅助脚本？有，请看方式 B（可选，能提升成功率与可读性）。

---

### 方式 B：附一个通用 Python 脚本，让 Agent 调用（可选，更稳）

如果你（或接收文档的人）机器上有 **Python**，可以放一个脚本让 Agent 定期运行，脚本自动"找进程→读内存→签到→输日志"，Agent 只负责调用并汇报。脚本逻辑**不写死 PID/路径**，通用。

```
#!/usr/bin/env python
# -*- coding: utf-8 -*-
# workbuddy_checkin.py —— WorkBuddy 每日积分自动签到（内存令牌方案，通用）
# 用法（命令行）：
#   python workbuddy_checkin.py --check   # 仅自检，不签到
#   python workbuddy_checkin.py           # 正式签到（幂等）
# 依赖：仅标准库。需本机已登录并运行 WorkBuddy 桌面端。
import ctypes, ctypes.wintypes as wt, json, re, os, base64, ssl
import datetime, urllib.request, urllib.error, subprocess

PROCESS_QUERY_INFORMATION = 0x0400
PROCESS_VM_READ = 0x0010
MEM_COMMIT = 0x1000
PAGE_NOACCESS = 0x01
PAGE_GUARD = 0x100
API = "https://copilot.tencent.com/v2/billing/meter"

def _b64json(seg):
    seg += "=" * (-len(seg) % 4)
    return json.loads(base64.urlsafe_b64decode(seg).decode())

def _pids():
    try:
        r = subprocess.run(["tasklist","/FO","CSV","/FI","IMAGENAME eq WorkBuddy.exe"],
                           capture_output=True)
        out=[]
        for line in r.stdout.decode("utf-8","ignore").splitlines()[1:]:
            p=line.replace('"','').split(",")
            if len(p)>=2 and p[1].isdigit(): out.append(int(p[1]))
        return out
    except Exception: return []

def _uid():
    for base in (os.environ.get("LOCALAPPDATA",""), os.environ.get("APPDATA","")):
        p=os.path.join(base,"CodeBuddyExtension","Data","Public","auth","workbuddy-desktop.info")
        if os.path.exists(p):
            try: return json.load(open(p,encoding="utf-8")).get("account",{}).get("uid")
            except Exception: pass
    return None

class MBI(ctypes.Structure):
    _fields_=[("BaseAddress",ctypes.c_void_p),("AllocationBase",ctypes.c_void_p),
              ("AllocationProtect",wt.DWORD),("PartitionId",wt.WORD),
              ("RegionSize",ctypes.c_size_t),("State",wt.DWORD),
              ("Protect",wt.DWORD),("Type",wt.DWORD)]

_k32=ctypes.WinDLL("kernel32",use_last_error=True)

def _scan(pid,uid):
    h=_k32.OpenProcess(PROCESS_QUERY_INFORMATION|PROCESS_VM_READ,False,pid)
    if not h: return None
    cand=set(); addr=0
    try:
        while True:
            m=MBI()
            if _k32.VirtualQueryEx(h,ctypes.c_void_p(addr),ctypes.byref(m),ctypes.sizeof(m))==0: break
            if m.State==MEM_COMMIT and not (m.Protect&PAGE_NOACCESS) and not (m.Protect&PAGE_GUARD) and 0<m.RegionSize<=64*1024*1024:
                buf=ctypes.create_string_buffer(m.RegionSize); rd=ctypes.c_size_t(0)
                if _k32.ReadProcessMemory(h,ctypes.c_void_p(addr),buf,m.RegionSize,ctypes.byref(rd)):
                    s=buf.raw[:rd.value].decode("utf-8","ignore")
                    for mm in re.finditer(r"(eyJ[A-Za-z0-9_\-]{40,}\.[A-Za-z0-9_\-]{40,}\.[A-Za-z0-9_\-]{20,})",s):
                        t=mm.group(1)
                        if len(t)<400 or t in cand: continue
                        try:
                            if _b64json(t.split(".")[0]).get("alg")!="RS256": continue
                            if _b64json(t.split(".")[1]).get("sub")==uid: cand.add(t)
                        except Exception: pass
            addr+=m.RegionSize
            if addr>0x7FFFFFFFFFFF: break
    finally: _k32.CloseHandle(h)
    return sorted(cand,key=len,reverse=True)[0] if cand else None

def _api(token,path,body):
    req=urllib.request.Request(API+path,data=json.dumps(body).encode(),method="POST")
    req.add_header("Authorization","Bearer "+token); req.add_header("Content-Type","application/json")
    try:
        with urllib.request.urlopen(req,timeout=20,context=ssl.create_default_context()) as r:
            return r.status,json.loads(r.read().decode())
    except urllib.error.HTTPError as e:
        try: return e.code,json.loads(e.read().decode("utf-8","ignore"))
        except Exception: return e.code,e.read().decode("utf-8","ignore")

def _locate():
    """返回 (uid, pids)。供 main / check 复用。"""
    return _uid(), _pids()

def _check():
    uid,pids=_locate()
    if not uid: print("❌ 未找到登录账号，请先登录 WorkBuddy"); return 1
    print(f"✅ 账号 UID: {uid}")
    if not pids: print("❌ 未检测到 WorkBuddy 进程"); return 2
    print(f"✅ WorkBuddy 进程 PID: {pids}")
    for pid in pids:
        try:
            if _scan(pid,uid):
                print(f"✅ PID {pid} 内存可取到 access_token")
                return 0
        except Exception as e: print("  扫描出错",e)
    print("❌ 内存未取到有效 token（请确认 WorkBuddy 已登录）"); return 2

def main():
    if "--check" in __import__("sys").argv: return _check()
    uid,pids=_uid(),_pids()
    if not uid: print("❌ 未找到登录账号，请先登录 WorkBuddy"); return 1
    if not pids: print("❌ 未检测到 WorkBuddy 进程"); return 2
    tok=None
    for pid in pids:
        try:
            t=_scan(pid,uid)
            if t: tok=t; print(f"✅ PID {pid} 内存取到 access_token (len={len(t)})"); break
        except Exception as e: print("  扫描出错",e)
    if not tok: print("❌ 内存未取到有效 token"); return 2
    st,body=_api(tok,"/daily-checkin",{})
    if st==200 and isinstance(body,dict) and body.get("code")==0:
        print(f"✅ 签到成功！本次获得 {body.get('data',{}).get('credit','?')} 分")
    elif isinstance(body,dict) and body.get("code")==10001:
        print("ℹ️ 今日已签到（幂等，跳过）")
    else:
        print("❌ 签到失败",st,body); return 4
    return 0

if __name__=="__main__":
    import sys; sys.exit(main())
```

> 用脚本后，把方式 A 的提示词里"调用签到接口"换成「运行 `python workbuddy_checkin.py`（或用 `--check` 自检）并读取输出汇报即可」。

---

## 4. 在 WorkBuddy 里创建 Agent 定时任务 —— 分步图解

（以下以 WorkBuddy 内"自动化/定时任务"入口为准，各版本按钮名称可能略有差异）

1. 打开 WorkBuddy，进入**自动化 / 定时任务**管理页。
2. 新建一个任务，**类型选「循环（recurring）」**。
3. **名称**：填 `WorkBuddy 每日积分签到`。
4. **触发规则**：每天，时间 `09:00`（推荐 08:00–10:00，此时一般已开机登录。
   - 可选：若你希望多时间点补签（电脑可能晚开机），可用多条 `BYHOUR`，例 `FREQ=DAILY;BYHOUR=9,12,15,18,21;BYMINUTE=0`。
5. **提示词（prompt）**：粘贴第 3 节「方式 A」的模板（或用方式 B 脚本版）。
6. **工作目录**：若有脚本，写脚本所在目录；纯方式 A 可不填或填工作目录。
7. 保存并**启用（ACTIVE）**。

---

## 5. 如何验证真的生效

任务跑完，看 Agent 的第一条汇报或日志：

| 你看到的 | 含义 |
|---|---|
| ✅ 签到成功！本次获得 100 分 | 今天+100 分，成功 |
| ℹ️ 今日已签到（幂等，跳过） | 已被当天的签到，成功（不重复） |
| ❌ 未检测到 WorkBuddy 进程 | 定时时 WorkBuddy 没开 → 调早一点或开机后跑 |
| ❌ 未取到有效 token | 检查是否已登录、重启 WorkBuddy |

**积分核对**：登录 WorkBuddy 个人中心/积分页，应比昨日 +100。

---

## 7 排障

| 现象 | 处理 |
|---|---|
| 总提示"未检测到 WorkBuddy 进程" | 登录并打开 WorkBuddy 桌面端再跑；定时时间改到你在电脑旁这样 |
| 运行时段 WorkBuddy 未打开 | 让定时任务时间对应用电开机时间，或用上面多条 `BYHOUR` |
| 自检看到"未取到 token" | 桌面端可能掉登录态，退出重登一次 |
| 提示接口 401/失败 | token 失效，重登 WorkBuddy 后会刷新；检查网络/代理 |
| 定时任务没触发 | 确认已"启用（ACTIVE）"、时间设对、不是一次性任务 |

---

## 8. 安全与注意事项（请转发时保留）

- **本任务只向你自己的 WorkBuddy 账号操作**，为官方正规签到，安全合法。
- **令牌只在内存中使用一次，绝不落盘、不写日志、不回显**。日志只记结果与积分。
- 网络仅发往官方 `copilot.tencent.com`，**不上传第三方**。
- 不要用于他人账号、刷分或违反 WorkBuddy 用户协议，使用风险自担。
- **保留授权边界**：本文假定你对自己账号的积分签到被官方允许（用户协议范围内）。