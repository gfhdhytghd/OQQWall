#!/usr/bin/env python3
# -*- coding: utf-8 -*-

# 导入必要的模块
import argparse
import http.server
import json
import os
import queue
import re
import threading
import time
from typing import Any, Dict, List, Optional
import requests

# -----------------------------
# 工具函数
# -----------------------------
def dict_contains(big: Dict[str, Any], small: Dict[str, Any]) -> bool:
    """检查字典 'big' 是否包含字典 'small'（递归子集匹配）。"""
    for k, v in small.items():
        if k not in big:
            return False
        if isinstance(v, dict) and isinstance(big[k], dict):
            if not dict_contains(big[k], v):
                return False
        else:
            if big[k] != v:
                return False
    return True

def wait_until(cond_fn, timeout=5.0, interval=0.05):
    """等待直到 cond_fn() 返回 True 或超时。"""
    deadline = time.time() + timeout
    while time.time() < deadline:
        if cond_fn():
            return True
        time.sleep(interval)
    return False

# 录制模式
VOLATILE_KEYS_DEFAULT = {"time", "timestamp", "tag", "id", "trace_id"}
SENSITIVE_KEYS_DEFAULT = {"skey", "p_skey", "pt4_token", "uin", "p_uin",
                          "qzone_check", "RK", "ptcz", "pt2gguin"}

def prune_dict(d, drop_keys):
    if not isinstance(d, dict):
        return d
    out = {}
    for k, v in d.items():
        if k in drop_keys:
            continue
        if isinstance(v, dict):
            v = prune_dict(v, drop_keys)
        out[k] = v
    return out

def pick_subset(d, keys):
    if not isinstance(d, dict):
        return d
    out = {}
    for k in keys:
        if k in d:
            out[k] = d[k]
    return out

def summarize_napcat(rec):
    # 仅保留核心断言所需内容
    return {"path": rec.get("path", "").split("?")[0],
            "query": (rec.get("path", "").split("?", 1)[1] if "?" in rec.get("path","") else "")}

def build_recorded_plan(original_steps,
                        napcat_records,
                        qzone_inputs,
                        qzone_outputs,
                        *,
                        volatile_keys=VOLATILE_KEYS_DEFAULT,
                        sensitive_keys=SENSITIVE_KEYS_DEFAULT,
                        qzone_subset_keys=None,
                        link_window=2.0):
    """
    将观察到的 napcat/qzone 结果写回每个 step 的 expect/expect_qzone_in/expect_qzone_out。
    简单的时间窗口关联：假定 each step 的输出会在 step 发送后的 link_window 秒内产生。
    """
    now = time.time()
    # 给每条记录打一个粗时间戳（本脚本里没有记录精确时间，使用列表顺序近似）
    # 我们按“先来先配对”：每个 step 消费掉队列的下一条输出。
    napcat_queue = napcat_records[:]          # list of dict
    qzone_in_queue = qzone_inputs[:]          # list of dict
    qzone_out_queue = qzone_outputs[:]        # list of str

    recorded = []
    for step in original_steps:
        new_step = {k: v for k, v in step.items() if k not in ("expect","expect_qzone_in","expect_qzone_out")}
        # 关联 Napcat：取下一条
        if napcat_queue:
            n = napcat_queue.pop(0)
            new_step["expect"] = summarize_napcat(n)

        # 关联 QZone IN：取下一条并做裁剪/脱敏
        if qzone_in_queue:
            qin = qzone_in_queue.pop(0)
            # 屏蔽敏感+易变
            qin_pruned = prune_dict(qin, volatile_keys | sensitive_keys)
            if qzone_subset_keys:
                qin_pruned = pick_subset(qin_pruned, set(qzone_subset_keys))
            new_step["expect_qzone_in"] = qin_pruned

        # 关联 QZone OUT：取下一条
        if qzone_out_queue:
            qout = qzone_out_queue.pop(0)
            new_step["expect_qzone_out"] = qout

        recorded.append(new_step)
    return recorded


# -----------------------------
# Napcat HTTP 模拟器（捕获输入/输出）
# -----------------------------
class CaptureHandler(http.server.BaseHTTPRequestHandler):
    # 处理 GET 请求
    def do_GET(self):
        length = int(self.headers.get('Content-Length', 0))
        body = self.rfile.read(length) if length else b''
        record = {
            'method': 'GET',
            'path': self.path,
            'body': body.decode('utf-8', errors='ignore')
        }
        self.server.records.append(record)
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b'ok')

    # 处理 POST 请求
    def do_POST(self):
        length = int(self.headers.get('Content-Length', 0))
        body = self.rfile.read(length) if length else b''
        record = {
            'method': 'POST',
            'path': self.path,
            'body': body.decode('utf-8', errors='ignore')
        }
        self.server.records.append(record)
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b'ok')

    # 禁用日志输出
    def log_message(self, fmt, *args):
        return

class ThreadedHTTPServer(http.server.ThreadingHTTPServer):
    # 初始化 HTTP 服务器，记录请求
    def __init__(self, addr, handler, records: list):
        super().__init__(addr, handler)
        self.records = records

