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
