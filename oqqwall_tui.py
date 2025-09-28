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
            state, msg = await fetch_napcat_status()
            self.napcat_msg = msg
            uid = await fetch_napcat_login_user_id()
            suffix = f"（登录: {uid}）" if uid else ""
            color = _state_color(state)
            self.napcat_label.update(Text(f"NapCat: {msg}{suffix}", style=color))
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
        ids = get_all_qq_ids()
        # 默认全部待检测
        status_map = {i: "待检测" for i in ids}
        uid = await fetch_napcat_login_user_id()
        # 如果拿到当前登录账号，则标记其状态
        if uid:
            status_map[uid] = "在线且健康"
        # 拼接显示，用中文分号分隔
        if status_map:
            parts = [f"qq {k}:{v}" for k, v in status_map.items()]
            text = "；".join(parts)
        else:
            text = "无配置账号"
        self.qq_label.update(Text(text, style="green" if uid else "grey50"))

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
        for idx, k in enumerate(sorted(cfg.keys())):
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
    """组配置：展示 AcountGroupcfg.json 概览。"""
    def __init__(self):
        super().__init__(id="group_cfg_page")
        self.table: Optional[DataTable] = None

    def compose(self) -> ComposeResult:
        yield Static("组配置 (AcountGroupcfg.json)", classes="title")
        tbl = DataTable(id="group_table")
        tbl.add_columns("组名", "主账号", "次账号数量")
        self.table = tbl
        yield tbl
        with Horizontal(classes="toolbar"):
            yield Button("↻ 重新加载", id="reload_group")

    def _load(self) -> None:
        if not self.table:
            return
        self.table.clear()
        try:
            data = json.loads(GROUP_CFG.read_text(encoding="utf-8"))
        except Exception as e:
            self.table.add_row("加载失败", str(e), "-")
            return
        for g, obj in data.items():
            mainqq = str(obj.get("mainqqid", ""))
            minors = obj.get("minorqqid") or []
            self.table.add_row(g, mainqq, str(len(minors)))

    async def on_mount(self) -> None:
        self.call_after_refresh(self._load)

    async def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "reload_group":
            self._load()


class LogsPage(Vertical):
    """日志查看页面。"""
    def __init__(self):
        super().__init__(id="logs_page")
        self.textlog = LogWidget(highlight=False, wrap=False, id="log_view")
        self.follow = True
        self.current_file: Optional[Path] = None
        self.tail_task: Optional[asyncio.Task] = None

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