def run_server(port, records):
    """启动 HTTP 服务器并以线程方式运行。"""
    srv = ThreadedHTTPServer(('0.0.0.0', port), CaptureHandler, records)
    t = threading.Thread(target=srv.serve_forever, daemon=True)
    t.start()
    return srv

# -----------------------------
# QZone 管道模拟器
# -----------------------------
class QzonePipeMock:
    """
    模拟 qzone-serv-pipe：
      - 从 ./qzone_in_fifo 读取 JSON
      - 将其追加到 inputs 列表
      - 将回复字符串写入 ./qzone_out_fifo（默认：'success'）
      - 捕获写入的回复以便断言
    """
    def __init__(self, path_in='./qzone_in_fifo', path_out='./qzone_out_fifo', default_reply='success'):
        self.path_in = path_in
        self.path_out = path_out
        self.default_reply = default_reply
        self.inputs: List[Dict[str, Any]] = []
        self.outputs: List[str] = []
        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._reply_queue: "queue.Queue[Optional[str]]" = queue.Queue()

    def ensure_fifos(self):
        """确保 FIFO 文件存在。"""
        if not os.path.exists(self.path_in):
            os.mkfifo(self.path_in)
        if not os.path.exists(self.path_out):
            os.mkfifo(self.path_out)

    def start(self):
        """启动模拟器线程。"""
        self.ensure_fifos()
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()

    def stop(self):
        """停止模拟器线程。"""
        self._stop.set()
        # 尝试以非阻塞模式打开 FIFO，以解除阻塞的读取操作
        try:
            fd = os.open(self.path_in, os.O_WRONLY | os.O_NONBLOCK)
            os.close(fd)
        except Exception:
            pass

    def set_next_reply(self, reply: Optional[str]):
        """设置下一个写入到 out FIFO 的回复。如果为 None，则使用默认回复。"""
        self._reply_queue.put(reply)

    def _write_out(self, text: str):
        """向 out FIFO 写入文本。"""
        with open(self.path_out, 'w') as pipe:
            pipe.write(text)
            pipe.flush()
        self.outputs.append(text)

    def _loop(self):
        """主循环，处理 FIFO 的读写操作。"""
        while not self._stop.is_set():
            try:
                # 阻塞直到有人打开写入（OQQWall），然后我们打开读取
                with open(self.path_in, 'r') as fifo:
                    data = fifo.read()
                data = (data or "").strip()
                if not data:
                    continue
                # 尝试解析 JSON
                try:
                    obj = json.loads(data)
                    self.inputs.append(obj)
                except Exception:
                    # 记录原始文本以便排查问题
                    self.inputs.append({"__raw__": data})

                # 选择回复（允许每次调用覆盖）
                reply = self.default_reply
                try:
                    item = self._reply_queue.get_nowait()
                    if item is not None:
                        reply = item
                except queue.Empty:
                    pass

                self._write_out(reply)
            except FileNotFoundError:
                # FIFO 被删除？重新创建
                self.ensure_fifos()
                time.sleep(0.1)
            except Exception:
                time.sleep(0.05)

# -----------------------------
# 测试计划执行器
# -----------------------------
def run_plan(plan_path: str, target_port: int) -> List[dict]:
    """执行测试计划并返回期望值列表。"""
    with open(plan_path, 'r', encoding='utf-8') as f:
        plan = json.load(f)

    expectations = []
    for step in plan:
        delay = step.get('delay', 0)
        if delay:
            time.sleep(delay)

        # 对于 qzone_out 立即回复覆盖
        qzone_reply = step.get('qzone_reply')
        if qzone_reply is not None:
            QZONE.set_next_reply(qzone_reply)

        inp = step.get('input', {})
        if inp:
            try:
                requests.post(f'http://127.0.0.1:{target_port}', json=inp, timeout=3)
            except Exception as e:
                print('发送失败', e)

        exp = {}
        if 'expect' in step:
            exp['napcat'] = step['expect']
        if 'expect_qzone_in' in step:
            exp['qzone_in'] = step['expect_qzone_in']
        if 'expect_qzone_out' in step:
            exp['qzone_out'] = step['expect_qzone_out']
        if exp:
            expectations.append(exp)

    return expectations

