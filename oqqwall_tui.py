#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
OQQWall TUI 管理器（Linux 终端）
依赖: textual>=0.30 (pip install textual)

功能概览：
- 双栏导航：主页 / 全局配置 / 组配置 / Log
- 主页：启动/停止 OQQWall、检查 NapCat 状态、显示待审核数量与当前内部编号
- 全局配置：查看/编辑 oqqwall.config（简易表单）
- 组配置：查看 AcountGroupcfg.json（组与账号概览）
- Log：查看并跟随 logs/*.log 与 OQQWallmsgserv.log
"""

from __future__ import annotations

import asyncio
import json
import os
import signal
import sqlite3
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional
from urllib.request import urlopen
from urllib.error import URLError

from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Container, Horizontal, Vertical, ScrollableContainer
from textual.widgets import (
    Button,
    Header,
    Footer,
    Static,
    Label,
    ListView,
    ListItem,
    Input,
    DataTable,
    SelectionList,
    Switch,
)
# 兼容不同版本 Textual 的日志控件
try:  # Textual 新版本
    from textual.widgets import TextLog as LogWidget  # type: ignore
except Exception:  # Textual 旧/其他版本
    try:
        from textual.widgets import RichLog as LogWidget  # type: ignore
    except Exception:
        from textual.widgets import Log as LogWidget  # type: ignore
from textual.reactive import reactive
from rich.text import Text


ROOT = Path(__file__).resolve().parent
DB_PATH = ROOT / "cache" / "OQQWall.db"
PREPOST_DIR = ROOT / "cache" / "prepost"
PICTURE_DIR = ROOT / "cache" / "picture"
CONFIG_FILE = ROOT / "oqqwall.config"
GROUP_CFG = ROOT / "AcountGroupcfg.json"

# 配置项提示信息（鼠标悬浮在“?”上显示）
CONFIG_TOOLTIPS: dict[str, str] = {
    "http-serv-port": "HTTP 服务端口（默认 8082）",
    "apikey": "调用大模型时使用的 API Key",
    "process_waittime": "等待图片/处理的超时秒数",
    "manage_napcat_internal": "是否由本程序管理 NapCat/QQ",
    "max_attempts_qzone_autologin": "QZone 自动登录重试次数",
    "text_model": "文本模型名称（如 qwen-plus-latest）",
    "vision_model": "多模态模型名称",
    "vision_pixel_limit": "图片像素限制，超出会压缩",
    "vision_size_limit_mb": "图片大小限制（MB）",
    "at_unprived_sender": "通过时是否 @ 未公开空间的投稿人",
    "friend_request_window_sec": "好友请求窗口（秒）",
    "force_chromium_no-sandbox": "Chromium 禁用 sandbox（容器/权限受限环境使用）",
    "use_web_review": "是否启用网页审核面板",
    "web_review_port": "网页审核监听端口",
    "napcat_access_token": "NapCat /get_status 接口 Access Token",
}

# 全局配置固定顺序（未列出的键会按字母顺序追加在末尾）
CONFIG_ORDER: list[str] = [
    # 基础/服务
    "http-serv-port",
    "process_waittime",
    "apikey",
    # NapCat/登录
    "napcat_access_token",
    "manage_napcat_internal",
    # QZone/浏览器
    "max_attempts_qzone_autologin",
    "force_chromium_no-sandbox",
    # 机器人行为
    "at_unprived_sender",
    "friend_request_window_sec",
    # 审核面板
    "use_web_review",
    "web_review_port",
    # 模型与能力
    "text_model",
    "vision_model",
    "vision_pixel_limit",
    "vision_size_limit_mb",
]


def read_kv_config(path: Path) -> dict[str, str]:
    """读取 oqqwall.config（key=value，#注释），返回字典。"""
    result: dict[str, str] = {}
    if not path.is_file():
        return result
    for line in path.read_text(encoding="utf-8").splitlines():
        s = line.strip()
        if not s or s.startswith("#"):
            continue
        if "=" not in s:
            continue
        k, v = s.split("=", 1)
        result[k.strip()] = v.strip().strip('"')
    return result


def write_kv_config(path: Path, data: dict[str, str]) -> None:
    """覆盖写回简单 key=value 文件，保留注释较难，这里简化为纯导出。"""
    lines = []
    for k, v in data.items():
        # 对值加引号以避免空格/特殊字符问题
        lines.append(f"{k}={json.dumps(str(v), ensure_ascii=False)}")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def sqlite_query_one(sql: str, params: tuple = ()) -> Optional[tuple]:
    if not DB_PATH.exists():
        return None
    con = sqlite3.connect(str(DB_PATH))
    try:
        cur = con.execute(sql, params)
        return cur.fetchone()
    finally:
        con.close()


def sqlite_query_all(sql: str, params: tuple = ()) -> list[tuple]:
    if not DB_PATH.exists():
        return []
    con = sqlite3.connect(str(DB_PATH))
    try:
        cur = con.execute(sql, params)
        return cur.fetchall()
    finally:
        con.close()


def list_groups_from_cfg() -> list[str]:
    try:
        data = json.loads(GROUP_CFG.read_text(encoding="utf-8"))
        return list(data.keys())
    except Exception:
        return []


def staged_tags_all_groups() -> set[str]:
    """合并所有 sendstorge_<group> 的 tag。"""
    tags: set[str] = set()
    for group in list_groups_from_cfg():
        try:
            rows = sqlite_query_all(f"SELECT tag FROM sendstorge_{group}")
            for (tag,) in rows:
                if tag is not None:
                    tags.add(str(tag))
        except Exception:
            # 表不存在等情况
            pass
    return tags


def pending_count() -> int:
    """计算待审核数：prepost 目录下的数字子目录，去除暂存区中的 tag。"""
    if not PREPOST_DIR.exists():
        return 0
    staged = staged_tags_all_groups()
    count = 0
    for p in PREPOST_DIR.iterdir():
        if p.is_dir() and p.name.isdigit() and p.name not in staged:
            count += 1
    return count


def current_internal_id() -> Optional[int]:
    """读取 preprocess 表中的 MAX(tag) 作为当前内部编号。"""
    row = sqlite_query_one("SELECT MAX(CAST(tag AS INTEGER)) FROM preprocess")
    if not row:
        return None
    try:
        return int(row[0]) if row[0] is not None else None
    except Exception:
        return None


def napcat_status_url() -> str:
    cfg = read_kv_config(CONFIG_FILE)
    token = cfg.get("napcat_access_token") or os.environ.get("NAPCAT_TOKEN") or ""
    if token:
        return f"http://127.0.0.1:3000/get_status?access_token={token}"
    # 回退到示例 token（仅本地测试）
    sample = "Wv6I0yogQBXU9iFmdUqJNLbPhGjMMUPY"
    return f"http://127.0.0.1:3000/get_status?access_token={sample}"


def _state_color(state: str) -> str:
    return {
        "ok": "green",
        "warn": "yellow",
        "fail": "red",
        "unknown": "grey50",
    }.get(state, "white")


async def fetch_napcat_status() -> tuple[str, str]:
    """获取 NapCat 健康状态。

    Returns:
        (state, message): state in {ok, warn, fail, unknown}
    """
    url = napcat_status_url()
    try:
        with urlopen(url, timeout=3) as resp:
            data = json.loads(resp.read().decode("utf-8", errors="ignore"))
        online = bool(((data or {}).get("data") or {}).get("online"))
        good = bool(((data or {}).get("data") or {}).get("good"))
        if online and good:
            return "ok", "在线且健康"
        if online and not good:
            return "warn", "在线但异常"
        return "fail", "离线"
    except URLError as e:
        return "fail", f"请求失败: {e.reason}"
    except Exception as e:
        return "fail", f"错误: {e}"


def napcat_login_info_url() -> str:
    cfg = read_kv_config(CONFIG_FILE)
    token = cfg.get("napcat_access_token") or os.environ.get("NAPCAT_TOKEN") or ""
    if token:
        return f"http://127.0.0.1:3000/get_login_info?access_token={token}"
    sample = "Wv6I0yogQBXU9iFmdUqJNLbPhGjMMUPY"
    return f"http://127.0.0.1:3000/get_login_info?access_token={sample}"


async def fetch_napcat_login_user_id() -> Optional[str]:
    """读取 NapCat 当前登录 QQ 号（若可用）。"""
    url = napcat_login_info_url()
    try:
        with urlopen(url, timeout=3) as resp:
            data = json.loads(resp.read().decode("utf-8", errors="ignore"))
        uid = str(((data or {}).get("data") or {}).get("user_id") or "").strip()
        return uid or None
    except Exception:
        return None


def _inst_urls(port: str, token: str) -> tuple[str, str]:
    base = f"http://127.0.0.1:{port}"
    return (
        f"{base}/get_status?access_token={token}",
        f"{base}/get_login_info?access_token={token}",
    )


async def fetch_instance_state(port: str, token: str) -> tuple[str, str, Optional[str]]:
    """获取指定端口 NapCat 实例的状态。

    Returns:
        (state, message, user_id)
        state: ok / warn / fail
        message: 文本描述
        user_id: 登录 QQ（可能为 None）
    """
    status_url, login_url = _inst_urls(port, token)
    state = "fail"
    msg = "未检测"
    uid: Optional[str] = None
    try:
        with urlopen(status_url, timeout=2) as resp:
            data = json.loads(resp.read().decode("utf-8", errors="ignore"))
        online = bool(((data or {}).get("data") or {}).get("online"))
        good = bool(((data or {}).get("data") or {}).get("good"))
        if online and good:
            state, msg = "ok", "在线且健康"
        elif online:
            state, msg = "warn", "在线但异常"
        else:
            state, msg = "fail", "离线"
    except Exception as e:
        state, msg = "fail", f"请求失败"
    # 尝试读取登录 QQ
    try:
        with urlopen(login_url, timeout=2) as resp:
            j = json.loads(resp.read().decode("utf-8", errors="ignore"))
        uid = str(((j or {}).get("data") or {}).get("user_id") or "").strip() or None
    except Exception:
        pass
    return state, msg, uid


def iter_account_instances() -> list[tuple[str, str, str]]:
    """返回 (group, qq, port) 列表，包含主/副账号。
    若副账号端口数组长度与 id 数量不等，按较短长度对齐。
    """
    try:
        raw = json.loads((ROOT / "AcountGroupcfg.json").read_text(encoding="utf-8")) or {}
    except Exception:
        return []
    out: list[tuple[str, str, str]] = []
    for g, obj in raw.items():
        qq = str(obj.get("mainqqid") or "").strip()
        pt = str(obj.get("mainqq_http_port") or "").strip()
        if qq and pt:
            out.append((g, qq, pt))
        ids = [str(x or "").strip() for x in (obj.get("minorqqid") or [])]
        ports = [str(x or "").strip() for x in (obj.get("minorqq_http_port") or [])]
        m = min(len(ids), len(ports))
        for i in range(m):
            if ids[i] and ports[i]:
                out.append((g, ids[i], ports[i]))
    return out


def get_all_qq_ids() -> list[str]:
    """从 AcountGroupcfg.json 汇总所有主/副账号 QQ 号。"""
    try:
        data = json.loads(GROUP_CFG.read_text(encoding="utf-8"))
        ids: set[str] = set()
        for _, obj in (data or {}).items():
            mq = str(obj.get("mainqqid") or "").strip()
            if mq:
                ids.add(mq)
            for sub in obj.get("minorqqid") or []:
                s = str(sub or "").strip()
                if s:
                    ids.add(s)
        return sorted(ids)
    except Exception:
        return []


def _iter_proc_cmdlines():
    proc_dir = Path("/proc")
    for p in proc_dir.iterdir():
        if not p.name.isdigit():
            continue
        try:
            raw = (p / "cmdline").read_bytes()
            if not raw:
                continue
            args = raw.split(b"\x00")
            args = [a.decode("utf-8", "ignore") for a in args if a]
            if not args:
                continue
            yield args
        except Exception:
            continue


def _py_script_running(suffix: str) -> bool:
    """Detect a running Python script by suffix path match in argv tokens.

    Avoids false positives from shell wrappers (e.g., `bash -lc "pgrep ..."`).
    """
    for args in _iter_proc_cmdlines():
        exe = args[0]
        if not (exe.endswith("python") or exe.endswith("python3") or "/python" in exe):
            continue
        for a in args[1:]:
            if a.endswith(suffix):
                return True
    return False


def _sh_script_running(suffix: str) -> bool:
    for args in _iter_proc_cmdlines():
        exe = args[0]
        if not (exe.endswith("bash") or exe.endswith("/sh") or exe.endswith("/bash")):
            continue
        for a in args[1:]:
            if a.endswith(suffix):
                return True
    return False


def services_status() -> dict[str, bool]:
    """返回三个核心子服务状态。"""
    s = {
        "recv": _py_script_running("getmsgserv/serv.py"),
        "ctrl": _sh_script_running("Sendcontrol/sendcontrol.sh"),
        "pipe": _py_script_running("SendQzone/qzone-serv-pipe.py"),
    }
    # 可选 web_review
    cfg = read_kv_config(CONFIG_FILE)
    use_web = str(cfg.get("use_web_review", "false")).strip().lower() == "true"
    if use_web:
        # 可能以 "python3 web_review/web_review.py" 或在 web_review 目录直接以 "python3 web_review.py" 启动
        s["web"] = _py_script_running("web_review/web_review.py") or _py_script_running("web_review.py")
    else:
        s["web"] = None  # 表示禁用
    return s


def is_oqqwall_running_external() -> bool:
    """判断 OQQWall 是否运行（即使非 TUI 启动）。"""
    s = services_status()
    # 把 None 过滤掉（表示禁用）
    return any(bool(v) for v in s.values() if v is not None)


def kill_child_services() -> None:
    """停止核心子服务（不会动 NapCat）。"""
    cmds = [
        "pkill -f -- 'python3 getmsgserv/serv.py' 2>/dev/null || true",
        "pkill -f -- 'Sendcontrol/sendcontrol.sh' 2>/dev/null || true",
        "pkill -f -- 'python3 ./SendQzone/qzone-serv-pipe.py' 2>/dev/null || true",
        "pkill -f -- 'python3 SendQzone/qzone-serv-pipe.py' 2>/dev/null || true",
        "pkill -f -- 'python3 web_review/web_review.py' 2>/dev/null || true",
        "pkill -f -- 'python3 web_review.py' 2>/dev/null || true",
    ]
    for c in cmds:
        try:
            subprocess.run(["bash", "-lc", c], cwd=str(ROOT), stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        except Exception:
            pass


@dataclass
class ProcHandle:
    proc: subprocess.Popen | None = None
    pgid: int | None = None


class HomePage(Vertical):
    """主页内容：启动/停止、NapCat 状态、统计信息。"""
    pending: reactive[int | None] = reactive(None)
    internal_id: reactive[int | None] = reactive(None)
    napcat_msg: reactive[str] = reactive("未检查")
    running: reactive[bool] = reactive(False)

    def __init__(self, proc_handle: ProcHandle):
        super().__init__(id="home_page")
        self.proc_handle = proc_handle

    def compose(self) -> ComposeResult:
        yield Static("主页", classes="title")
        with Horizontal(classes="toolbar"):
            yield Button("▶ 启动 OQQWall", id="start")
            yield Button("■ 停止 OQQWall", id="stop")
            yield Button("🔍 检查 NapCat", id="check_napcat")
            yield Button("🧪 检查子服务", id="check_services")
        # 状态块：两行显示
        with Vertical(id="status_block"):
            with Horizontal(classes="status_row"):
                self.running_label = Label("OQQWall: 未运行", id="run_status")
                yield self.running_label
            with Horizontal(classes="status_row"):
                self.napcat_label = Label("NapCat: 未检查", id="napcat_status")
                self.qq_label = Label("QQ: 未检查", id="qq_status")
                yield self.napcat_label
                yield Static("  ")
                yield self.qq_label
            with Horizontal(classes="status_row"):
                self.services_label = Label("子服务: 待检测", id="services_status")
                yield self.services_label
        with Horizontal(classes="cards"):
            self.pending_label = Static("待审核: -", classes="card")
            self.internal_label = Static("内部编号: -", classes="card")
            yield self.pending_label
            yield self.internal_label

    async def on_button_pressed(self, event: Button.Pressed) -> None:
        bid = event.button.id
        if bid == "start":
            await self._start()
        elif bid == "stop":
            await self._stop()
        elif bid == "check_napcat":
            await self._refresh_qq_status()
        elif bid == "check_services":
            await self._refresh_services_status()

    async def _start(self) -> None:
        if self.proc_handle.proc and self.proc_handle.proc.poll() is None:
            self.running = True
            self._set_running_label(True)
            return
        try:
            # 使用新进程组以便整组停止
            proc = subprocess.Popen(
                ["bash", "-lc", "./main.sh"],
                cwd=str(ROOT),
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                preexec_fn=os.setsid if sys.platform != "win32" else None,
            )
            self.proc_handle.proc = proc
            try:
                self.proc_handle.pgid = os.getpgid(proc.pid)
            except Exception:
                self.proc_handle.pgid = None
            self.running = True
            self._set_running_label(True)
            # 将输出转发到 App 的日志面板（若存在）
            app = self.app
            if isinstance(app, OQQWallTUI):
                app.forward_process_output(proc)
        except Exception as e:
            self.running = False
            self.running_label.update(f"启动失败: {e}")

    async def _stop(self) -> None:
        proc = self.proc_handle.proc
        if proc and proc.poll() is None:
            try:
                if self.proc_handle.pgid is not None:
                    os.killpg(self.proc_handle.pgid, signal.SIGTERM)
                else:
                    proc.terminate()
            except Exception:
                try:
                    proc.kill()
                except Exception:
                    pass
        # 读取是否内部管理 NapCat/QQ
        cfg = read_kv_config(CONFIG_FILE)
        manage_q = (str(cfg.get("manage_napcat_internal", "false")).strip().lower() == "true")
        # 手动杀核心子服务；如内部管理则尝试杀 QQ（与 main.sh 的 kill_pat 模式一致）
        try:
            kill_child_services()
            if manage_q:
                subprocess.run(["bash", "-lc", "pkill -f -- 'xvfb-run -a qq --no-sandbox -q' 2>/dev/null || true"], cwd=str(ROOT), stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        except Exception:
            pass
        self.running = False
        # 立即刷新子服务与运行状态行
        try:
            self._update_services_line()
        except Exception:
            pass
        self._set_running_label(False)

    async def watch_metrics(self) -> None:
        """周期刷新待审数量与内部编号。"""
        while True:
            try:
                p = pending_count()
                i = current_internal_id()
                self.pending = p
                self.internal_id = i
                self.pending_label.update(f"待审核: {p}")
                self.internal_label.update(f"内部编号: {i if i is not None else '-'}")
            except Exception:
                pass
            await asyncio.sleep(5)

    async def on_mount(self) -> None:
        # 定时刷新 OQQWall 进程状态
        self.set_interval(2, self._update_run_status)
        # 启动指标刷新任务
        self.run_worker(self.watch_metrics(), exclusive=True, thread=False)
        # 首次刷新一次服务状态
        self.run_worker(self._refresh_services_status(), exclusive=False, thread=False)
        # 定时刷新子服务状态行
        self.set_interval(5, self._update_services_line)

    def _calc_oqqwall_running(self) -> bool:
        running = bool(self.proc_handle.proc and self.proc_handle.proc.poll() is None)
        if not running:
            running = is_oqqwall_running_external()
        return running

    def _set_running_label(self, running: bool) -> None:
        from rich.text import Text as _T
        self.running_label.update(_T("OQQWall: 运行中", style="green") if running else _T("OQQWall: 未运行", style="red"))

    def _update_run_status(self) -> None:
        running = self._calc_oqqwall_running()
        self.running = bool(running)
        self._set_running_label(running)

    async def _refresh_qq_status(self) -> None:
        # 逐实例探测
        cfg = read_kv_config(CONFIG_FILE)
        token = cfg.get("napcat_access_token") or os.environ.get("NAPCAT_TOKEN") or ""
        instances = iter_account_instances()
        ok = 0
        total = 0
        abnormal_ids: list[str] = []
        parts: list[Text] = []
        if not instances:
            self.qq_label.update(Text("无配置账号", style="grey50"))
            self.napcat_label.update(Text("NapCat: 未配置", style="grey50"))
            return
        for (grp, qq, port) in instances:
            total += 1
            st, msg, uid = await fetch_instance_state(port, token)
            if st == "ok":
                ok += 1
            else:
                abnormal_ids.append(qq)
            parts.extend([
                Text(f"qq {qq}:", style="bold"),
                Text(msg, style=_state_color(st)),
                Text(f"({port})"),
                Text("； ")
            ])
        # 去掉最后的间隔
        if parts:
            parts = parts[:-1]
        self.qq_label.update(Text.assemble(*parts))
        # 汇总到 NapCat 行
        if ok == total:
            self.napcat_label.update(Text(f"NapCat: 健康 {ok}/{total}", style="green"))
        else:
            base = Text(f"NapCat: 全部不可用 {ok}/{total}", style="red") if ok == 0 else Text(f"NapCat: 部分可用 {ok}/{total}", style="yellow")
            if abnormal_ids:
                base = Text.assemble(base, Text("；异常: "), Text(", ".join(abnormal_ids), style="red"))
            self.napcat_label.update(base)

    async def _refresh_services_status(self) -> None:
        """检查子服务进程状态并更新状态行。"""
        s = services_status()
        self._set_services_label(s)

    def _update_services_line(self) -> None:
        s = services_status()
        self._set_services_label(s)

    def _set_services_label(self, s: dict[str, bool]) -> None:
        recv_ok = s.get("recv", False)
        ctrl_ok = s.get("ctrl", False)
        pipe_ok = s.get("pipe", False)
        web_val = s.get("web", None)  # None 表示禁用
        cfg = read_kv_config(CONFIG_FILE)
        web_port = str(cfg.get("web_review_port", "")) if web_val is not None else ""
        parts = [
            Text("子服务："),
            Text("接收:", style="bold"), Text("运行" if recv_ok else "未运行", style=("green" if recv_ok else "red")), Text("； "),
            Text("审核:", style="bold"), Text("运行" if ctrl_ok else "未运行", style=("green" if ctrl_ok else "red")), Text("； "),
            Text("QZone:", style="bold"), Text("运行" if pipe_ok else "未运行", style=("green" if pipe_ok else "red")),
        ]
        parts.append(Text("； "))
        parts.append(Text("WebReview:", style="bold"))
        if web_val is None:
            parts.append(Text("已禁用", style="grey50"))
        else:
            label = "运行" if web_val else "未运行"
            style = "green" if web_val else "red"
            if web_port:
                label = f"{label}({web_port})"
            parts.append(Text(label, style=style))
        t = Text.assemble(*parts)
        self.services_label.update(t)


class GlobalConfigPage(Vertical):
    """全局配置：oqqwall.config 简易编辑。"""
    def __init__(self):
        super().__init__(id="global_cfg_page")
        self.inputs: dict[str, Input] = {}

    def compose(self) -> ComposeResult:
        yield Static("全局配置 (oqqwall.config)", classes="title")
        # 可滚动容器，放置配置表单行
        self.form = ScrollableContainer(id="global_cfg_form")
        yield self.form
        with Horizontal(classes="toolbar"):
            yield Button("💾 保存", id="save_cfg")
            yield Button("↻ 重新加载", id="reload_cfg")

    def _load(self) -> None:
        # 清空并重新渲染表单（Textual 6.x 无 clear 方法）
        try:
            self.form.remove_children()
        except Exception:
            for child in list(self.form.children):
                try:
                    self.form.remove(child)
                except Exception:
                    pass
        self.inputs.clear()
        cfg = read_kv_config(CONFIG_FILE)
        if not cfg:
            self.form.mount(Static("未找到 oqqwall.config 或为空", classes="hint"))
            return
        # 使用固定顺序渲染；未列出的键按字母序追加
        ordered_keys: list[str] = []
        seen: set[str] = set()
        for key in CONFIG_ORDER:
            if key in cfg and key not in seen:
                ordered_keys.append(key)
                seen.add(key)
        rest = sorted(k for k in cfg.keys() if k not in seen)
        ordered_keys.extend(rest)

        for idx, k in enumerate(ordered_keys):
            v = cfg.get(k, "")
            v_raw = str(v)
            v_low = v_raw.strip().lower()
            tip = CONFIG_TOOLTIPS.get(k, "配置项")
            # 键名 + 输入/开关 + 帮助“?”
            key_label = Label(k, classes="cfg_key")
            help_icon = Label("?", classes="cfg_help")
            row_children = [help_icon, key_label]
            if v_low in ("true", "false"):
                widget = Switch(value=(v_low == "true"), id=f"inp_{k}")
                row_children.extend([widget, Static("", classes="cfg_spacer")])
            else:
                widget = Input(value=v_raw, id=f"inp_{k}")
                row_children.append(widget)
            # 统一设置提示（不同 Textual 版本支持 tooltip 属性）
            try:
                key_label.tooltip = tip
                help_icon.tooltip = tip
                setattr(widget, 'tooltip', tip)
            except Exception:
                pass
            # 顺序调整："?" 在标题左侧；并交替行背景
            row_cls = "cfg_row row-even" if (idx % 2 == 0) else "cfg_row row-odd"
            spacer = Static("", classes="cfg_spacer")
            row = Horizontal(*row_children, classes=row_cls)
            self.inputs[k] = widget
            self.form.mount(row)

    async def on_mount(self) -> None:
        # 延迟到组件完全挂载后再构建子控件，避免 mount 前置检查失败
        self.call_after_refresh(self._load)

    async def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "reload_cfg":
            self._load()
            return
        if event.button.id == "save_cfg":
            data: dict[str, str] = {}
            for k, widget in self.inputs.items():
                try:
                    if isinstance(widget, Switch):
                        data[k] = "true" if widget.value else "false"
                    elif isinstance(widget, Input):
                        data[k] = widget.value
                    else:
                        data[k] = str(getattr(widget, "value", ""))
                except Exception:
                    data[k] = ""
            try:
                write_kv_config(CONFIG_FILE, data)
                self.app.notify("保存成功。", severity="information")
            except Exception as e:
                self.app.notify(f"保存失败: {e}", severity="error")


class GroupConfigPage(Vertical):
    """组配置：可编辑 AcountGroupcfg.json。

    - 顶栏：各组按钮 + “添加组”
    - 可编辑项：mangroupid, mainqqid, mainqq_http_port, watermark_text,
      friend_add_message, max_post_stack, max_image_number_one_post
    - 副账号及端口：成对列表，可增删
    - 快捷回复：指令/回复 成对列表，可增删
    - 保存/重新加载
    """

    def __init__(self):
        super().__init__(id="group_cfg_page")
        self.data: dict = {}
        self.current_group: Optional[str] = None
        self.topbar: Optional[Horizontal] = None
        self.form: Optional[ScrollableContainer] = None
        # 当前组的控件引用，便于 harvest
        self.inputs: dict[str, Input] = {}
        self.minor_pairs: list[tuple[Input, Input]] = []
        self.qr_pairs: list[tuple[Input, Input]] = []
        self.sched_inputs: list[Input] = []
        self.admin_pairs: list[tuple[Input, Input]] = []
        self._topbar_rev: int = 0
        self._form_rev: int = 0
        # 顶栏交互状态
        self._adding_group: bool = False
        self._deleting_group: bool = False
        self._new_group_input: Optional[Input] = None

    def compose(self) -> ComposeResult:
        yield Static("组配置 (AcountGroupcfg.json)", classes="title")
        self.topbar = Horizontal(id="group_topbar")
        yield self.topbar
        self.form = ScrollableContainer(id="group_form")
        yield self.form
        with Horizontal(classes="toolbar"):
            yield Button("💾 保存", id="save_group")
            yield Button("↻ 重新加载", id="reload_group")

    # ---------- 数据加载/保存 ----------
    def _load_data(self) -> None:
        try:
            self.data = json.loads(GROUP_CFG.read_text(encoding="utf-8")) or {}
        except Exception:
            self.data = {}
        if not self.current_group:
            self.current_group = next(iter(self.data.keys()), None)

    def _save_data(self) -> None:
        # 在保存前做校验（规则参考 main.sh）
        errs, warns = self._validate_data(self.data)
        if errs:
            # 展示前若干条错误，阻止保存
            head = errs[:5]
            for m in head:
                self.app.notify(m, severity="error")
            if len(errs) > 5:
                self.app.notify(f"还有 {len(errs)-5} 条错误未显示", severity="error")
            return
        # 有警告但允许保存
        for w in warns[:3]:
            self.app.notify(w, severity="warning")
        try:
            GROUP_CFG.write_text(json.dumps(self.data, ensure_ascii=False, indent=2), encoding="utf-8")
            self.app.notify("已保存组配置。", severity="information")
        except Exception as e:
            self.app.notify(f"保存失败: {e}", severity="error")

    # ---------- 顶栏/表单 渲染 ----------
    def _render_topbar(self) -> None:
        assert self.topbar is not None
        # 保持已有容器，清空子节点（避免重复容器 ID）
        # 使用 remove_children 与回退方案，确保立刻移除旧按钮，避免重复 ID。
        try:
            self.topbar.remove_children()
        except Exception:
            for ch in list(self.topbar.children):
                try:
                    self.topbar.remove(ch)
                except Exception:
                    try:
                        ch.remove()
                    except Exception:
                        pass
        self._topbar_rev += 1
        # 添加组/输入新组名 控件优先显示，避免被顶栏挤出
        if self._adding_group:
            name_inp = Input(placeholder="输入组名(字母/数字/下划线)", id=f"new_group_name__{self._topbar_rev}")
            self._new_group_input = name_inp
            self.topbar.mount(name_inp)
            self.topbar.mount(Button("确认", id=f"confirm_add_group__{self._topbar_rev}"))
            self.topbar.mount(Button("取消", id=f"cancel_add_group__{self._topbar_rev}"))

        # 组按钮
        for g in self.data.keys():
            btn = Button(g, id=f"group_select__{g}__{self._topbar_rev}")
            if g == self.current_group:
                try:
                    btn.add_class("-active")
                except Exception:
                    pass
            self.topbar.mount(btn)
        # 非新建模式下显示“添加组”按钮
        if not self._adding_group:
            self.topbar.mount(Button("＋ 添加组", id=f"add_group__{self._topbar_rev}"))

        # 删除组/确认删除
        if self._deleting_group:
            label = f"确认删除 {self.current_group or ''}"
            self.topbar.mount(Button(label, id=f"confirm_delete_group__{self._topbar_rev}"))
            self.topbar.mount(Button("取消", id=f"cancel_delete_group__{self._topbar_rev}"))
        else:
            self.topbar.mount(Button("🗑 删除组", id=f"delete_group__{self._topbar_rev}"))

    def _render_form(self) -> None:
        assert self.form is not None
        # 清空
        try:
            self.form.remove_children()
        except Exception:
            for ch in list(self.form.children):
                try:
                    self.form.remove(ch)
                except Exception:
                    pass
        self.inputs.clear()
        self.minor_pairs.clear()
        self.qr_pairs.clear()
        self.sched_inputs.clear()
        self.admin_pairs.clear()
        # 版本递增，所有控件 ID 带后缀，避免与未及时移除的旧节点发生 ID 冲突
        self._form_rev += 1

        if not self.current_group or self.current_group not in self.data:
            self.form.mount(Static("未选择组或配置为空。", classes="hint"))
            return
        obj = self.data[self.current_group] or {}

        def row(key: str, label_text: str, default: str = "") -> Input:
            val = str(obj.get(key, default) or "")
            lab = Label(label_text, classes="cfg_key")
            inp = Input(value=val, id=f"inp_{key}__{self._form_rev}")
            self.inputs[key] = inp
            self.form.mount(Horizontal(lab, inp, Static("", classes="cfg_spacer"), classes="cfg_row"))
            return inp

        row("mangroupid", "群号(mangroupid)")
        row("mainqqid", "主账号(mainqqid)")
        row("mainqq_http_port", "主账号端口(mainqq_http_port)")
        row("max_post_stack", "暂存区阈值(max_post_stack)")
        row("max_image_number_one_post", "单贴图数上限")
        row("watermark_text", "水印文本")
        row("friend_add_message", "好友通过私信")

        # 副账号与端口（成对）
        self.form.mount(Static("副账号(qq) 与 端口(一行一对)", classes="title"))
        minors = list(map(str, (obj.get("minorqqid") or [])))
        minor_ports = list(map(str, (obj.get("minorqq_http_port") or [])))
        # 对齐长度
        ln = max(len(minors), len(minor_ports))
        while len(minors) < ln:
            minors.append("")
        while len(minor_ports) < ln:
            minor_ports.append("")
        for i in range(ln):
            qq_inp = Input(value=minors[i], id=f"minorqq_{i}__{self._form_rev}")
            pt_inp = Input(value=minor_ports[i], id=f"minorport_{i}__{self._form_rev}")
            del_btn = Button("删除", id=f"del_minor__{i}__{self._form_rev}")
            self.minor_pairs.append((qq_inp, pt_inp))
            self.form.mount(Horizontal(Label("副账号"), qq_inp, Label("端口"), pt_inp, del_btn, Static("", classes="cfg_spacer"), classes="cfg_row"))
        self.form.mount(Horizontal(Button("＋ 添加副账号", id=f"add_minor__{self._form_rev}"), classes="toolbar"))

        # 快捷回复（指令 -> 文本）
        self.form.mount(Static("快捷回复(指令 -> 文本)", classes="title"))
        qr_dict = obj.get("quick_replies") or {}
        qr_items = list(qr_dict.items())
        for i, (cmd, txt) in enumerate(qr_items):
            c_inp = Input(value=str(cmd), id=f"qrkey_{i}__{self._form_rev}")
            t_inp = Input(value=str(txt), id=f"qrval_{i}__{self._form_rev}")
            del_btn = Button("删除", id=f"del_qr__{i}__{self._form_rev}")
            self.qr_pairs.append((c_inp, t_inp))
            self.form.mount(Horizontal(Label("指令"), c_inp, Label("回复"), t_inp, del_btn, Static("", classes="cfg_spacer"), classes="cfg_row"))
        self.form.mount(Horizontal(Button("＋ 添加快捷回复", id=f"add_qr__{self._form_rev}"), classes="toolbar"))

        # 发送计划（字符串时间 HH:MM 列表）
        self.form.mount(Static("发送计划(send_schedule) - 时间(HH:MM)", classes="title"))
        sched_list = obj.get("send_schedule") or []
        if not isinstance(sched_list, list):
            sched_list = []
        for i, t in enumerate(sched_list):
            ti = Input(value=str(t), id=f"sched_{i}__{self._form_rev}")
            self.sched_inputs.append(ti)
            self.form.mount(Horizontal(Label("时间"), ti, Button("删除", id=f"del_sched__{i}__{self._form_rev}"), Static("", classes="cfg_spacer"), classes="cfg_row"))
        self.form.mount(Horizontal(Button("＋ 添加时间", id=f"add_sched__{self._form_rev}"), classes="toolbar"))

        # 管理员（username/password 列表）
        self.form.mount(Static("管理员(admins) - 用户名/密码(支持 sha256: 前缀)", classes="title"))
        admins = obj.get("admins") or []
        if not isinstance(admins, list):
            admins = []
        for i, adm in enumerate(admins):
            u = Input(value=str((adm or {}).get("username", "")), id=f"admin_u_{i}__{self._form_rev}")
            p = Input(value=str((adm or {}).get("password", "")), id=f"admin_p_{i}__{self._form_rev}")
            self.admin_pairs.append((u, p))
            self.form.mount(Horizontal(Label("用户名"), u, Label("密码"), p, Button("删除", id=f"del_admin__{i}__{self._form_rev}"), Static("", classes="cfg_spacer"), classes="cfg_row"))
        self.form.mount(Horizontal(Button("＋ 添加管理员", id=f"add_admin__{self._form_rev}"), classes="toolbar"))

    # ---------- 事件 ----------
    async def on_mount(self) -> None:
        self._load_data()
        self._render_topbar()
        self._render_form()

    async def on_input_submitted(self, event: Input.Submitted) -> None:
        bid = event.input.id or ""
        # 在新建组模式下，回车等同于点击“确认”
        if self._adding_group and bid.startswith("new_group_name__"):
            # 触发确认逻辑
            name = (event.value or "").strip()
            if not name:
                self.app.notify("组名不能为空。", severity="error")
                return
            if not all(c.isalnum() or c == '_' for c in name):
                self.app.notify("组名仅允许字母、数字和下划线。", severity="error")
                return
            if name in self.data:
                self.app.notify("组名已存在。", severity="error")
                return
            self._harvest_form()
            self.data[name] = {
                "mangroupid":"",
                "mainqqid":"","mainqq_http_port":"",
                "minorqqid":[],"minorqq_http_port":[],
                "admins":[],"max_post_stack":"3","max_image_number_one_post":"18",
                "friend_add_message":"","watermark_text":"",
                "quick_replies":{}
            }
            self.current_group = name
            self._adding_group = False
            self._render_topbar()
            self._render_form()
            return

    def _harvest_form(self) -> None:
        if not self.current_group or self.current_group not in self.data:
            return
        obj = dict(self.data.get(self.current_group) or {})

        def get_val(k: str) -> str:
            w = self.inputs.get(k)
            return w.value if isinstance(w, Input) else str(obj.get(k, ""))

        for k in [
            "mangroupid","mainqqid","mainqq_http_port","max_post_stack",
            "max_image_number_one_post","watermark_text","friend_add_message"
        ]:
            obj[k] = get_val(k)

        # 副账号
        minors: list[str] = []
        minor_ports: list[str] = []
        for (q, p) in self.minor_pairs:
            minors.append(q.value.strip())
            minor_ports.append(p.value.strip())
        obj["minorqqid"] = minors
        obj["minorqq_http_port"] = minor_ports

        # 快捷回复
        qr: dict[str, str] = {}
        for (ck, tv) in self.qr_pairs:
            k = ck.value.strip()
            v = tv.value
            if k:
                qr[k] = v
        obj["quick_replies"] = qr

        # 发送计划
        sched: list[str] = []
        for ti in self.sched_inputs:
            v = ti.value.strip()
            if v:
                sched.append(v)
        obj["send_schedule"] = sched

        # 管理员
        admins: list[dict] = []
        for (u, p) in self.admin_pairs:
            uu = u.value.strip()
            pp = p.value
            if uu:
                admins.append({"username": uu, "password": pp})
        obj["admins"] = admins

        self.data[self.current_group] = obj

    # ---------- 校验 ----------
    def _validate_data(self, data: dict) -> tuple[list[str], list[str]]:
        errors: list[str] = []
        warnings: list[str] = []

        def is_num(s: str) -> bool:
            return s.isdigit()

        # 唯一性集合
        mainqqids: set[str] = set()
        all_minor_ids: set[str] = set()
        http_ports: set[str] = set()

        # 审核指令冲突列表
        audit_cmds = {"是","否","匿","等","删","拒","立即","刷新","重渲染","扩列审查","评论","回复","展示","拉黑"}

        for group in data.keys():
            if not group or not all(c.isalnum() or c == '_' for c in group):
                errors.append(f"错误：组名 '{group}' 含非法字符，仅允许字母、数字和下划线。")
                continue
            obj = data.get(group) or {}
            mangroupid = str(obj.get("mangroupid") or "")
            mainqqid = str(obj.get("mainqqid") or "")
            main_port = str(obj.get("mainqq_http_port") or "")
            minor_ids = [str(x or "") for x in (obj.get("minorqqid") or [])]
            minor_ports = [str(x or "") for x in (obj.get("minorqq_http_port") or [])]

            # 必填 & 数字
            if not is_num(mangroupid):
                errors.append(f"错误：在 {group} 中，mangroupid 缺失或不是有效的数字！")
            if not is_num(mainqqid):
                errors.append(f"错误：在 {group} 中，mainqqid 缺失或不是有效的数字！")
            else:
                if mainqqid in mainqqids:
                    errors.append(f"错误：mainqqid {mainqqid} 在多个组中重复！")
                mainqqids.add(mainqqid)
            if not is_num(main_port):
                errors.append(f"错误：在 {group} 中，mainqq_http_port 缺失或不是有效的数字！")
            else:
                if main_port in http_ports:
                    errors.append(f"错误：mainqq_http_port {main_port} 在多个组中重复！")
                http_ports.add(main_port)

            # 副账号校验
            if not minor_ids:
                warnings.append(f"警告：在 {group} 中，minorqqid 为空。")
            for mid in minor_ids:
                if mid and not is_num(mid):
                    errors.append(f"错误：在 {group} 中，minorqqid 包含非数字值：{mid}")
                elif mid:
                    if mid in all_minor_ids or mid in mainqqids:
                        errors.append(f"错误：minorqqid {mid} 在多个组中重复！")
                    all_minor_ids.add(mid)
            if not minor_ports:
                warnings.append(f"警告：在 {group} 中，minorqq_http_port 为空。")
            for mp in minor_ports:
                if mp and not is_num(mp):
                    errors.append(f"错误：在 {group} 中，minorqq_http_port 包含非数字值：{mp}")
                elif mp:
                    if mp in http_ports:
                        errors.append(f"错误：minorqq_http_port {mp} 在多个组中重复！")
                    http_ports.add(mp)
            if len(minor_ids) != len(minor_ports):
                errors.append(f"错误：在 {group} 中，minorqqid 的数量 ({len(minor_ids)}) 与 minorqq_http_port 的数量 ({len(minor_ports)}) 不匹配。")

            # max_* 数字（可空）
            for key in ("max_post_stack","max_image_number_one_post"):
                val = str(obj.get(key) or "")
                if val and not is_num(val):
                    errors.append(f"错误：在 {group} 中，{key} 存在但不是纯数字：{val}")

            # friend_add_message 与 watermark_text（可空，若存在必须是字符串）
            for key in ("friend_add_message","watermark_text"):
                v = obj.get(key, None)
                if v is not None and not isinstance(v, str):
                    errors.append(f"错误：在 {group} 中，{key} 必须是字符串或为空。")

            # send_schedule（可空；若存在必须为字符串数组，元素 HH:MM）
            sched = obj.get("send_schedule", None)
            if sched is not None:
                if not isinstance(sched, list):
                    errors.append(f"错误：在 {group} 中，send_schedule 必须是数组。")
                else:
                    import re
                    pat = re.compile(r"^([01]?[0-9]|2[0-3]):[0-5][0-9]$")
                    for t in sched:
                        if t and (not isinstance(t, str) or not pat.match(t)):
                            errors.append(f"错误：在 {group} 中，send_schedule 含非法时间：{t}（应为 HH:MM）")

            # quick_replies（可空；若存在必须对象；键/值为字符串；不冲突；内容非空）
            qr = obj.get("quick_replies", None)
            if qr is not None:
                if not isinstance(qr, dict):
                    errors.append(f"错误：在 {group} 中，quick_replies 必须是对象。")
                else:
                    for k, v in qr.items():
                        if not isinstance(k, str):
                            errors.append(f"错误：在 {group} 中，快捷回复键必须是字符串。")
                            continue
                        if k in audit_cmds:
                            errors.append(f"错误：在 {group} 中，快捷回复指令 '{k}' 与审核指令冲突。")
                        if not isinstance(v, str):
                            errors.append(f"错误：在 {group} 中，快捷回复 '{k}' 的值必须是字符串。")
                        if isinstance(v, str) and not v.strip():
                            errors.append(f"错误：在 {group} 中，快捷回复 '{k}' 内容不能为空。")

        return errors, warnings

    async def on_button_pressed(self, event: Button.Pressed) -> None:
        bid = event.button.id or ""
        if bid == "reload_group":
            self._load_data()
            self._render_topbar()
            self._render_form()
            return
        if bid == "save_group":
            self._harvest_form()
            self._save_data()
            return
        if bid.startswith("add_group"):
            # 进入新建模式：展示输入 + 确认/取消
            self._adding_group = True
            self._deleting_group = False
            self._render_topbar()
            return
        if bid.startswith("cancel_add_group"):
            self._adding_group = False
            self._render_topbar()
            return
        if bid.startswith("confirm_add_group"):
            # 读取输入的新组名
            name = ""
            try:
                if isinstance(self._new_group_input, Input):
                    name = (self._new_group_input.value or "").strip()
            except Exception:
                name = ""
            if not name:
                self.app.notify("组名不能为空。", severity="error")
                return
            # 校验：仅允许字母/数字/下划线
            if not all(c.isalnum() or c == '_' for c in name):
                self.app.notify("组名仅允许字母、数字和下划线。", severity="error")
                return
            if name in self.data:
                self.app.notify("组名已存在。", severity="error")
                return
            # 创建组
            self._harvest_form()
            self.data[name] = {
                "mangroupid":"",
                "mainqqid":"","mainqq_http_port":"",
                "minorqqid":[],"minorqq_http_port":[],
                "admins":[],"max_post_stack":"3","max_image_number_one_post":"18",
                "friend_add_message":"","watermark_text":"",
                "quick_replies":{}
            }
            self.current_group = name
            self._adding_group = False
            self._render_topbar()
            self._render_form()
            return
        if bid.startswith("group_select__"):
            self._harvest_form()
            try:
                self.current_group = bid.split("__")[1]
            except Exception:
                self.current_group = bid.replace("group_select__","",1)
            self._adding_group = False
            self._deleting_group = False
            self._render_topbar()
            self._render_form()
            return
        if bid.startswith("delete_group"):
            if not self.current_group:
                self.app.notify("没有选择任何组。", severity="warning")
                return
            # 进入确认删除模式
            self._deleting_group = True
            self._adding_group = False
            self._render_topbar()
            return
        if bid.startswith("cancel_delete_group"):
            self._deleting_group = False
            self._render_topbar()
            return
        if bid.startswith("confirm_delete_group"):
            if not self.current_group:
                self._deleting_group = False
                self._render_topbar()
                return
            g = self.current_group
            # 删除并选择下一个组
            try:
                self.data.pop(g, None)
            except Exception:
                pass
            self.current_group = next(iter(self.data.keys()), None)
            self._deleting_group = False
            self._render_topbar()
            self._render_form()
            return
        if bid.startswith("add_minor"):
            self._harvest_form()
            obj = self.data.get(self.current_group, {})
            obj.setdefault("minorqqid", []).append("")
            obj.setdefault("minorqq_http_port", []).append("")
            self._render_form()
            return
        if bid.startswith("del_minor__"):
            self._harvest_form()
            parts = bid.split("__")
            idx = int(parts[1]) if len(parts) > 1 else -1
            obj = self.data.get(self.current_group, {})
            qqs = obj.get("minorqqid", [])
            pts = obj.get("minorqq_http_port", [])
            if 0 <= idx < len(qqs):
                qqs.pop(idx)
            if 0 <= idx < len(pts):
                pts.pop(idx)
            obj["minorqqid"], obj["minorqq_http_port"] = qqs, pts
            self._render_form()
            return
        if bid.startswith("add_qr"):
            self._harvest_form()
            obj = self.data.get(self.current_group, {})
            qrd = obj.get("quick_replies", {})
            # 添加一个空占位，避免键冲突
            n=1
            newk = f"新指令{n}"
            while newk in qrd:
                n+=1
                newk = f"新指令{n}"
            qrd[newk] = "回复内容"
            obj["quick_replies"] = qrd
            self._render_form()
            return
        if bid.startswith("del_qr__"):
            self._harvest_form()
            parts = bid.split("__")
            idx = int(parts[1]) if len(parts) > 1 else -1
            obj = self.data.get(self.current_group, {})
            qrd = obj.get("quick_replies", {})
            items = list(qrd.items())
            if 0 <= idx < len(items):
                k,_ = items[idx]
                qrd.pop(k, None)
            obj["quick_replies"] = qrd
            self._render_form()
            return
        if bid.startswith("add_sched"):
            self._harvest_form()
            obj = self.data.get(self.current_group, {})
            lst = obj.get("send_schedule") or []
            if not isinstance(lst, list):
                lst = []
            lst.append("")
            obj["send_schedule"] = lst
            self._render_form()
            return
        if bid.startswith("del_sched__"):
            self._harvest_form()
            parts = bid.split("__")
            idx = int(parts[1]) if len(parts) > 1 else -1
            obj = self.data.get(self.current_group, {})
            lst = obj.get("send_schedule") or []
            if isinstance(lst, list) and 0 <= idx < len(lst):
                lst.pop(idx)
            obj["send_schedule"] = lst
            self._render_form()
            return
        if bid.startswith("add_admin"):
            self._harvest_form()
            obj = self.data.get(self.current_group, {})
            admins = obj.get("admins") or []
            if not isinstance(admins, list):
                admins = []
            admins.append({"username":"","password":""})
            obj["admins"] = admins
            self._render_form()
            return
        if bid.startswith("del_admin__"):
            self._harvest_form()
            parts = bid.split("__")
            idx = int(parts[1]) if len(parts) > 1 else -1
            obj = self.data.get(self.current_group, {})
            admins = obj.get("admins") or []
            if isinstance(admins, list) and 0 <= idx < len(admins):
                admins.pop(idx)
            obj["admins"] = admins
            self._render_form()
            return


class LogsPage(Vertical):
    """日志查看页面。"""
    def __init__(self):
        super().__init__(id="logs_page")
        self.textlog = LogWidget(highlight=False, wrap=False, id="log_view")
        self.follow = True
        self.current_file: Optional[Path] = None
        self.tail_task: Optional[asyncio.Task] = None
        self.state_path: Path = ROOT / "cache" / "tui_state.json"

    def compose(self) -> ComposeResult:
        yield Static("Log 查看", classes="title")
        with Horizontal(classes="toolbar"):
            yield Button("⟳ 刷新文件列表", id="refresh_logs")
            yield Button("▶ 跟随" if self.follow else "■ 暂停跟随", id="toggle_follow")
        self.selector = SelectionList(id="log_selector")
        yield self.selector
        yield self.textlog

    async def on_mount(self) -> None:
        await self.refresh_files()
        # 尝试恢复上次查看的日志
        try:
            state = self._load_state()
            # 恢复跟随状态
            follow = state.get("follow") if isinstance(state, dict) else None
            if isinstance(follow, bool):
                self.follow = follow
                try:
                    btn = self.query_one("#toggle_follow", Button)
                    btn.label = "▶ 跟随" if self.follow else "■ 暂停跟随"
                except Exception:
                    pass
            # 恢复最后一次查看的日志
            last = state.get("last_log_path") if isinstance(state, dict) else None
            if last and Path(last).is_file():
                await self.switch_to(Path(last))
            else:
                # 默认打开主日志（如果存在）
                default = ROOT / "OQQWallmsgserv.log"
                if default.exists():
                    await self.switch_to(default)
        except Exception:
            pass

    async def refresh_files(self) -> None:
        self.selector.clear_options()
        files: list[Path] = []
        # 常见日志
        for p in [ROOT / "OQQWallmsgserv.log", ROOT / "NapCatlog"]:
            if p.exists():
                files.append(p)
        # logs 目录
        log_dir = ROOT / "logs"
        if log_dir.is_dir():
            for p in sorted(log_dir.glob("*.log")):
                files.append(p)
        # 去重并填充
        seen = set()
        for p in files:
            if str(p) in seen:
                continue
            seen.add(str(p))
            # SelectionList 接收 (prompt, value) 元组
            self.selector.add_option((str(p), str(p)))

    async def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "refresh_logs":
            await self.refresh_files()
        elif event.button.id == "toggle_follow":
            self.follow = not self.follow
            event.button.label = "▶ 跟随" if self.follow else "■ 暂停跟随"
            try:
                self._save_state({"follow": self.follow})
            except Exception:
                pass

    async def on_option_list_option_selected(self, event) -> None:
        """处理日志文件选择（适配 Textual 6.x 的 OptionList 事件）。"""
        try:
            # 仅响应本页面的选择器
            if getattr(event, "control", None) is not self.selector:
                return
            idx = int(getattr(event, "option_index"))
            opt = self.selector.get_option_at_index(idx)
            path = Path(str(opt.prompt))
        except Exception:
            return
        await self.switch_to(path)

    async def switch_to(self, path: Path) -> None:
        # 取消之前的 tail
        if self.tail_task and not self.tail_task.done():
            self.tail_task.cancel()
        self.current_file = path
        self.textlog.clear()
        # 读取末尾若干行
        try:
            lines = tail_lines(path, 500)
            for line in lines:
                self.textlog.write(line.rstrip("\n"))
        except Exception as e:
            self.textlog.write(f"打开失败: {e}")
            return
        # 保存状态
        try:
            self._save_state({"last_log_path": str(path)})
        except Exception:
            pass
        # 启动追踪
        self.tail_task = asyncio.create_task(self._tail_loop())

    async def _tail_loop(self) -> None:
        if not self.current_file:
            return
        path = self.current_file
        try:
            with path.open("r", encoding="utf-8", errors="ignore") as f:
                f.seek(0, os.SEEK_END)
                while True:
                    where = f.tell()
                    line = f.readline()
                    if not line:
                        await asyncio.sleep(0.5)
                        f.seek(where)
                    else:
                        if self.follow:
                            self.textlog.write(line.rstrip("\n"))
        except asyncio.CancelledError:
            return
        except Exception as e:
            self.textlog.write(f"跟随错误: {e}")

    def _load_state(self) -> dict:
        try:
            if self.state_path.is_file():
                return json.loads(self.state_path.read_text(encoding="utf-8")) or {}
        except Exception:
            return {}
        return {}

    def _save_state(self, data: dict) -> None:
        try:
            self.state_path.parent.mkdir(parents=True, exist_ok=True)
            # 合并已有状态，避免覆盖其他字段
            current = {}
            if self.state_path.exists():
                try:
                    current = json.loads(self.state_path.read_text(encoding="utf-8")) or {}
                except Exception:
                    current = {}
            current.update(data)
            self.state_path.write_text(json.dumps(current, ensure_ascii=False), encoding="utf-8")
        except Exception:
            pass


def tail_lines(path: Path, n: int) -> list[str]:
    """简易 tail -n 实现。"""
    try:
        with path.open("rb") as f:
            f.seek(0, os.SEEK_END)
            end = f.tell()
            size = end
            block = 4096
            data = b""
            while size > 0 and data.count(b"\n") <= n:
                step = min(block, size)
                size -= step
                f.seek(size)
                data = f.read(step) + data
            text = data.decode("utf-8", errors="ignore")
            lines = text.splitlines()
            return lines[-n:]
    except Exception:
        return []


class MessageScreen(Static):
    """简易信息提示。"""
    DEFAULT_CSS = """
    MessageScreen { padding: 1 2; border: solid #666; background: #111111; color: #dddddd }
    """

    def __init__(self, message: str):
        super().__init__(message)


class OQQWallTUI(App):
    CSS = """
    Screen { layout: vertical; }
    #root_layout { height: 1fr; }
    .title { content-align: left middle; height: 3; padding: 0 1; background: $surface; color: $text; }
    .toolbar { height: auto; padding: 0 1; }
    .status_row { height: auto; padding: 0 1; }
    #status_block { height: auto; padding: 0 1; }
    .cards { height: auto; padding: 1; }
    .card { padding: 1; border: heavy $primary; width: 1fr; min-height: 3; content-align: left middle; }
    #left_nav { width: 24; border: tall $primary; }
    #content { border: tall $primary; }
    .cfg_row { height: auto; min-height: 3; padding: 0 1; width: 1fr; background: $panel; content-align: left middle; }
    .cfg_row.row-odd { background: $panel-darken-1; }
    .cfg_key { width: 28; text-style: bold; height: 3; content-align: left middle; }
    .cfg_help { width: 3; text-style: bold; height: 3; content-align: center middle; color: $accent; }
    .cfg_spacer { width: 1fr; }
    .cfg_row Input { background: transparent; width: 1fr; }
    .cfg_row Switch { background: transparent; }
    #log_view { height: 1fr; border: tall $accent; }
    #log_selector { height: 10; }
    #global_cfg_form { height: 1fr; width: 1fr; }
    #group_topbar { height: auto; padding: 0 1; }
    #group_topbar Input { width: 28; min-width: 16; }
    #group_topbar Button { width: auto; }
    #group_form { height: 1fr; }
    """

    BINDINGS = [
        Binding("q", "quit", "退出"),
        Binding("ctrl+c", "quit", show=False),
    ]

    def __init__(self):
        super().__init__()
        self.proc = ProcHandle()
        self.home_page = HomePage(self.proc)
        self.global_page = GlobalConfigPage()
        self.group_page = GroupConfigPage()
        self.logs_page = LogsPage()
        self._proc_forward_task: Optional[asyncio.Task] = None

    def compose(self) -> ComposeResult:
        yield Header(show_clock=True)
        with Horizontal(id="root_layout"):
            with Vertical(id="left_nav"):
                self.nav = ListView(
                    ListItem(Label("主页"), id="nav_home"),
                    ListItem(Label("全局配置"), id="nav_global"),
                    ListItem(Label("组配置"), id="nav_group"),
                    ListItem(Label("Log"), id="nav_logs"),
                )
                yield self.nav
            with Container(id="content"):
                self.content_container = Container(self.home_page)
                yield self.content_container
        yield Footer()

    async def on_mount(self) -> None:
        self.set_focus(self.nav)

    async def on_list_view_selected(self, event: ListView.Selected) -> None:
        if event.item.id == "nav_home":
            await self._switch_to(self.home_page)
        elif event.item.id == "nav_global":
            await self._switch_to(self.global_page)
        elif event.item.id == "nav_group":
            await self._switch_to(self.group_page)
        elif event.item.id == "nav_logs":
            await self._switch_to(self.logs_page)

    async def _switch_to(self, widget) -> None:
        # Textual 6.x: Container 无 clear(); 使用 remove_children()+mount()
        try:
            self.content_container.remove_children()
        except Exception:
            # 兜底：逐个移除
            for child in list(self.content_container.children):
                try:
                    self.content_container.remove(child)
                except Exception:
                    pass
        self.content_container.mount(widget)

    def forward_process_output(self, proc: subprocess.Popen) -> None:
        """将 main.sh 的输出转发到日志页面（若在 Log 页会看到；否则缓存直到打开）。"""
        async def _pump():
            try:
                assert proc.stdout is not None
                while True:
                    line = await asyncio.get_event_loop().run_in_executor(None, proc.stdout.readline)
                    if not line:
                        break
                    if self.logs_page:
                        self.logs_page.textlog.write(line.rstrip("\n"))
            except Exception:
                pass
        if self._proc_forward_task and not self._proc_forward_task.done():
            self._proc_forward_task.cancel()
        self._proc_forward_task = asyncio.create_task(_pump())


def main() -> None:
    if sys.platform != "linux":
        print("此 TUI 仅适配 Linux 终端。", file=sys.stderr)
        sys.exit(1)
    try:
        from textual import __version__ as _  # noqa: F401
    except Exception:
        print("未找到 textual，请先安装：pip install textual", file=sys.stderr)
        sys.exit(2)
    OQQWallTUI().run()


if __name__ == "__main__":
    main()