def check_expectations(expectations: List[dict], napcat_records: List[dict],
                       qzone_inputs: List[dict], qzone_outputs: List[str],
                       strict_qzone=False) -> bool:
    """检查实际结果是否符合期望值。"""
    ok = True

    # --- 检查 Napcat HTTP 期望值（路径+查询包含） ---
    for exp in expectations:
        napcat_exp = exp.get('napcat')
        if napcat_exp:
            found = False
            for rec in napcat_records:
                path = rec.get('path') or ''
                if path.startswith(napcat_exp.get('path', '')) and napcat_exp.get('query', '') in path:
                    found = True
                    break
            if not found:
                ok = False
                print('[失败] Napcat 期望值未满足:', napcat_exp)

    # --- 检查 QZone IN（OQQWall 写入 qzone_in_fifo 的内容） ---
    for exp in expectations:
        qin = exp.get('qzone_in')
        if qin is None:
            continue
        matched = False
        for item in qzone_inputs:
            if strict_qzone:
                # 严格模式：完全字典相等
                if isinstance(item, dict) and item == qin:
                    matched = True
                    break
            else:
                # 子集匹配
                if isinstance(item, dict) and dict_contains(item, qin):
                    matched = True
                    break
        if not matched:
            ok = False
            print('[失败] QZone IN 期望值未满足:', qin)
            print('       捕获到的:', qzone_inputs)

    # --- 检查 QZone OUT（模拟器写入 qzone_out_fifo 的内容） ---
    for exp in expectations:
        qout = exp.get('qzone_out')
        if qout is None:
            continue
        matched = False
        for s in qzone_outputs:
            if isinstance(qout, str):
                if s == qout:
                    matched = True
                    break
            elif isinstance(qout, dict):
                # 支持 {"regex": "pattern"}
                pattern = qout.get('regex')
                if pattern and re.search(pattern, s):
                    matched = True
                    break
        if not matched:
            ok = False
            print('[失败] QZone OUT 期望值未满足:', qout)
            print('       捕获到的:', qzone_outputs)

    return ok


# -----------------------------
# 主函数
# -----------------------------
def main():
    # 解析命令行参数
    parser = argparse.ArgumentParser()
    parser.add_argument('--in-port', type=int, required=True, help='OQQWall serv.py 监听端口')
    parser.add_argument('--out-port', type=int, required=True, help='Napcat HTTP 服务器端口 OQQWall 将调用')
    parser.add_argument('--plan', default='tests/test_plan.json')
    parser.add_argument('--strict-qzone', action='store_true', help='对 expect_qzone_in 使用严格相等性')
    parser.add_argument('--timeout', type=float, default=1.0, help='计划执行后的稳定时间（秒）')
    parser.add_argument('--record', action='store_true',help='Record observed outputs into a new plan file')
    parser.add_argument('--record-file', default='tests/recorded_plan.json',help='Where to write the recorded plan')
    parser.add_argument('--record-qzone-keys', default='text,image',help='Comma-separated keys to keep as expect_qzone_in subset (leave empty to keep all)')
    parser.add_argument('--record-drop-volatile', default='time,timestamp,tag,id,trace_id',help='Comma-separated volatile keys to drop from qzone_in')
    parser.add_argument('--record-drop-sensitive', default='skey,p_skey,pt4_token,uin,p_uin,qzone_check,RK,ptcz,pt2gguin',help='Comma-separated sensitive keys to drop from qzone_in')
    parser.add_argument('--link-window', type=float, default=2.0,help='Time window to associate outputs to steps (greedy)')
    args = parser.parse_args()

    # 启动 Napcat 输入/输出捕获服务器
    out_records: List[dict] = []
    in_records: List[dict] = []  # 保留以便你也想捕获发往 serv 的请求（很少需要）
    out_server = run_server(args.out_port, out_records)
    in_server = run_server(args.in_port, in_records)

    # 启动 QZone 管道模拟器
    global QZONE
    QZONE = QzonePipeMock(default_reply='success')
    QZONE.start()

    # 执行测试计划
    expectations = run_plan(args.plan, args.in_port)

    # 等待稳定
    time.sleep(args.timeout)

    # 关闭 HTTP 服务器
    out_server.shutdown()
    in_server.shutdown()

    # 评估测试结果
    success = check_expectations(
        expectations=expectations,
        napcat_records=out_records,
        qzone_inputs=QZONE.inputs,
        qzone_outputs=QZONE.outputs,
        strict_qzone=args.strict_qzone
    )
    QZONE.stop()
    # ---- 录制模式：把观察到的结果写回新的 plan 文件 ----
    if args.record:
        subset_keys = [k.strip() for k in args.record_qzone_keys.split(",") if k.strip()] \
                    if args.record_qzone_keys is not None else None
        drop_vol = set([k.strip() for k in args.record_drop_volatile.split(",") if k.strip()])
        drop_sens = set([k.strip() for k in args.record_drop_sensitive.split(",") if k.strip()])
        try:
            with open(args.plan, 'r', encoding='utf-8') as f:
                orig_steps = json.load(f)
        except Exception:
            # 也支持“无 plan 录制”：用 input 为空的空步骤承接输出
            orig_steps = [{} for _ in range(max(len(out_records), len(QZONE.inputs), len(QZONE.outputs)))]

        recorded = build_recorded_plan(
            orig_steps, out_records, QZONE.inputs, QZONE.outputs,
            volatile_keys=drop_vol, sensitive_keys=drop_sens,
            qzone_subset_keys=subset_keys, link_window=args.link_window
        )
        with open(args.record_file, 'w', encoding='utf-8') as f:
            json.dump(recorded, f, ensure_ascii=False, indent=2)
        print(f'[record] wrote: {args.record_file}')
    if success:
        print('所有测试通过')
        exit(0)
    else:
        print('测试失败')
        exit(1)

if __name__ == '__main__':
    main()
