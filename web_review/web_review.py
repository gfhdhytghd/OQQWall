#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
OQQWall 网页审核面板
==================

这是一个基于 Python 的网页审核界面，用于管理校园墙投稿内容。
支持实时审核、图片预览、批量操作等功能。

作者: OQQWall Team
版本: 2.0
"""

# ============================================================================
# 导入模块
# ============================================================================

import http.server
import socket
import socketserver
import urllib.parse
import os
import sqlite3
import json
import subprocess
import shlex
import sys
import argparse
from pathlib import Path
import mimetypes
from urllib.parse import quote as urlquote
import time
import threading
from datetime import datetime, timedelta
import html
import secrets
import hashlib
from http import cookies
import base64
import re
import queue
import struct
import zlib

# ============================================================================
# 配置和路径设置
# ============================================================================

# 脚本目录：OQQWall/web_review/
SCRIPT_DIR = Path(__file__).resolve().parent 

# 项目根目录：OQQWall/
ROOT_DIR = SCRIPT_DIR.parent

# 数据库和缓存路径
DB_PATH = ROOT_DIR / 'cache' / 'OQQWall.db'
PREPOST_DIR = ROOT_DIR / 'cache' / 'prepost'
PICTURE_DIR = ROOT_DIR / 'cache' / 'picture'

# ============================================================================
# 模板加载
# ============================================================================

try:
    # 从当前目录加载 HTML 模板
    with open(SCRIPT_DIR / 'review_template.html', 'r', encoding='utf-8') as f:
        INDEX_HTML_TEMPLATE = f.read()
except FileNotFoundError:
    INDEX_HTML_TEMPLATE = """
    <h1>❌ 错误: review_template.html 未找到</h1>
    <p>请确保模板文件与 web_review.py 在同一目录下。</p>
    """

# ------------------------------
# PWA assets (manifest, sw, icons, offline)
# ------------------------------
MANIFEST_JSON = json.dumps({
    "name": "OQQWall 审核面板",
    "short_name": "OQQWall审核",
    "start_url": "/",
    "scope": "/",
    "display": "standalone",
    "background_color": "#F7F2FA",
    "theme_color": "#6750A4",
    "icons": [
        {"src": "/static/icons/icon-192.png", "sizes": "192x192", "type": "image/png", "purpose": "any maskable"},
        {"src": "/static/icons/icon-512.png", "sizes": "512x512", "type": "image/png", "purpose": "any maskable"}
    ]
}, ensure_ascii=False)

SW_JS = """
const CACHE_NAME = 'oqqwall-pwa-v3';
const CORE_ASSETS = ['/', '/list', '/login', '/offline.html', '/manifest.webmanifest'];
self.addEventListener('install', (event) => {
  event.waitUntil(caches.open(CACHE_NAME).then(c => c.addAll(CORE_ASSETS)).then(() => self.skipWaiting()));
});
self.addEventListener('activate', (event) => {
  event.waitUntil(
    caches.keys().then(keys => Promise.all(keys.map(k => { if (k !== CACHE_NAME) return caches.delete(k); })))
      .then(() => self.clients.claim())
  );
});
function isNavigate(request){ return request.mode === 'navigate' || (request.method==='GET' && request.headers.get('accept')?.includes('text/html')); }
self.addEventListener('fetch', (event) => {
  const url = new URL(event.request.url);
  if (url.origin !== location.origin) return;

  // 动态图片与缓存目录：始终走网络，不缓存，避免会话失效或重定向被缓存
  if (url.pathname.startsWith('/cache/')) {
    if (event.request.method === 'GET') {
      event.respondWith(fetch(event.request));
    }
    return;
  }

  if (isNavigate(event.request)){
    event.respondWith(
      fetch(event.request)
        .then(r => {
          if (r && r.ok && r.status === 200) {
            const rc = r.clone();
            caches.open(CACHE_NAME).then(c=>c.put(event.request, rc));
          }
          return r;
        })
        .catch(async ()=>{
          const c = await caches.open(CACHE_NAME);
          return (await c.match(event.request)) || c.match('/offline.html');
        })
    );
    return;
  }

  if (event.request.method==='GET'){
    event.respondWith(
      caches.match(event.request).then(cached => cached || fetch(event.request).then(r => {
        if (r && r.ok && r.status === 200) {
          const rc = r.clone();
          caches.open(CACHE_NAME).then(c=>c.put(event.request, rc));
        }
        return r;
      }).catch(()=>caches.match('/offline.html')))
    );
  }
});
"""

OFFLINE_HTML = (
  "<!doctype html><meta charset='utf-8'>"+
  "<meta name='viewport' content='width=device-width, initial-scale=1'>"+
  "<title>离线 - OQQWall 审核面板</title>"+
  "<style>body{font-family:system-ui,-apple-system,Segoe UI,Roboto,Helvetica,Arial,'PingFang SC','Microsoft Yahei',sans-serif;background:#F7F2FA;margin:0;display:grid;place-items:center;height:100vh;color:#1C1B1F}.card{background:#fff;border-radius:16px;padding:24px;box-shadow:0 2px 12px rgba(0,0,0,.08);max-width:520px}.btn{display:inline-block;margin-top:12px;padding:8px 14px;border-radius:999px;background:#6750A4;color:#fff;text-decoration:none}</style>"+
  "<div class='card'><h1>📴 你目前处于离线状态</h1><p>已缓存的页面仍可查看。恢复网络后将自动刷新。</p><a class='btn' href='/'>返回首页</a></div>"
)

def _png_rgba(w:int, h:int, rgba=(0x67,0x50,0xA4,255)) -> bytes:
    sig=b'\x89PNG\r\n\x1a\n'
    ihdr=struct.pack('!IIBBBBB', w,h,8,6,0,0,0)
    ihdr_chunk=b'IHDR'+ihdr
    ihdr_crc=struct.pack('!I', zlib.crc32(ihdr_chunk)&0xffffffff)
    ihdr_len=struct.pack('!I', len(ihdr))
    row=bytes([0])+bytes(rgba)*w
    raw=row*h
    comp=zlib.compress(raw)
    idat_chunk=b'IDAT'+comp
    idat_crc=struct.pack('!I', zlib.crc32(idat_chunk)&0xffffffff)
    idat_len=struct.pack('!I', len(comp))
    iend_chunk=b'IEND'
    iend_crc=struct.pack('!I', zlib.crc32(iend_chunk)&0xffffffff)
    iend_len=struct.pack('!I', 0)
    return b''.join([sig, ihdr_len, ihdr_chunk, ihdr_crc, idat_len, idat_chunk, idat_crc, iend_len, iend_chunk, iend_crc])

# 列表页模板（内置默认，可外置 list_template.html 覆盖）
try:
    with open(SCRIPT_DIR / 'list_template.html', 'r', encoding='utf-8') as f:
        LIST_HTML_TEMPLATE = f.read()
except FileNotFoundError:
    LIST_HTML_TEMPLATE = """
    <!doctype html><meta charset='utf-8'><meta name='viewport' content='width=device-width, initial-scale=1'>
    <link rel=\"manifest\" href=\"/manifest.webmanifest\">\n    <meta name=\"theme-color\" content=\"#6750A4\">\n    <link rel=\"apple-touch-icon\" href=\"/static/icons/icon-192.png\">
    <title>列表视图</title>
    <style>
      :root{--outline:#CAC4D0}
      body{font-family:system-ui,-apple-system,Segoe UI,Roboto,Helvetica,Arial,"PingFang SC","Microsoft Yahei",sans-serif;background:#F7F2FA;margin:0;padding:12px;color:#1C1B1F}
      .container{max-width:1600px;margin:0 auto;padding:24px}
      .items-list{display:block}
      .l-card{position:relative;background:#fff;border-radius:16px;box-shadow:0 2px 8px rgba(0,0,0,.06);margin:10px 0;transition:transform .2s ease, box-shadow .2s ease}
      .l-card:hover{transform:translateY(-2px);box-shadow:0 6px 16px rgba(0,0,0,.12)}
      .l-form{display:grid;grid-template-columns:1fr 320px;gap:8px;align-items:start;padding:12px;position:relative}
      .l-wrap, .l-warp{display:flex;gap:16px;align-items:flex-start}
      .l-left, i-left{display:grid;grid-template-rows:auto auto;gap:8px}
      .l-top{display:flex;gap:10px;align-items:center}
      .l-select{display:none;align-items:center;justify-content:center;width:22px;height:22px;border:2px solid var(--outline);border-radius:6px;user-select:none;overflow:hidden;font-size:0;line-height:0}
      body.batch-on .l-select{display:inline-flex}
      .l-select input{appearance:none;width:0;height:0;margin:0}
      .l-select.checked{border-color:#28a745;background:#28a745}
      .l-select.checked::after{content:'✓';color:#fff;font-size:12px;line-height:12px;text-align:center}
      /* 批量模式下：已处理卡片隐藏复选框 */
      body.batch-on .l-card.processed .l-select{display:none !important}
      .l-tag{color:#6750A4;font-weight:700}
      .l-comment{color:#1C1B1F;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;max-width:42vw}
      .l-meta{color:#49454F;font-size:13px;display:grid;gap:2px}
      .l-images, i-image{display:flex;flex-wrap:nowrap;overflow:hidden;gap:6px;align-items:center;height:80px}
      .l-images img, i-image img{flex:0 0 76px;width:76px;height:76px;border-radius:8px;border:1px solid var(--outline);object-fit:cover}
      .l-images{max-width:var(--list-img-width, 320px)}
      .l-right, i-right{display:flex;flex-direction:column;margin-top:auto;position:relative}
      .l-badges, badge{position:absolute;top:8px;right:8px;display:flex;gap:8px}
      .badge{padding:4px 10px;border-radius:16px;font-size:12px;font-weight:600}
      .badge-anonymous{background:#F8D7DA;color:#721C24}
      .badge-images{background:#D4EDDA;color:#155724}
      .l-actions{margin-top:auto;display:grid;grid-template-columns:repeat(3,1fr);gap:8px}
      .l-status{margin-top:auto;padding:10px 12px;border:1px solid var(--outline);border-radius:999px;text-align:center;color:#155724;background:rgba(212,237,218,.5)}
      .l-card.processed{opacity:.82}
      .btn{height:41px;padding:0 12px;border:none;border-radius:999px;background:rgba(202,196,208,.35);box-shadow:inset 0 0 0 2px var(--outline);color:#000;text-decoration:none;display:inline-flex;align-items:center;justify-content:center;gap:6px;transition:transform .2s ease, box-shadow .2s ease}
      .btn:hover{transform:translateY(-2px);box-shadow:0 1px 2px rgba(0,0,0,.2), inset 0 0 0 2px var(--outline)}
      .btn-success{background:rgba(40,167,69,.35);box-shadow:inset 0 0 0 2px #28a745;color:#000}
      .btn-danger{background:rgba(220,53,69,.35);box-shadow:inset 0 0 0 2px #dc3545;color:#000}
      .btn-info{background:rgba(23,162,184,.35);box-shadow:inset 0 0 0 2px #17a2b8;color:#000}
      /* 批量工具条 */
      .batch-bar{position:sticky;top:0;z-index:12000;display:grid;grid-template-columns:1fr;gap:8px;align-items:center;background:#fff;border:1px solid var(--outline);border-radius:12px;padding:8px 10px;margin-bottom:8px;box-shadow:0 2px 8px rgba(0,0,0,.06)}
      .batch-row1{display:flex;align-items:center;gap:12px}
      .batch-bar .count{color:#49454F}
      .batch-actions{display:grid;grid-template-columns:repeat(5,1fr);gap:8px}
      /* 批量按钮文本显示：桌面显示文字 + emoji；窄屏仅显示 emoji，去掉不稳定计算 */
      .batch-btn{white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
      .batch-btn .text{display:inline}
      @media (max-width: 550px){ .batch-btn .text{display:none} }
      @media (max-width: 900px){ .l-form{grid-template-columns:1fr 200px} }
      @media (max-width: 720px){
        .l-form{grid-template-columns:1fr}
        .l-actions{margin-top:8px; background:transparent; box-shadow:none; border:0}
      }
      @media (max-width: 768px){ .container{padding:12px} }
    </style>
    <script>window.HIDE_STAGING={hide_staging};</script>
    <div class='container'>
    <div style="display:flex;justify-content:flex-start;gap:8px;margin-bottom:8px"><a href="/" class="btn">← 返回瀑布流</a></div>
    <div class='staging-area' style="display:none;background:#ECE6F0;border-radius:16px;padding:16px;margin-bottom:12px;box-shadow:0 2px 8px rgba(0,0,0,.06)">
      <h2 style="margin:0 0 10px 0;color:#49454F;font-size:18px">暂存区预览</h2>
      <div id='staging-grid' class='staging-grid' style="display:grid;grid-template-columns:repeat(auto-fit,minmax(240px,1fr));gap:10px"></div>
    </div>
    <div class='batch-bar'>
      <div class='batch-row1'>
        <label class='batch-toggle'><input id='batchSwitch' type='checkbox'> 批量模式</label>
        <span class='count' id='selCount'>已选 0</span>
      </div>
      <div class='batch-actions'>
        <button class='btn btn-success batch-btn' id='batchApprove'>✅<span class='text'> 通过</span></button>
        <button class='btn btn-danger batch-btn' id='batchDelete'>🗑️<span class='text'> 删除</span></button>
        <button class='btn batch-btn' id='batchMore'>⋯<span class='text'> 其他</span></button>
        <button class='btn batch-btn' id='selectAll'>📋<span class='text'>全选</span></button>
        <button class='btn batch-btn' id='invertSel'>🔄<span class='text'>反选</span></button>
      </div>
    </div>
    <div class='items-list'>{rows}</div>
    </div>
    <script>
      // 批量按钮响应式文本处理
      (function(){
        function updateBatchButtons(){
          const buttons = document.querySelectorAll('.batch-btn');
          buttons.forEach(btn => {
            const container = btn.closest('.batch-actions');
            if (!container) return;

            // 临时显示文本来测量宽度
            btn.classList.remove('compact');

            // 获取按钮的实际宽度和可用宽度
            const btnWidth = btn.scrollWidth;
            const containerWidth = container.offsetWidth;
            const buttonCount = buttons.length;
            const gap = 8; // grid gap
            const availableWidth = (containerWidth - (buttonCount - 1) * gap) / buttonCount;

            // 如果按钮内容超出可用宽度，切换为紧凑模式
            if (btnWidth > availableWidth) {
              btn.classList.add('compact');
            }
          });
        }

        window.addEventListener('load', updateBatchButtons);
        window.addEventListener('resize', updateBatchButtons);

        // 监听批量模式切换，确保按钮状态正确
        const batchSwitch = document.getElementById('batchSwitch');
        if (batchSwitch) {
          batchSwitch.addEventListener('change', () => {
            setTimeout(updateBatchButtons, 100);
          });
        }
      })();

      // 列表模式自适应图片数量
      (function(){
        function updateListImageDisplay(){
          document.querySelectorAll('.l-card').forEach(card => {
            const imagesContainer = card.querySelector('.l-images, i-image');
            if (!imagesContainer) return;

            const images = imagesContainer.querySelectorAll('img');
            if (images.length === 0) return;

            // 获取卡片宽度和相关空间
            const cardWidth = card.offsetWidth;
            const badgeSpace = 100; // badge预留空间
            const textSpace = 200; // 左侧文字内容最小空间
            const imageWidth = 80;
            const gap = 6;

            // 计算不同情况下的可用宽度
            const totalAvailableWidth = cardWidth - textSpace;
            const availableWidthWithBadge = totalAvailableWidth - badgeSpace;
            const availableWidthWithoutBadge = totalAvailableWidth;

            // 计算在各种情况下能显示的图片数量
            const maxImagesWithBadge = Math.floor((availableWidthWithBadge + gap) / (imageWidth + gap));
            const maxImagesWithoutBadge = Math.floor((availableWidthWithoutBadge + gap) / (imageWidth + gap));

            let displayCount, showBadge, alignRight = false;

            // 决策逻辑：如果能同时显示图片和badge，则显示badge
            if (maxImagesWithBadge >= 2 || (maxImagesWithBadge >= 1 && maxImagesWithoutBadge >= 2)) {
              displayCount = Math.max(1, maxImagesWithBadge);
              showBadge = true;
            } else {
              // 否则隐藏badge，图片靠右对齐
              displayCount = Math.max(1, maxImagesWithoutBadge);
              showBadge = false;
              alignRight = true;
            }

            // 限制显示图片数量在1-4之间，且不超过实际图片数量
            displayCount = Math.min(displayCount, Math.min(4, images.length));

            // 设置图片容器样式
            const totalWidth = displayCount * imageWidth + (displayCount - 1) * gap;
            imagesContainer.style.setProperty('--list-img-width', totalWidth + 'px');

            if (alignRight) {
              imagesContainer.style.justifyContent = 'flex-end';
              imagesContainer.style.marginLeft = 'auto';
            } else {
              imagesContainer.style.justifyContent = 'flex-start';
              imagesContainer.style.marginLeft = '0';
            }

            // 显示/隐藏图片
            images.forEach((img, index) => {
              img.style.display = index < displayCount ? 'block' : 'none';
            });

            // 控制badge显示
            const badges = card.querySelector('.l-badges, badge');
            if (badges) {
              badges.style.display = showBadge ? 'flex' : 'none';
            }
          });
        }

        window.addEventListener('load', updateListImageDisplay);
        window.addEventListener('resize', updateListImageDisplay);

        // 监听新卡片插入
        const observer = new MutationObserver(() => {
          updateListImageDisplay();
          updateListActionButtons();
        });
        observer.observe(document.body, { childList: true, subtree: true });
      })();

      // 列表卡片操作按钮响应式文本处理
      (function(){
        function updateListActionButtons(){
          document.querySelectorAll('.l-card').forEach(card => {
            const actionButtons = card.querySelectorAll('.l-action-btn');
            const actionsContainer = card.querySelector('.l-actions');
            if (!actionsContainer || actionButtons.length === 0) return;

            actionButtons.forEach(btn => {
              // 临时显示文本来测量宽度
              btn.classList.remove('compact');
            });

            // 获取容器宽度和按钮数量
            const containerWidth = actionsContainer.offsetWidth;
            const buttonCount = actionButtons.length;
            const gap = 8; // grid gap
            const availableWidth = (containerWidth - (buttonCount - 1) * gap) / buttonCount;

            // 检查每个按钮是否需要紧凑模式
            actionButtons.forEach(btn => {
              const btnWidth = btn.scrollWidth;
              if (btnWidth > availableWidth) {
                btn.classList.add('compact');
              }
            });
          });
        }

        window.addEventListener('load', updateListActionButtons);
        window.addEventListener('resize', updateListActionButtons);

        // 暴露函数供其他模块调用
        window.updateListActionButtons = updateListActionButtons;
      })();

      // 暂存区：复用主页面的简化加载逻辑
      (function(){
        let tmr=null;
        function schedule(){ if (tmr) return; tmr = setTimeout(()=>{ tmr=null; update(); }, 400); }
        async function update(){
          try{
            const area = document.querySelector('.staging-area');
            if (window.HIDE_STAGING === true || window.HIDE_STAGING === 'true') { if (area) area.style.display='none'; return; }
            const r = await fetch('/api/staged'); if(!r.ok) return; const data = await r.json();
            const grid = document.getElementById('staging-grid'); if(!grid) return; grid.innerHTML='';
            const groups = Object.keys(data||{});
            if (!groups.length){ if (area) area.style.display='none'; return; } else { if (area) area.style.display=''; }
            groups.forEach(groupName=>{
              (data[groupName]||[]).forEach(item=>{
                const div = document.createElement('div');
                div.className='staged-item';
                div.style.cssText='background:#fff;border-radius:12px;padding:10px;display:grid;grid-template-columns:64px 1fr auto;grid-template-rows:auto auto;gap:8px 10px;align-items:center;box-shadow:0 1px 4px rgba(0,0,0,.08)';
                const thumbs = document.createElement('div'); thumbs.className='thumbs'; thumbs.style.cssText='display:flex;gap:6px';
                (item.thumbs||[]).forEach(url=>{ const img=document.createElement('img'); img.src='/cache/'+item.img_source_dir+'/'+item.tag+'/'+url; img.style.cssText='width:56px;height:56px;object-fit:cover;border-radius:8px;border:1px solid #CAC4D0'; thumbs.appendChild(img); });
                const meta = document.createElement('div'); meta.className='meta'; meta.innerHTML = `<span class=\"tag\">#${item.tag}</span>`;
                const info = document.createElement('div'); info.className='info'; info.style.cssText='color:#49454F';
                { const name = item.nickname || ''; const sid = item.senderid || ''; info.textContent = (name || sid) ? `${name}${sid? ' ('+sid+')':''}` : '未知'; }
                const undoWrap = document.createElement('div'); undoWrap.className='undo'; const undoBtn=document.createElement('button'); undoBtn.className='btn'; undoBtn.textContent='↩ 撤销'; undoBtn.onclick=async(ev)=>{ ev.preventDefault(); try{ const rr=await fetch('/api/staged_undo',{method:'POST', headers:{'Content-Type':'application/x-www-form-urlencoded'}, body:new URLSearchParams({tag:String(item.tag)})}); if(rr.ok) div.remove(); }catch(_){}}; undoWrap.appendChild(undoBtn);
                // 布局到三列：缩略图(列1，跨两行) | 文本(列2) | 撤销(列3，跨两行)
                thumbs.style.gridColumn = '1'; thumbs.style.gridRow = '1 / span 2';
                meta.style.gridColumn = '2';
                info.style.gridColumn = '2';
                undoWrap.style.gridColumn = '3'; undoWrap.style.gridRow = '1 / span 2'; undoWrap.style.alignSelf = 'center'; undoWrap.style.justifySelf = 'end';
                div.appendChild(thumbs); div.appendChild(meta); div.appendChild(info); div.appendChild(undoWrap); grid.appendChild(div);
              });
            });
          }catch(_){ }
        }
        // 首次与轮询
        update(); setInterval(update, 15000);
        // SSE 近实时刷新
        try{
          const es = new EventSource('/events');
          es.onmessage = (ev)=>{ try{ const data = JSON.parse(ev.data||'{}');
            if (data && (data.type==='undo' || data.type==='new_pending' || data.type==='processed' || data.type==='toast')) schedule();
          }catch(_){ } };
        }catch(_){ }
      })();
      // SSE: 列表实时插入
      (function(){
        try{
          const es = new EventSource('/events');
          function currentMax(){ let m=0; document.querySelectorAll('.l-card input[name="tag"]').forEach(i=>{const v=parseInt(i.value,10); if(!isNaN(v)) m=Math.max(m,v);}); return m; }
          async function insertTag(tag){ try{ const r=await fetch('/api/list_card?tag='+encodeURIComponent(String(tag))); if(!r.ok) return; const j=await r.json(); const wrap=document.createElement('div'); wrap.innerHTML=j.html; const card=wrap.firstElementChild; if(!card) return; const list=document.querySelector('.items-list'); if(!list) return; list.insertAdjacentElement('afterbegin', card); }catch(_){}}
          es.onmessage=(ev)=>{ try{ const data=JSON.parse(ev.data); if (data.type==='new_pending'){ const curMax=currentMax(); fetch('/api/pending_tags').then(r=>r.json()).then(async (j)=>{ const tags=(j.tags||[]).map(t=>parseInt(t,10)).filter(n=>!isNaN(n)); const newOnes=tags.filter(n=>n>curMax).sort((a,b)=>a-b); for(const t of newOnes){ await insertTag(t);} }); } else if (data.type==='undo'){ const t=parseInt(data.tag,10); if(!isNaN(t)) insertTag(t); } }catch(_){ } };
        }catch(_){ }
      })();

      // 批量模式
      (function(){
        const bodyEl=document.body, selCount=document.getElementById('selCount');
        function boxes(){ return Array.from(document.querySelectorAll('.l-card:not(.processed) input.sel')); }
        function update(){ const n=boxes().filter(x=>x.checked).length; selCount.textContent='已选 '+n; const dis=n===0; ['batchApprove','batchDelete','batchMore'].forEach(id=>{ const b=document.getElementById(id); if(b) b.disabled=dis; }); }
        document.getElementById('batchSwitch')?.addEventListener('change', (e)=>{ if(e.target.checked) bodyEl.classList.add('batch-on'); else { bodyEl.classList.remove('batch-on'); boxes().forEach(cb=>cb.checked=false); document.querySelectorAll('.l-select').forEach(l=>l.classList.remove('checked')); update(); } });
        document.getElementById('selectAll')?.addEventListener('click', (e)=>{ e.preventDefault(); boxes().forEach(cb=>{cb.checked=true; cb.closest('.l-select')?.classList.add('checked');}); update(); });
        document.getElementById('invertSel')?.addEventListener('click', (e)=>{ e.preventDefault(); boxes().forEach(cb=>{cb.checked=!cb.checked; cb.closest('.l-select')?.classList.toggle('checked', cb.checked);}); update(); });
        document.addEventListener('click', (e)=>{ const lab=e.target.closest('.l-select'); if(lab){ e.preventDefault(); const cb=lab.querySelector('input.sel'); cb.checked=!cb.checked; lab.classList.toggle('checked', cb.checked); update(); } });
        document.addEventListener('change', (e)=>{ if (e.target.matches('input.sel')){ e.target.closest('.l-select')?.classList.toggle('checked', e.target.checked); update(); } });
        async function doBatch(cmd){ const tags=boxes().filter(cb=>cb.checked).map(cb=>cb.value); if(!tags.length) return; const form=new URLSearchParams(); tags.forEach(t=>form.append('tags',t)); form.set('cmd',cmd); form.set('flag',''); const r=await fetch('/api/batch', {method:'POST', headers:{'Content-Type':'application/x-www-form-urlencoded'}, body:form.toString()}); if(r.ok){ location.reload(); } }
        document.getElementById('batchApprove')?.addEventListener('click', (e)=>{ e.preventDefault(); doBatch('是'); });
        document.getElementById('batchDelete')?.addEventListener('click', (e)=>{ e.preventDefault(); doBatch('删'); });
        // 简单“其他”菜单（纵向列表）
        const moreBtn=document.getElementById('batchMore'); let menu=null; function closeMenu(){ if(menu){ menu.remove(); menu=null; }}
        function openMenu(anchor){ closeMenu(); menu=document.createElement('div'); menu.style.cssText='position:fixed;z-index:20000;background:#fff;border:1px solid var(--outline);border-radius:12px;box-shadow:0 6px 18px rgba(0,0,0,.12);overflow:hidden;min-width:160px'; const opts=['评论','拒','拉黑','刷新','立即']; opts.forEach((k,i)=>{ const b=document.createElement('button'); b.className='btn'; b.textContent=k; b.style.cssText='display:block;width:100%;border-radius:0;height:36px;background:#fff;box-shadow:none;border-bottom:1px solid var(--outline)'; if(i===opts.length-1) b.style.borderBottom='none'; b.onclick=(ev)=>{ ev.preventDefault(); doBatch(k); closeMenu(); }; menu.appendChild(b); }); const r=anchor.getBoundingClientRect(); const w=200; let left=Math.max(8, Math.min(window.innerWidth-w-8, r.left)); if (r.right > window.innerWidth-100) left=Math.max(8, r.right-w); menu.style.left=left+'px'; menu.style.top=(r.bottom+6)+'px'; document.body.appendChild(menu); setTimeout(()=>{ const onDoc=(e)=>{ const m=menu; if(!m){ document.removeEventListener('click', onDoc); return;} if(!m.contains(e.target) && e.target!==anchor){ document.removeEventListener('click', onDoc); closeMenu(); } }; document.addEventListener('click', onDoc, { passive:true }); }); }
        moreBtn?.addEventListener('click', (e)=>{ e.preventDefault(); openMenu(moreBtn); });
      })();

      // 单卡片三键：详情/通过/删除（AJAX）
      document.addEventListener('click', async (e)=>{
        const btn=e.target.closest('.act'); if(!btn) return; e.preventDefault();
        const form=btn.closest('form'); if(!form) return; const tag=(form.querySelector('input[name="tag"]')||{}).value; const cmd=btn.getAttribute('data-cmd');
        try{ const body=new URLSearchParams({tag,cmd,flag:''}); const r=await fetch('/api/action',{method:'POST', headers:{'Content-Type':'application/x-www-form-urlencoded'}, body}); if(!r.ok){ alert('操作失败: '+r.status); return; }
          const card=btn.closest('.l-card'); if(cmd==='删'){ card && card.remove(); } else { card && card.classList.add('processed'); const act=card && card.querySelector('.l-actions'); if (act) act.outerHTML='<div class="l-status">已处理</div>'; }
        }catch(err){ alert('网络错误: '+err); }
      });
    </script>
    """

# 登录页模板（可选外置）
try:
    with open(SCRIPT_DIR / 'login_template.html', 'r', encoding='utf-8') as f:
        LOGIN_HTML_TEMPLATE = f.read()
except FileNotFoundError:
    LOGIN_HTML_TEMPLATE = """
<!doctype html>
<html lang=\"zh-CN\"><head><meta charset=\"utf-8\"><meta name=\"viewport\" content=\"width=device-width, initial-scale=1\"><link rel=\"manifest\" href=\"/manifest.webmanifest\"><meta name=\"theme-color\" content=\"#6750A4\"><link rel=\"apple-touch-icon\" href=\"/static/icons/icon-192.png\"><title>登录</title>
<style>body{font-family:system-ui,-apple-system,Segoe UI,Roboto,Helvetica,Arial,\"PingFang SC\",\"Microsoft Yahei\",sans-serif;background:#F7F2FA;margin:0;display:flex;align-items:center;justify-content:center;height:100vh} .card{background:#fff;border-radius:16px;box-shadow:0 2px 12px rgba(0,0,0,.08);padding:24px;min-width:320px;max-width:560px;width:75%} h1{font-size:20px;margin:.2rem 0 1rem} .row{display:flex;flex-direction:column;gap:6px;margin-bottom:10px} input{padding:10px 12px;border:1px solid #ccc;border-radius:10px} .btn{width:100%;padding:10px 12px;border:none;border-radius:999px;background:#6750A4;color:#fff;font-weight:600;cursor:pointer} .msg{color:#B3261E;margin-bottom:8px;font-size:13px}</style>
</head><body>
<form class=\"card\" method=\"post\" action=\"/login\"> 
  <h1>OQQWall 审核登录</h1>
  {msg}
  <div class=\"row\"><label>用户名</label><input name=\"username\" required></div>
  <div class=\"row\"><label>密码</label><input type=\"password\" name=\"password\" required></div>
  <button class=\"btn\">登录</button>
</form>
<script>if('serviceWorker' in navigator){window.addEventListener('load',()=>{navigator.serviceWorker.register('/sw.js').catch(()=>{});});}</script>
</body></html>
"""

# ============================================================================
# 数据库和配置函数 + 事件广播
# ============================================================================

def load_config():
    """
    加载 oqqwall.config 配置文件
    
    Returns:
        dict: 配置字典
    """
    cfg = {}
    cfg_file = ROOT_DIR / 'oqqwall.config'
    
    if cfg_file.exists():
        with cfg_file.open('r', encoding='utf-8') as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith('#'):
                    continue
                if '=' in line:
                    k, v = line.split('=', 1)
                    cfg[k.strip()] = v.strip().strip('"')
    return cfg

# 简易会话存储：token -> {username, group, created}
SESSION_STORE: dict[str, dict] = {}
# 会话配置
SESSION_COOKIE_NAME = 'oqqwall_review_session'
# 默认 7 天（可按需调整）
SESSION_TTL_SECONDS = 7 * 24 * 60 * 60

# 服务器推送（SSE）
EVENT_CLIENTS: list[tuple[str, queue.Queue]] = []  # (group, queue)
EVENT_LOCK = threading.Lock()

def broadcast_event(event: dict, target_group: str | None = None):
    """向所有事件队列广播一个事件（可按组过滤）。"""
    with EVENT_LOCK:
        for grp, q in list(EVENT_CLIENTS):
            if (target_group is None) or (grp == target_group):
                try:
                    q.put_nowait(event)
                except Exception:
                    pass

def load_admins():
    """从 AcountGroupcfg.json 读取管理员账号。
    支持两种密码形式：
      - 明文: "password": "pwd"
      - sha256: "password": "sha256:<hex>"
    结构示例：
      {
        "GroupA": { ..., "admins": [{"username": "alice", "password": "sha256:..."}] }
      }
    返回: dict username -> {"group": group_key, "password": stored}
    """
    try:
        with open(ROOT_DIR / 'AcountGroupcfg.json', 'r', encoding='utf-8') as f:
            data = json.load(f)
        admins = {}
        for group_key, obj in (data or {}).items():
            for adm in obj.get('admins', []) or []:
                u = str(adm.get('username', '')).strip()
                p = str(adm.get('password', '')).strip()
                if u:
                    admins[u] = { 'group': group_key, 'password': p }
        return admins
    except Exception as e:
        print(f"[web-review] 读取管理员配置失败: {e}")
        return {}

def verify_password(stored: str, provided: str) -> bool:
    if stored.startswith('sha256:'):
        h = hashlib.sha256(provided.encode('utf-8')).hexdigest()
        return h == stored.split(':', 1)[1]
    return secrets.compare_digest(stored, provided)

def parse_cookies(header: str | None) -> dict:
    jar = cookies.SimpleCookie()
    if header:
        try:
            jar.load(header)
        except Exception:
            return {}
    return {k: morsel.value for k, morsel in jar.items()}


def db_query(sql, params=()):
    """
    执行数据库查询
    
    Args:
        sql (str): SQL 查询语句
        params (tuple): 查询参数
        
    Returns:
        list: 查询结果列表
    """
    if not DB_PATH.exists():
        return []
        
    con = sqlite3.connect(str(DB_PATH))
    con.row_factory = sqlite3.Row
    
    try:
        cur = con.execute(sql, params)
        rows = cur.fetchall()
        return [dict(r) for r in rows]
    finally:
        con.close()

def db_exec(sql, params=()):
    """执行写操作（INSERT/UPDATE/DELETE）。"""
    if not DB_PATH.exists():
        return 0
    con = sqlite3.connect(str(DB_PATH))
    try:
        cur = con.execute(sql, params)
        con.commit()
        return cur.rowcount
    finally:
        con.close()

# ============================================================================
# 数据处理函数
# ============================================================================

def get_all_staged_tags() -> set:
    """合并所有组的暂存区 tag，用于从待审核列表中过滤。"""
    staged = set()
    try:
        with open(ROOT_DIR / 'AcountGroupcfg.json', 'r', encoding='utf-8') as f:
            account_groups = json.load(f)
        for group in (account_groups or {}).keys():
            try:
                rows = db_query(f"SELECT tag FROM sendstorge_{group}")
            except Exception as e:
                print(f"[web-review] 读取 sendstorge_{group} 失败: {e}")
                rows = []
            for r in rows:
                t = str(r.get('tag') or '').strip()
                if t:
                    staged.add(t)
    except Exception as e:
        print(f"[web-review] 读取暂存区标签失败(外层): {e}")
    return staged


def list_pending(search: str | None = None, group_filter: str | None = None):
    """
    获取待审核项目列表
    
    Args:
        search (str, optional): 搜索关键词
        
    Returns:
        list: 待审核项目列表
    """
    items = []
    
    if not PREPOST_DIR.exists():
        return []
    
    # 获取所有暂存标签，避免重复展示
    staged_tags = get_all_staged_tags()

    for p in PREPOST_DIR.iterdir():
        if not p.is_dir() or not p.name.isdigit():
            continue
            
        tag = p.name

        # 如果已经在暂存区中，则跳过
        if tag in staged_tags:
            continue
        
        # 从数据库获取基本信息
        row = db_query(
            "SELECT tag, senderid, nickname, receiver, ACgroup, comment, AfterLM FROM preprocess WHERE tag = ?", 
            (tag,)
        )
        if not row:
            continue
            
        r = row[0]
        # 组过滤
        if group_filter and str(r.get('ACgroup')) != str(group_filter):
            continue
        
        # 搜索过滤
        if search:
            search_lower = search.lower()
            searchable_fields = ['senderid', 'nickname', 'comment']
            if not any([search_lower in str(r.get(k, '')).lower() for k in searchable_fields]) and search_lower not in tag:
                continue
        
        # 收集图片文件
        imgs = [f.name for f in sorted(p.iterdir()) if f.is_file()]
        img_source_dir = 'prepost'
        
        # 如果 prepost 目录没有图片，检查 picture 目录
        if not imgs:
            picture_dir_for_tag = PICTURE_DIR / tag
            if picture_dir_for_tag.exists():
                imgs = [f.name for f in sorted(picture_dir_for_tag.iterdir()) if f.is_file()]
                img_source_dir = 'picture'
        
        # 解析 AfterLM JSON 数据
        afterlm_data = {}
        try:
            if r.get('AfterLM'):
                afterlm_data = json.loads(r['AfterLM'])
        except:
            pass
        
        # 获取提交时间
        try:
            mod_time = p.stat().st_mtime
            submit_time = datetime.fromtimestamp(mod_time).strftime('%Y-%m-%d %H:%M:%S')
        except:
            submit_time = '未知'
        
        # 构建项目数据
        item = {
            'tag': tag,
            'senderid': r.get('senderid'),
            'nickname': r.get('nickname'),
            'ACgroup': r.get('ACgroup'),
            'receiver': r.get('receiver'),
            'comment': r.get('comment') or '',
            'images': imgs,
            'submit_time': submit_time,
            'afterlm': afterlm_data,
            'is_anonymous': afterlm_data.get('needpriv') == 'true',
            'has_images': len(imgs) > 0,
            'image_count': len(imgs),
            'img_source_dir': img_source_dir
        }
        
        items.append(item)
    
    # 按标签数字排序（最新的在前）
    items.sort(key=lambda x: int(x['tag']), reverse=True)
    return items

def list_staged(group_filter: str | None = None):
    """
    获取已暂存的项目列表
    
    Returns:
        dict: 按群组分组的暂存项目
    """
    staged_items = {}
    
    try:
        with open(ROOT_DIR / 'AcountGroupcfg.json', 'r', encoding='utf-8') as f:
            account_groups = json.load(f)
        group_names = list(account_groups.keys())
    except Exception as e:
        print(f"[web-review] Error reading AcountGroupcfg.json: {e}")
        return {}
    
    for group in group_names:
        try:
            staged_tags = db_query(f"SELECT tag FROM sendstorge_{group}")
        except Exception as e:
            print(f"[web-review] 读取 sendstorge_{group} 失败: {e}")
            staged_tags = []
        if not staged_tags:
            continue
            
        group_items = []
        for tag_row in staged_tags:
            tag = tag_row.get('tag')
            if not tag:
                continue
                
            item_details = db_query(
                "SELECT tag, senderid, nickname FROM preprocess WHERE tag = ?",
                (tag,)
            )
            if item_details:
                item = dict(item_details[0])
                # 补充缩略图（最多3张），来源优先 prepost，其次 picture
                thumbs = []
                src_dir = 'prepost'
                p = PREPOST_DIR / str(tag)
                if p.exists():
                    thumbs = [f.name for f in sorted(p.iterdir()) if f.is_file()][:3]
                if not thumbs:
                    alt = PICTURE_DIR / str(tag)
                    if alt.exists():
                        src_dir = 'picture'
                        thumbs = [f.name for f in sorted(alt.iterdir()) if f.is_file()][:3]
                item['thumbs'] = thumbs
                item['img_source_dir'] = src_dir
                group_items.append(item)
                
        if group_items:
            if (not group_filter) or (group == group_filter):
                staged_items[group] = group_items
            
    return staged_items

def list_groups():
    """读取账户组配置，返回可用于 command.sh 的账号选项。"""
    try:
        with open(ROOT_DIR / 'AcountGroupcfg.json', 'r', encoding='utf-8') as f:
            data = json.load(f)
        result = []
        for key, val in (data or {}).items():
            result.append({
                'key': key,
                'mainqqid': str(val.get('mainqqid', '')),
                'minorqqids': [str(x) for x in (val.get('minorqqid') or [])],
            })
        return result
    except Exception as e:
        print(f"[web-review] 读取 AcountGroupcfg.json 失败: {e}")
        return []


def get_image_mime_type(file_path):
    """
    根据文件头检测图片 MIME 类型
    
    Args:
        file_path (str): 图片文件路径
        
    Returns:
        str: MIME 类型
    """
    try:
        with open(file_path, 'rb') as f:
            header = f.read(16)
            
            if header.startswith(b'\xff\xd8\xff'):
                return 'image/jpeg'
            elif header.startswith(b'\x89PNG\r\n\x1a\n'):
                return 'image/png'
            elif header.startswith((b'GIF87a', b'GIF89a')):
                return 'image/gif'
            elif header.startswith(b'BM'):
                return 'image/bmp'
            elif header.startswith(b'RIFF') and header[8:12] == b'WEBP':
                return 'image/webp'
    except:
        pass
        
    return 'application/octet-stream'

def make_inline_img_src(img_source_dir: str, tag: str | int, filename: str, inline: bool = True) -> str:
    """返回列表/详情页可用的图片 src。

    - inline=True 时，优先将项目目录内的文件转为 data:URI，避免鉴权/缓存等因素导致首屏不显示。
    - 若读取失败或不在项目目录内，则退回到 /cache 路由，由服务器按权限与 MIME 正确返回。
    """
    try:
        tag_str = str(tag)
        rel = Path('cache') / img_source_dir / tag_str / filename
        p = (ROOT_DIR / rel).resolve()
        root = ROOT_DIR.resolve()
        if inline and str(p).startswith(str(root)) and p.is_file():
            data = p.read_bytes()
            mime = get_image_mime_type(p)
            b64 = base64.b64encode(data).decode('ascii')
            return f"data:{mime};base64,{b64}"
    except Exception as e:
        print(f"[web-review] 构建内联图片失败: {e}")
    # 回退为 /cache 路径（仍然可用）
    from urllib.parse import quote
    return quote(f"/cache/{img_source_dir}/{tag}/{filename}")

# ============================================================================
# 命令执行函数
# ============================================================================

def run_audit_command(tag: str, cmd: str, flag: str | None = None, background: bool = False, web_user: str | None = None):
    """
    执行审核相关的 shell 命令
    
    Args:
        tag (str): 投稿标签
        cmd (str): 审核命令
        flag (str, optional): 附加参数
        background (bool): 是否后台执行
        
    Returns:
        tuple: (退出码, 输出内容)
    """
    args = [tag, cmd]
    if flag:
        args.append(flag)
    
    # 安全地转义参数
    safe_joined = ' '.join(arg.replace("'", "'\\''") for arg in args)
    env_prefix = "WEB_REVIEW=1"
    if web_user:
        safe_user = web_user.replace("'", "'\\''")
        env_prefix += f" WEB_REVIEW_USER='{safe_user}'"
    cmdline = ['bash', '-lc', f"{env_prefix} ./getmsgserv/processsend.sh '{safe_joined}'"]

    # 记录执行日志
    preview = safe_joined if len(safe_joined) < 200 else (safe_joined[:200] + ' …')
    print(f"[web-review] 执行命令: ./getmsgserv/processsend.sh '{preview}'", flush=True)

    # 在项目根目录执行命令
    proc = subprocess.run(
        cmdline, 
        cwd=str(ROOT_DIR), 
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE, 
        text=True,
    )
    
    # 输出执行结果
    if proc.stdout:
        print("[web-review] 标准输出:\n" + proc.stdout, flush=True)
    if proc.stderr:
        print("[web-review] 错误输出:\n" + proc.stderr, flush=True)
        
    print(f"[web-review] 命令执行完成，退出码: {proc.returncode}", flush=True)
    return proc.returncode, (proc.stdout or proc.stderr)

# ============================================================================
# Web 服务器类
# ============================================================================

class ReviewServer(http.server.SimpleHTTPRequestHandler):
    """
    OQQWall 审核面板 Web 服务器
    
    继承自 SimpleHTTPRequestHandler，提供 HTTP 请求处理功能
    """
    
    def __init__(self, *args, **kwargs):
        """
        初始化服务器处理器
        
        设置工作目录为项目根目录
        """
        super().__init__(*args, directory=str(ROOT_DIR), **kwargs)

    # --- Session helpers ---
    def _issue_session_cookie(self, token: str):
        try:
            max_age = SESSION_TTL_SECONDS
            expires_dt = datetime.utcnow() + timedelta(seconds=max_age)
            expires_str = expires_dt.strftime('%a, %d %b %Y %H:%M:%S GMT')
            parts = [f"{SESSION_COOKIE_NAME}={token}", 'HttpOnly', 'Path=/', f"Max-Age={max_age}", f"Expires={expires_str}", 'SameSite=Lax']
            proto = (self.headers.get('X-Forwarded-Proto') or '').lower()
            if proto == 'https':
                parts.append('Secure')
            self.send_header('Set-Cookie', '; '.join(parts))
        except Exception:
            pass

    def do_GET(self):
        """
        处理 GET 请求
        
        支持以下路径：
        - /api/staged: 获取暂存项目 API
        - /detail?tag=123: 稿件详情页
        - /cache/prepost/*, /cache/picture/*: 图片文件服务
        - 其他: 渲染审核页面
        """
        parsed_path = urllib.parse.urlparse(self.path)
        # PWA assets (public, no auth required)
        if parsed_path.path == '/manifest.webmanifest':
            body = MANIFEST_JSON.encode('utf-8')
            self.send_response(200)
            self.send_header('Content-type', 'application/manifest+json; charset=utf-8')
            self.send_header('Cache-Control', 'public, max-age=3600')
            self.end_headers()
            self.wfile.write(body)
            return
        if parsed_path.path == '/sw.js':
            body = SW_JS.encode('utf-8')
            self.send_response(200)
            self.send_header('Content-type', 'application/javascript; charset=utf-8')
            self.send_header('Service-Worker-Allowed', '/')
            self.send_header('Cache-Control', 'public, max-age=300')
            self.end_headers()
            self.wfile.write(body)
            return
        if parsed_path.path in ('/offline.html', '/pwa/offline'):
            body = OFFLINE_HTML.encode('utf-8')
            self.send_response(200)
            self.send_header('Content-type', 'text/html; charset=utf-8')
            self.send_header('Cache-Control', 'public, max-age=3600')
            self.end_headers()
            self.wfile.write(body)
            return
        if parsed_path.path in ('/static/icons/icon-192.png', '/favicon.ico'):
            png = _png_rgba(192, 192, (0x67, 0x50, 0xA4, 255))
            self.send_response(200)
            self.send_header('Content-type', 'image/png')
            self.send_header('Cache-Control', 'public, max-age=2592000')
            self.end_headers()
            self.wfile.write(png)
            return
        if parsed_path.path == '/static/icons/icon-512.png':
            png = _png_rgba(512, 512, (0x67, 0x50, 0xA4, 255))
            self.send_response(200)
            self.send_header('Content-type', 'image/png')
            self.send_header('Cache-Control', 'public, max-age=2592000')
            self.end_headers()
            self.wfile.write(png)
            return
        
        # 获取当前用户
        user = self._get_user()
        # 登录页：如果已登录则直接跳到首页，避免二次点击/刷新
        if parsed_path.path == '/login':
            if user:
                self.send_response(303)
                self.send_header('Location', '/')
                self.end_headers()
                return
            self._render_login()
            return
        if parsed_path.path == '/logout':
            self._logout()
            return

        # 未登录则跳转
        if not user:
            self.send_response(303)
            self.send_header('Location', '/login')
            self.end_headers()
            return

        # API 端点：获取暂存项目
        if parsed_path.path == '/api/staged':
            try:
                staged_data = list_staged(group_filter=user['group'])
                response_body = json.dumps(staged_data, ensure_ascii=False).encode('utf-8')
                self.send_response(200)
                self.send_header('Content-type', 'application/json; charset=utf-8')
                self.end_headers()
                self.wfile.write(response_body)
            except Exception as e:
                print(f"[web-review] API 错误: {e}")
                self.send_error(500, "Internal Server Error")
            return

        # API 端点：查看会话（调试用）
        if parsed_path.path == '/api/whoami':
            u = self._get_user()
            body = json.dumps({
                "ok": bool(u),
                "user": {"username": (u or {}).get('username'), "group": (u or {}).get('group')}
            }, ensure_ascii=False).encode('utf-8')
            self.send_response(200)
            # 访问即刷新 Cookie
            tok = None
            try:
                tok = (parse_cookies(self.headers.get('Cookie')) or {}).get(SESSION_COOKIE_NAME)
            except Exception:
                tok = None
            if tok:
                self._issue_session_cookie(tok)
            self.send_header('Content-type', 'application/json; charset=utf-8')
            self.end_headers()
            self.wfile.write(body)
            return

        # SSE 事件流
        if parsed_path.path == '/events':
            user = self._get_user()
            if not user:
                self.send_error(401, 'Unauthorized')
                return
            self.send_response(200)
            self.send_header('Content-type', 'text/event-stream; charset=utf-8')
            self.send_header('Cache-Control', 'no-cache')
            self.send_header('Connection', 'keep-alive')
            self.end_headers()
            q = queue.Queue()
            with EVENT_LOCK:
                EVENT_CLIENTS.append((user['group'], q))
            try:
                # 初始握手
                init = json.dumps({"type":"hello","group":user['group']}, ensure_ascii=False)
                self.wfile.write(f"data: {init}\n\n".encode('utf-8'))
                self.wfile.flush()
                # 循环推送
                while True:
                    try:
                        ev = q.get(timeout=15)
                        payload = json.dumps(ev, ensure_ascii=False)
                        self.wfile.write(f"data: {payload}\n\n".encode('utf-8'))
                        self.wfile.flush()
                    except queue.Empty:
                        # keepalive
                        self.wfile.write(b": keepalive\n\n")
                        self.wfile.flush()
            except Exception:
                pass
            finally:
                with EVENT_LOCK:
                    try:
                        EVENT_CLIENTS.remove((user['group'], q))
                    except ValueError:
                        pass
            return

        # API 端点：获取当前待审标签列表（按组过滤）
        if parsed_path.path == '/api/pending_tags':
            user = self._get_user()
            if not user:
                self.send_error(401, 'Unauthorized')
                return
            try:
                items = list_pending(search=None, group_filter=user['group'])
                tags = [str(i['tag']) for i in items]
                body = json.dumps({"tags": tags}, ensure_ascii=False).encode('utf-8')
                self.send_response(200)
                self.send_header('Content-type', 'application/json; charset=utf-8')
                self.end_headers()
                self.wfile.write(body)
            except Exception as e:
                print(f"[web-review] API 错误: {e}")
                self.send_error(500, 'Internal Server Error')
            return

        # API 端点：获取单个卡片HTML（用于无刷新插入）
        if parsed_path.path == '/api/card':
            user = self._get_user()
            if not user:
                self.send_error(401, 'Unauthorized')
                return
            qs = urllib.parse.parse_qs(parsed_path.query)
            tag = (qs.get('tag') or [''])[0]
            if not tag.isdigit():
                self.send_error(400, 'Bad Request')
                return
            # 查找待审核项目（已过滤暂存）
            items = list_pending(search=None, group_filter=user['group'])
            item = next((i for i in items if i.get('tag') == tag), None)
            if not item:
                self.send_error(404, 'Not Found')
                return
            html_card = self._generate_item_card(item)
            body = json.dumps({"tag": tag, "html": html_card}, ensure_ascii=False).encode('utf-8')
            self.send_response(200)
            self.send_header('Content-type', 'application/json; charset=utf-8')
            self.end_headers()
            self.wfile.write(body)
            return

        # 列表视图页（iframe 或独立）
        if parsed_path.path == '/list':
            self.render_list_page(parsed_path, user)
            return

        # 列表卡片 HTML（用于 SSE 插入）
        if parsed_path.path == '/api/list_card':
            user = self._get_user()
            if not user:
                self.send_error(401, 'Unauthorized')
                return
            qs = urllib.parse.parse_qs(parsed_path.query)
            tag = (qs.get('tag') or [''])[0]
            if not tag.isdigit():
                self.send_error(400, 'Bad Request')
                return
            items = list_pending(search=None, group_filter=user['group'])
            item = next((i for i in items if i.get('tag') == tag), None)
            if not item:
                self.send_error(404, 'Not Found')
                return
            html_card = self._generate_list_card(item, back_path='/list')
            body = json.dumps({"tag": tag, "html": html_card}, ensure_ascii=False).encode('utf-8')
            self.send_response(200)
            self.send_header('Content-type', 'application/json; charset=utf-8')
            self.end_headers()
            self.wfile.write(body)
            return

        # API 端点：待审核元信息（用于无刷新提示）
        if parsed_path.path == '/api/pending_meta':
            try:
                items = list_pending(search=None, group_filter=user['group'])
                total = len(items)
                max_tag = max([int(i['tag']) for i in items], default=0)
                body = json.dumps({"count": total, "max_tag": max_tag}, ensure_ascii=False).encode('utf-8')
                self.send_response(200)
                self.send_header('Content-type', 'application/json; charset=utf-8')
                self.end_headers()
                self.wfile.write(body)
            except Exception as e:
                print(f"[web-review] API 错误: {e}")
                self.send_error(500, "Internal Server Error")
            return
        
        # 图片文件服务
        if parsed_path.path.startswith(('/cache/prepost/', '/cache/picture/')):
            fs_path_str = parsed_path.path.lstrip('/')
            fs_path = Path(self.directory) / fs_path_str
            
            # 安全检查：确保文件在允许的目录内
            if fs_path.is_file() and str(fs_path.resolve()).startswith(str(Path(self.directory).resolve())):
                try:
                    # 额外权限检查：根据 tag 限制组访问
                    parts = fs_path.parts
                    # expect: ROOT/.../cache/<dir>/<tag>/file
                    tag = None
                    for i, p in enumerate(parts):
                        if p == 'cache' and i + 2 < len(parts):
                            maybe_tag = parts[i + 2]
                            if maybe_tag.isdigit():
                                tag = maybe_tag
                            break
                    if tag:
                        row = db_query("SELECT ACgroup FROM preprocess WHERE tag = ?", (tag,))
                        if not row or str(row[0].get('ACgroup')) != str(user['group']):
                            self.send_error(403, "Forbidden")
                            return
                    with open(fs_path, 'rb') as f:
                        content = f.read()
                    content_type = get_image_mime_type(fs_path)
                    self.send_response(200)
                    self.send_header('Content-type', content_type)
                    self.send_header('Content-Length', str(len(content)))
                    # 避免浏览器/Service Worker 缓存动态图片响应，减少旧重定向/错误被缓存的问题
                    self.send_header('Cache-Control', 'private, no-store')
                    self.end_headers()
                    self.wfile.write(content)
                except IOError:
                    self.send_error(404, "File Not Found")
            else:
                self.send_error(404, "File Not Found")
            return
        
        # 详情页
        if parsed_path.path == '/detail':
            self.render_detail_page(parsed_path, user)
            return
        # 详情页HTML渲染预览
        if parsed_path.path == '/detail_html':
            self.render_detail_html(parsed_path, user)
            return
        
        # 默认：渲染审核页面
        self.render_review_page(parsed_path, user)

    def do_POST(self):
        """
        处理 POST 请求
        
        处理审核操作，如通过、拒绝、删除等；以及全局 command.sh 操作
        """
        content_length = int(self.headers.get('Content-Length', '0') or '0')
        post_data = self.rfile.read(content_length).decode('utf-8')
        params = urllib.parse.parse_qs(post_data)
        path = urllib.parse.urlparse(self.path).path

        # 登录提交
        if path == '/login':
            username = (params.get('username') or [''])[0]
            password = (params.get('password') or [''])[0]
            admins = load_admins()
            rec = admins.get(username)
            if rec and verify_password(rec['password'], password):
                token = secrets.token_urlsafe(32)
                SESSION_STORE[token] = {'username': username, 'group': rec['group'], 'created': time.time()}
                self.send_response(303)
                # 计算 Cookie 属性
                cookie_attrs = [f"{SESSION_COOKIE_NAME}={token}", 'HttpOnly', 'Path=/', f"Max-Age={SESSION_TTL_SECONDS}", 'SameSite=Lax']
                # 透传代理的 HTTPS 头以决定是否设置 Secure
                proto = (self.headers.get('X-Forwarded-Proto') or '').lower()
                if proto == 'https':
                    cookie_attrs.append('Secure')
                self.send_header('Set-Cookie', '; '.join(cookie_attrs))
                self.send_header('Location', '/')
                self.end_headers()
                return
            else:
                self._render_login("<div class='msg'>用户名或密码错误</div>")
                return

        if path == '/api/cmd':
            # 全局命令 -> command.sh
            user = self._get_user()
            if not user:
                self.send_response(303)
                self.send_header('Location', '/login')
                self.end_headers()
                return
            object_str = params.get('object', [''])[0]
            self_id = params.get('self_id', [''])[0]
            # 共享输入：number 用于设定编号和调出
            numb = params.get('numb', [''])[0] or params.get('number', [''])[0]
            senderid = params.get('senderid', [''])[0]
            replay_tag = params.get('replay_tag', [''])[0] or params.get('number', [''])[0]

            if object_str == '设定编号' and numb:
                object_str = f"设定编号 {numb}"
            elif object_str == '取消拉黑' and senderid:
                object_str = f"取消拉黑 {senderid}"
            elif object_str == '调出' and replay_tag:
                object_str = f"调出 {replay_tag}"

            # 强制以主账号发送
            for g in list_groups():
                if g['key'] == user['group']:
                    self_id = g['mainqqid']
                    break

            rc, out = self._run_command_sh(object_str, self_id, web_user=user.get('username'))
            notice = urllib.parse.quote(f"已执行全局操作: {object_str}")
            self.send_response(303)
            self.send_header('Location', f"/?notice={notice}")
            self.end_headers()
            return
        elif path == '/api/batch':
            # 批量执行同一命令
            user = self._get_user()
            if not user:
                self.send_error(401, 'Unauthorized')
                return
            raw_tags = params.get('tags', [])
            if len(raw_tags) == 1 and ',' in raw_tags[0]:
                tags = [t.strip() for t in raw_tags[0].split(',') if t.strip()]
            else:
                tags = [t for t in raw_tags if t]
            cmd = (params.get('cmd') or [''])[0]
            flag = (params.get('flag') or [''])[0]
            if not tags or not cmd:
                self.send_error(400, 'Bad Request')
                return
            ok = fail = 0
            for tag in tags:
                # 组校验
                row = db_query("SELECT ACgroup FROM preprocess WHERE tag = ?", (tag,))
                if not row or str(row[0].get('ACgroup')) != str(user['group']):
                    fail += 1
                    continue
                rc, _ = run_audit_command(tag, cmd, flag, web_user=user.get('username'))
                if rc == 0: ok += 1
                else: fail += 1
            total = ok + fail
            level = 'success' if fail == 0 else ('warning' if ok > 0 else 'error')
            broadcast_event({"type":"toast","level":level,"text":f"批量执行 {total} 项: 成功 {ok}, 失败 {fail}"}, target_group=user['group'])
            body = json.dumps({"ok": True, "done": ok, "failed": fail}).encode('utf-8')
            self.send_response(200)
            self.send_header('Content-type', 'application/json; charset=utf-8')
            self.end_headers()
            self.wfile.write(body)
            return
        elif path == '/api/action':
            # 单卡片操作（AJAX）
            user = self._get_user()
            if not user:
                self.send_error(401, 'Unauthorized')
                return
            tag = params.get('tag', [''])[0]
            cmd = params.get('cmd', [''])[0]
            flag = params.get('flag', [''])[0]
            if not tag or not cmd:
                self.send_error(400, 'Bad Request')
                return
            # 组权限校验
            row = db_query("SELECT ACgroup FROM preprocess WHERE tag = ?", (tag,))
            if not row or str(row[0].get('ACgroup')) != str(user['group']):
                self.send_error(403, 'Forbidden')
                return
            rc, out = run_audit_command(tag, cmd, flag, web_user=user.get('username'))
            # 推送 toast 事件
            level = 'success' if rc == 0 else 'error'
            broadcast_event({"type":"toast","level":level,"text":f"已执行: #{tag} 指令 {cmd}"}, target_group=user['group'])
            body = json.dumps({"ok": rc == 0}).encode('utf-8')
            self.send_response(200)
            self.send_header('Content-type', 'application/json; charset=utf-8')
            self.end_headers()
            self.wfile.write(body)
            return
        elif path == '/api/staged_undo':
            # 撤销暂存：从 sendstorge_{group} 删除后调出
            user = self._get_user()
            if not user:
                self.send_error(401, 'Unauthorized')
                return
            tag = params.get('tag', [''])[0]
            if not tag or not tag.isdigit():
                self.send_error(400, 'Bad Request')
                return
            group = user['group']
            # 删除行
            affected = db_exec(f"DELETE FROM sendstorge_{group} WHERE tag = ?", (tag,))
            # 触发调出
            self._run_command_sh(f"调出 {tag}", self_id=self._get_group_mainqqid(group), web_user=user.get('username'))
            # 通知前端可插入新卡片
            broadcast_event({"type":"undo","tag":tag}, target_group=group)
            self.send_response(200)
            self.send_header('Content-type', 'application/json; charset=utf-8')
            self.end_headers()
            self.wfile.write(json.dumps({"ok": True, "deleted": affected}).encode('utf-8'))
            return
        else:
            # 审核操作 -> processsend.sh
            user = self._get_user()
            if not user:
                self.send_response(303)
                self.send_header('Location', '/login')
                self.end_headers()
                return
            tag = params.get('tag', [''])[0]
            cmd = params.get('cmd', [''])[0]
            flag = params.get('flag', [''])[0]
            redirect_to = params.get('redirect', ['/'])[0] or '/'
            if tag and cmd:
                # 组权限校验
                row = db_query("SELECT ACgroup FROM preprocess WHERE tag = ?", (tag,))
                if not row or str(row[0].get('ACgroup')) != str(user['group']):
                    self.send_error(403, 'Forbidden')
                    return
                print(f"[web-review] 执行审核操作: tag={tag}, cmd={cmd}, flag={flag}")
                rc, out = run_audit_command(tag, cmd, flag, web_user=user.get('username'))
                # 在重定向地址上追加提示
                sep = '&' if ('?' in redirect_to) else '?'
                notice = urllib.parse.quote(f"已执行: #{tag} 指令 {cmd}")
                redirect_to = f"{redirect_to}{sep}notice={notice}"
            self.send_response(303)
            self.send_header('Location', redirect_to)
            self.end_headers()
            return

    def render_review_page(self, parsed_path, user):
        """
        渲染审核页面
        
        Args:
            parsed_path: 解析后的 URL 路径
        """
        query_params = urllib.parse.parse_qs(parsed_path.query)
        search_term = query_params.get('search', [''])[0]
        notice_msg = query_params.get('notice', [''])[0]
        
        # 设置响应头
        self.send_response(200)
        # 滚动续期：刷新 Cookie 过期时间
        tok = None
        try:
            tok = (parse_cookies(self.headers.get('Cookie')) or {}).get(SESSION_COOKIE_NAME)
        except Exception:
            tok = None
        if tok:
            self._issue_session_cookie(tok)
        self.send_header("Content-type", "text/html; charset=utf-8")
        self.end_headers()
        
        # 获取待审核项目
        items = list_pending(search=search_term, group_filter=user['group'])
        
        # 生成页面内容
        rows_html = ""
        
        if not items and not search_term:
            rows_html = """
            <div class='empty-state'>
                <h3>🎉 恭喜！</h3>
                <p>所有投稿都已处理完毕。</p>
    </div>
    <script>if('serviceWorker' in navigator){window.addEventListener('load',()=>{navigator.serviceWorker.register('/sw.js').catch(()=>{});});}</script>
    """
        elif not items and search_term:
            rows_html = f"""
            <div class='empty-state'>
                <h3>🤔 未找到结果</h3>
                <p>没有找到与 "{html.escape(search_term)}" 相关的投稿。</p>
            </div>
            """
        else:
            # 生成项目卡片
            for item in items:
                rows_html += self._generate_item_card(item)
        
        # 计算统计信息
        total_count = len(items)
        anonymous_count = sum(1 for i in items if i.get('is_anonymous'))
        with_images_count = sum(1 for i in items if i.get('has_images'))
        
        # 渲染最终页面（安全转义模板中的花括号，避免与 CSS 冲突）
        template_safe = INDEX_HTML_TEMPLATE.replace('{', '{{').replace('}', '}}')
        for key in ['total_count', 'anonymous_count', 'with_images_count', 'search', 'rows', 'group_options', 'userbar', 'notice_html', 'initial_max_tag', 'main_self_id', 'hide_staging']:
            template_safe = template_safe.replace('{{' + key + '}}', '{' + key + '}')

        # 账户组选项
        group_options_html = ''
        # 仅渲染当前组账号
        for g in list_groups():
            if g['key'] != user['group']:
                continue
            k = html.escape(g['key'])
            main = html.escape(g['mainqqid'])
            if main:
                group_options_html += f'<option value="{main}">{k} - 主账号({main})</option>'
            for i, mid in enumerate(g['minorqqids']):
                ms = html.escape(mid)
                group_options_html += f'<option value="{ms}">{k} - 次要账号{i+1}({ms})</option>'

        userbar = f"<div style='text-align:right;color:#49454F;margin-bottom:8px'>组: {html.escape(user['group'])} | 用户: {html.escape(user['username'])} | <a href='/logout'>退出</a></div>"
        notice_html = ''
        if notice_msg:
            notice_html = f"<div style='margin:8px 0;padding:10px 12px;border-radius:10px;background:#EADDFF;color:#21005D'>{html.escape(urllib.parse.unquote(notice_msg))}</div>"

        initial_max_tag = max([int(i['tag']) for i in items], default=0)
        main_self_id = self._get_group_mainqqid(user['group']) or ''
        # 每次刷新检测当前组配置的 max_post_stack，若为 1 则隐藏暂存区
        hide_staging = 'false'
        try:
            with open(ROOT_DIR / 'AcountGroupcfg.json', 'r', encoding='utf-8') as f:
                cfg = json.load(f) or {}
            gcfg = cfg.get(user['group']) or {}
            mps = int(gcfg.get('max_post_stack', 1))
            if mps == 1:
                hide_staging = 'true'
        except Exception as e:
            # 出错时按默认 1 处理，隐藏暂存区
            hide_staging = 'true'
        page_content = template_safe.format(
            total_count=total_count,
            anonymous_count=anonymous_count,
            with_images_count=with_images_count,
            search=html.escape(search_term),
            rows=rows_html,
            group_options=group_options_html,
            userbar=userbar,
            notice_html=notice_html,
            initial_max_tag=str(initial_max_tag),
            main_self_id=html.escape(main_self_id),
            hide_staging=hide_staging
        )
        
        self.wfile.write(page_content.encode('utf-8'))
    
    def _generate_item_card(self, item):
        """
        生成单个投稿项目的卡片 HTML
        
        Args:
            item (dict): 投稿项目数据
            
        Returns:
            str: 卡片 HTML
        """
        # 生成图片 HTML（内联 data:URI，提升首屏稳定性；失败回退为 /cache 路径）
        images_html = ""
        if item['has_images']:
            for img in item['images']:
                img_src = make_inline_img_src(item['img_source_dir'], item['tag'], img, inline=True)
                fallback = f"/cache/{item['img_source_dir']}/{item['tag']}/{img}"
                images_html += f'<img src="{img_src}" data-fallback="{html.escape(fallback)}" alt="投稿图片" loading="lazy">'
        
        # 生成徽章 HTML
        badges_html = ""
        if item['is_anonymous']:
            badges_html += '<span class="badge badge-anonymous">匿名</span>'
        if item['has_images']:
            badges_html += f'<span class="badge badge-images">{item["image_count"]} 图</span>'
        
        # 转义用户输入
        safe_nickname = html.escape(item.get('nickname') or '未知')
        safe_senderid = html.escape(str(item.get('senderid') or '未知'))
        _comment_raw = item.get('comment') or ''
        safe_comment = html.escape(_comment_raw).replace('\n', '<br>')
        _has_comment = True if _comment_raw.strip() else False
        
        # 生成卡片 HTML
        detail_url = f"/detail?tag={urlquote(item['tag'])}"
        _comment_block = (f"<div class=\"item-comment\">{safe_comment}</div>" if _has_comment else "<div class=\"item-sep\"></div>")
        card_html = f"""
        <div class="item-card">
            <form method="post" action="/">
                <input type="hidden" name="tag" value="{item['tag']}">
                <input type="hidden" name="redirect" value="/">
                <div class="item-content">
                    <div class="item-header">
                        <div class="item-meta">
                            <div class="item-tag">#{item['tag']}</div>
                            <div class="info-item">
                                <strong>投稿人:</strong> {safe_nickname} ({safe_senderid})
                            </div>
                            <div class="info-item">
                                <strong>时间:</strong> {item['submit_time']}
                            </div>
                        </div>
                        <div class="item-badges">{badges_html}</div>
                    </div>
                    {_comment_block}
                    <div class="item-images">{images_html}</div>
                    <div class="comment-form">
                        <textarea name="flag" placeholder="输入评论或拒绝/拉黑原因 (可选)"></textarea>
                    </div>
                </div>
                <div class="item-actions">
                    <a href="{detail_url}" class="btn btn-info">📄 详情</a>
                    <button type="submit" name="cmd" value="是" class="btn btn-success">✅ 通过</button>
                    <button type="submit" name="cmd" value="否" class="btn">🙅 否</button>
                    <button type="submit" name="cmd" value="立即" class="btn btn-info">🚀 立即</button>
                    <button type="submit" name="cmd" value="拒" class="btn btn-warning">⚠️ 拒绝</button>
                    <button type="submit" name="cmd" value="删" class="btn btn-danger">❌ 删除</button>
                    <button type="submit" name="cmd" value="拉黑" class="btn btn-danger">🚫 拉黑</button>
                    <button type="submit" name="cmd" value="评论" class="btn">💬 评论</button>
                    <button type="submit" name="cmd" value="刷新" class="btn">🔄 刷新</button>
                    <button type="submit" name="cmd" value="重渲染" class="btn">🎨 重渲染</button>
                    <button type="submit" name="cmd" value="展示" class="btn">🖼️ 展示</button>
                    <button type="submit" name="cmd" value="查" class="btn btn-info">ℹ️ 查成分</button>
                </div>
            </form>
        </div>
        """
        
        return card_html

    def _get_group_mainqqid(self, group_key: str) -> str | None:
        try:
            with open(ROOT_DIR / 'AcountGroupcfg.json', 'r', encoding='utf-8') as f:
                data = json.load(f)
            if group_key in data:
                return str(data[group_key].get('mainqqid') or '')
        except Exception:
            pass
        return None

    def _run_command_sh(self, object_str: str, self_id: str, web_user: str | None = None):
        if not object_str:
            return 1, 'empty'
        obj_safe = shlex.quote(object_str)
        id_safe = shlex.quote(self_id or '')
        env_prefix = "WEB_REVIEW=1"
        if web_user:
            env_prefix += f" WEB_REVIEW_USER={shlex.quote(web_user)}"
        cmdline = ['bash', '-lc', f"{env_prefix} ./getmsgserv/command.sh {obj_safe} {id_safe}"]
        print(f"[web-review] command.sh -> {object_str} (self_id={self_id})")
        proc = subprocess.run(cmdline, cwd=str(ROOT_DIR), stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        if proc.stdout:
            print('[web-review] command.sh stdout:\n' + proc.stdout)
        if proc.stderr:
            print('[web-review] command.sh stderr:\n' + proc.stderr)
        return proc.returncode, (proc.stdout or proc.stderr)

    # ------------------------------
    # 详情页渲染
    # ------------------------------
    def render_detail_page(self, parsed_path, user):
        query_params = urllib.parse.parse_qs(parsed_path.query)
        tag = (query_params.get('tag') or [''])[0]
        # 优先使用显式 back 路径，否则根据 from=list 退化
        back_to = (query_params.get('back') or [''])[0] or ('/list' if ((query_params.get('from') or [''])[0] == 'list') else '/')
        if not tag or not tag.isdigit():
            self.send_error(400, "Bad Request: missing or invalid tag")
            return

        item = self._get_item(tag)
        if not item:
            self.send_error(404, "Not Found: tag not found")
            return
        # 组权限校验
        if str(item.get('ACgroup')) != str(user['group']):
            self.send_error(403, 'Forbidden')
            return

        # 读取详情模板
        detail_tpl_path = SCRIPT_DIR / 'detail_template.html'
        if detail_tpl_path.exists():
            template = detail_tpl_path.read_text(encoding='utf-8')
        else:
            # 简单降级模板
            template = """
<!doctype html>
<html lang=\"zh-CN\"><head><meta charset=\"utf-8\"><meta name=\"viewport\" content=\"width=device-width, initial-scale=1\"><link rel=\"manifest\" href=\"/manifest.webmanifest\"><meta name=\"theme-color\" content=\"#6750A4\"><link rel=\"apple-touch-icon\" href=\"/static/icons/icon-192.png\"><title>稿件详情 #{tag}</title>
<style>body{font-family:Arial,Helvetica,sans-serif;padding:16px;max-width:900px;margin:0 auto}img{max-width:100%;height:auto;border-radius:8px}pre{white-space:pre-wrap;background:#f6f6f6;padding:12px;border-radius:8px;overflow:auto}</style>
</head><body>
<h1>稿件详情 #{tag}</h1>
<p><a href=\"/\">← 返回列表</a></p>
<form method=\"post\" action=\"/\" style=\"display:grid;grid-template-columns:repeat(3,1fr);gap:8px;margin:8px 0\"> 
<input type=\"hidden\" name=\"tag\" value=\"{tag}\"> 
<input type=\"hidden\" name=\"redirect\" value=\"/detail?tag={tag}\"> 
<!-- 行1：拉黑 | 输入 | 评论 -->
<button name=\"cmd\" value=\"拉黑\">拉黑</button>
<input type=\"text\" name=\"flag\" placeholder=\"评论或拒绝/拉黑原因(可选)\" style=\"padding:8px; border:1px solid #ddd; border-radius:8px\"> 
<button name=\"cmd\" value=\"评论\">评论</button>
<!-- 行2：重渲染 | 展示 | 查成分 -->
<button name=\"cmd\" value=\"重渲染\">重渲染</button>
<button name=\"cmd\" value=\"展示\">展示</button>
<button name=\"cmd\" value=\"查\">查成分</button>
<!-- 行3：刷新 | 拒绝 | 否 -->
<button name=\"cmd\" value=\"刷新\">刷新</button>
<button name=\"cmd\" value=\"拒\">拒绝</button>
<button name=\"cmd\" value=\"否\">否</button>
<!-- 行4：删除 | 立即 | 通过 -->
<button name=\"cmd\" value=\"删\">删除</button>
<button name=\"cmd\" value=\"立即\">立即</button>
<button name=\"cmd\" value=\"是\">通过</button>
</form>
<h3>投稿信息</h3>
<ul>
<li>投稿人: {nickname} ({senderid})</li>
<li>时间: {submit_time}</li>
<li>目标群: {ACgroup} / {receiver}</li>
<li>匿名: {is_anonymous}</li>
</ul>
<h3>内容</h3>
<div>{comment_html}</div>
<h3>渲染预览</h3>
<iframe src=\"/detail_html?tag={tag}\" style=\"width:100%;height:420px;border:1px solid #e5e5ef;border-radius:12px;background:#fff\"></iframe>
<h3>图片</h3>
<details open>
<summary style=\"cursor:pointer;user-select:none\">图片（{image_count}）</summary>
<div style=\"margin-top:8px\">{images_html}</div>
</details>
<h3>AfterLM</h3>
<details><summary style=\"cursor:pointer;user-select:none\">展开/收起</summary>
<pre>{afterlm_pretty}</pre>
</details>
<script>if('serviceWorker' in navigator){window.addEventListener('load',()=>{navigator.serviceWorker.register('/sw.js').catch(()=>{});});}</script></body></html>
"""

        # 构造图片 HTML（优先内联为 data:URI，避免首屏偶发加载失败）
        images_html = ""
        if item['has_images']:
            for img in item['images']:
                img_src = make_inline_img_src(item['img_source_dir'], item['tag'], img, inline=True)
                images_html += f'<img src="{img_src}" alt="投稿图片" loading="lazy" style="max-width:100%;margin:6px 0">'

        comment_html = html.escape(item.get('comment') or '').replace('\n', '<br>')
        afterlm_pretty = html.escape(json.dumps(item.get('afterlm') or {}, ensure_ascii=False, indent=2))

        # 响应
        self.send_response(200)
        tok = None
        try:
            tok = (parse_cookies(self.headers.get('Cookie')) or {}).get(SESSION_COOKIE_NAME)
        except Exception:
            tok = None
        if tok:
            self._issue_session_cookie(tok)
        self.send_header("Content-type", "text/html; charset=utf-8")
        self.end_headers()
        page = template
        # 顶部提示（可选）
        notice_msg = (urllib.parse.parse_qs(parsed_path.query).get('notice') or [''])[0]
        banner = ''
        if notice_msg:
            banner = f"<div style='margin:8px 0;padding:10px 12px;border-radius:10px;background:#EADDFF;color:#21005D'>{html.escape(urllib.parse.unquote(notice_msg))}</div>"
        # 安全替换占位符
        replacements = {
            '{tag}': item['tag'],
            '{nickname}': html.escape(item.get('nickname') or '未知'),
            '{senderid}': html.escape(str(item.get('senderid') or '未知')),
            '{submit_time}': item.get('submit_time') or '未知',
            '{ACgroup}': html.escape(str(item.get('ACgroup') or '')),
            '{receiver}': html.escape(str(item.get('receiver') or '')),
            '{is_anonymous}': '是' if item.get('is_anonymous') else '否',
            '{comment_html}': comment_html,
            '{images_html}': images_html,
            '{afterlm_pretty}': afterlm_pretty,
            '{image_count}': str(item.get('image_count') or 0),
            '{notice_html}': banner,
        }
        for k, v in replacements.items():
            page = page.replace(k, v)
        # 替换/注入返回链接为 back_to
        try:
            # 优先替换带 class="back" 的锚点
            page = re.sub(r'(class=\"back\"[^>]*href=)\"[^\"]*\"', r'\1"' + back_to + '"', page, count=1)
        except Exception:
            pass
        if 'class="back"' not in page:
            # 若没有提供 back 链接，则在 <body> 后插入一个
            page = page.replace('<body>', f'<body><div style="margin:8px 0;text-align:left"><a class="back" href="{back_to}">← 返回列表</a></div>', 1)
        self.wfile.write(page.encode('utf-8'))

    def render_list_page(self, parsed_path, user):
        """渲染列表视图页面（供 iframe 使用）。"""
        query_params = urllib.parse.parse_qs(parsed_path.query)
        search_term = query_params.get('search', [''])[0]
        items = list_pending(search=search_term, group_filter=user['group'])
        back_path = '/list' + (('?' + urllib.parse.urlencode({'search': search_term})) if search_term else '')
        rows_html = ''.join(self._generate_list_card(i, back_path=back_path) for i in items)
        # 读取当前组配置，若 max_post_stack == 1 则隐藏暂存区
        hide_staging = 'false'
        try:
            with open(ROOT_DIR / 'AcountGroupcfg.json', 'r', encoding='utf-8') as f:
                cfg = json.load(f) or {}
            gcfg = cfg.get(user['group']) or {}
            mps = int(gcfg.get('max_post_stack', 1))
            if mps == 1:
                hide_staging = 'true'
        except Exception:
            hide_staging = 'true'
        html_out = LIST_HTML_TEMPLATE.replace('{rows}', rows_html).replace('{hide_staging}', hide_staging)
        self.send_response(200)
        tok = None
        try:
            tok = (parse_cookies(self.headers.get('Cookie')) or {}).get(SESSION_COOKIE_NAME)
        except Exception:
            tok = None
        if tok:
            self._issue_session_cookie(tok)
        self.send_header('Content-type', 'text/html; charset=utf-8')
        self.end_headers()
        self.wfile.write(html_out.encode('utf-8'))

    def _generate_list_card(self, item: dict, back_path: str | None = None) -> str:
        """列表模式卡片：左文字+图，右三键（详情/通过/删除）。"""
        # 图片缩略图
        images_html = ""
        if item.get('has_images'):
            cnt = 0
            for img in item.get('images') or []:
                if cnt >= 6:
                    break
                img_src = make_inline_img_src(item['img_source_dir'], item['tag'], img, inline=True)
                fallback = f"/cache/{item['img_source_dir']}/{item['tag']}/{img}"
                images_html += f'<img src="{img_src}" data-fallback="{html.escape(fallback)}" alt="图片" loading="lazy">'
                cnt += 1
        # 徽章
        badges_html = ""
        if item.get('is_anonymous'):
            badges_html += '<span class="badge badge-anonymous">匿名</span>'
        if item.get('has_images'):
            badges_html += f'<span class="badge badge-images">{int(item.get("image_count") or 0)} 图</span>'
        # 文本
        tag = html.escape(item.get('tag') or '?')
        comment = html.escape((item.get('comment') or '').replace('\n',' ').strip())
        if len(comment) > 120:
            comment = comment[:120] + '…'
        nickname = html.escape(item.get('nickname') or '未知')
        senderid = html.escape(str(item.get('senderid') or ''))
        submit_time = html.escape(item.get('submit_time') or '')
        # 详情链接携带返回路径，优先使用传入的 back_path
        b = back_path or '/list'
        detail_url = f"/detail?tag={urlquote(item['tag'])}&back={urlquote(b)}"

        return f"""
        <div class=\"l-card\"> 
          <form method=\"post\" action=\"/\" class=\"l-form\"> 
            <input type=\"hidden\" name=\"tag\" value=\"{tag}\"> 
            <div class=\"l-wrap\"> 
              <i-left class=\"l-left\"> 
                <div class=\"l-top\"><label class=\"l-select\"><input type=\"checkbox\" class=\"sel\" value=\"{tag}\"></label><span class=\"l-tag\">#{tag}</span><span class=\"l-comment\">{comment or '[仅图片投稿]'} </span></div> 
                <div class=\"l-meta\"><div>投稿人：{nickname}{(' ('+senderid+')') if senderid else ''}</div><div>时间：{submit_time}</div></div> 
              </i-left> 
              <i-image class=\"l-images\">{images_html}</i-image> 
            </div> 
            <i-right class=\"l-right\"> 
              <div class=\"l-actions\">
                <a href=\"{detail_url}\" class=\"btn btn-info l-action-btn\">📄<span class=\"text\"> 详情</span></a>
                <button type=\"button\" class=\"btn btn-success act l-action-btn\" data-cmd=\"是\">✅<span class=\"text\"> 通过</span></button>
                <button type=\"button\" class=\"btn btn-danger act l-action-btn\" data-cmd=\"删\">🗑️<span class=\"text\"> 删除</span></button>
              </div> 
            </i-right> 
            <badge class=\"l-badges\">{badges_html}</badge> 
          </form> 
        </div> 
        """

    def _get_item(self, tag: str):
        rows = list_pending()
        for r in rows:
            if r.get('tag') == tag:
                return r
        return None

    def render_detail_html(self, parsed_path, user):
        query = urllib.parse.parse_qs(parsed_path.query)
        tag = (query.get('tag') or [''])[0]
        if not tag.isdigit():
            self.send_error(400, 'Bad Request')
            return
        # 权限校验
        row = db_query("SELECT ACgroup FROM preprocess WHERE tag = ?", (tag,))
        if not row or str(row[0].get('ACgroup')) != str(user['group']):
            self.send_error(403, 'Forbidden')
            return
        # 运行渲染脚本
        try:
            cmd = [
                'bash','-lc',
                f"getmsgserv/HTMLwork/gotohtml.sh {tag} > /dev/shm/OQQWall/oqqwallhtmlcache.html"
            ]
            subprocess.run(cmd, cwd=str(ROOT_DIR), stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=20)
        except Exception as e:
            print(f"[web-review] 渲染预览失败: {e}")
        # 读取渲染结果
        html_path = Path('/dev/shm/OQQWall/oqqwallhtmlcache.html')
        if not html_path.exists():
            self.send_response(200)
            self.send_header('Content-type', 'text/html; charset=utf-8')
            self.end_headers()
            self.wfile.write("<p style='color:#B3261E'>无法生成渲染预览</p>".encode('utf-8'))
            return
        content = html_path.read_text(encoding='utf-8', errors='ignore')
        # 内嵌 file:// 图片为 data URI（仅限项目目录内文件）
        def repl_img(m):
            url = m.group(1)
            if not url.startswith('file://'):
                return m.group(0)
            file_path = url[7:]
            try:
                p = Path(file_path).resolve()
                root = ROOT_DIR.resolve()
                if not str(p).startswith(str(root)):
                    return m.group(0)
                if not p.is_file():
                    return m.group(0)
                data = p.read_bytes()
                # 优先按文件头嗅探 MIME，避免后缀与内容不一致导致无法显示
                mime = None
                try:
                    if len(data) >= 12 and data[0:8] == b"\x89PNG\r\n\x1a\x0a":
                        mime = 'image/png'
                    elif len(data) >= 3 and data[0:2] == b"\xff\xd8":
                        mime = 'image/jpeg'
                    elif len(data) >= 6 and (data[0:6] == b"GIF87a" or data[0:6] == b"GIF89a"):
                        mime = 'image/gif'
                    elif len(data) >= 12 and data[0:4] == b"RIFF" and data[8:12] == b"WEBP":
                        mime = 'image/webp'
                    elif len(data) >= 2 and data[0:2] == b"BM":
                        mime = 'image/bmp'
                except Exception:
                    mime = None
                if not mime:
                    # fallback by suffix
                    ext = p.suffix.lower()
                    if ext in ('.jpg', '.jpeg'):
                        mime = 'image/jpeg'
                    elif ext == '.gif':
                        mime = 'image/gif'
                    elif ext == '.webp':
                        mime = 'image/webp'
                    elif ext == '.bmp':
                        mime = 'image/bmp'
                    else:
                        mime = 'image/png'
                b64 = base64.b64encode(data).decode('ascii')
                return f"src=\"data:{mime};base64,{b64}\""
            except Exception as e:
                print(f"[web-review] 内嵌图片失败: {e}")
                return m.group(0)
        # 替换 <img src="file://...">
        content = re.sub(r'src=\"(file://[^\"]+)\"', repl_img, content)
        self.send_response(200)
        tok = None
        try:
            tok = (parse_cookies(self.headers.get('Cookie')) or {}).get(SESSION_COOKIE_NAME)
        except Exception:
            tok = None
        if tok:
            self._issue_session_cookie(tok)
        self.send_header('Content-type', 'text/html; charset=utf-8')
        self.end_headers()
        self.wfile.write(content.encode('utf-8', errors='ignore'))

    # 登录/注销与用户获取
    def _render_login(self, msg_html: str = ""):
        self.send_response(200)
        self.send_header("Content-type", "text/html; charset=utf-8")
        self.end_headers()
        page = LOGIN_HTML_TEMPLATE.replace('{msg}', msg_html or '')
        self.wfile.write(page.encode('utf-8'))

    def _logout(self):
        # 清理 cookie（客户端覆盖），删除服务端会话
        jar = parse_cookies(self.headers.get('Cookie'))
        token = jar.get(SESSION_COOKIE_NAME) or jar.get('session')
        if token and token in SESSION_STORE:
            del SESSION_STORE[token]
        self.send_response(303)
        self.send_header('Set-Cookie', f'{SESSION_COOKIE_NAME}=deleted; Expires=Thu, 01 Jan 1970 00:00:00 GMT; Path=/')
        self.send_header('Location', '/login')
        self.end_headers()

    def _get_user(self):
        jar = parse_cookies(self.headers.get('Cookie'))
        # 兼容旧 cookie 名称 'session'
        token = jar.get(SESSION_COOKIE_NAME) or jar.get('session')
        if not token:
            return None
        rec = SESSION_STORE.get(token)
        if not rec:
            return None
        # TTL 校验与滚动续期
        try:
            created = float(rec.get('created') or 0)
        except Exception:
            created = 0.0
        now = time.time()
        if created and (now - created > SESSION_TTL_SECONDS):
            # 过期
            try:
                del SESSION_STORE[token]
            except Exception:
                pass
            return None
        # 滚动续期：每次访问刷新创建时间
        rec['created'] = now
        return rec

# ============================================================================
# 服务器启动函数
# ============================================================================

class ReuseAddrTCPServer(socketserver.TCPServer):
    pass

class ThreadingReuseAddrServer(socketserver.ThreadingMixIn, socketserver.TCPServer):
    # 确保工作线程为守护线程，避免 Ctrl+C 后被非守护线程阻塞退出
    daemon_threads = True
    allow_reuse_address = True
    def server_bind(self):
        try:
            self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        except Exception:
            pass
        # 尝试启用 REUSEPORT（如果系统支持）
        try:
            if hasattr(socket, 'SO_REUSEPORT'):
                self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEPORT, 1)
        except Exception:
            pass
        return super().server_bind()

def run_server(host='0.0.0.0', port=10923):
    """
    启动 Web 服务器
    
    Args:
        host (str): 监听地址
        port (int): 监听端口
    """
    try:
        server_cls = ThreadingReuseAddrServer
        with server_cls((host, port), ReviewServer) as httpd:
            print("=" * 50)
            print("🚀 OQQWall 审核面板已启动")
            print("=" * 50)
            
            display_host = 'localhost' if host == '0.0.0.0' else host
            print(f"📍 本地访问: http://localhost:{port}")
            print(f"🌐 外部访问: http://{display_host}:{port}")
            print("=" * 50)
            print("按 Ctrl+C 停止服务器")
            print("=" * 50)
            
            # 后台监测新投稿（每5秒），用于即时提示
            def poll_new():
                # 记录每个组的上一次待审核集合与最大 tag
                last_max = {}
                last_pending: dict[str, set] = {}
                while True:
                    try:
                        with EVENT_LOCK:
                            groups = list(set(g for g,_ in EVENT_CLIENTS))
                        # 若暂无订阅者则休眠
                        if not groups:
                            time.sleep(5)
                            continue
                        for grp in groups:
                            items = list_pending(search=None, group_filter=grp)
                            tags_now = {str(i['tag']) for i in items}
                            max_tag = max([int(i['tag']) for i in items], default=0)

                            # 新增项目提示（沿用原有 max_tag 逻辑）
                            if last_max.get(grp, 0) and max_tag > last_max.get(grp, 0):
                                broadcast_event({"type":"new_pending","max_tag":max_tag}, target_group=grp)
                            last_max[grp] = max_tag

                            # 处理掉的项目：上次有，这次没了
                            prev = last_pending.get(grp, set())
                            removed = prev - tags_now
                            if removed:
                                for t in removed:
                                    try:
                                        broadcast_event({"type":"processed", "tag": t}, target_group=grp)
                                    except Exception:
                                        pass
                            last_pending[grp] = tags_now
                        time.sleep(5)
                    except Exception:
                        time.sleep(5)

            t = threading.Thread(target=poll_new, daemon=True)
            t.start()
            try:
                httpd.serve_forever()
            except KeyboardInterrupt:
                # 优雅关闭：停止事件循环并关闭监听套接字
                print("\n🛑 服务器已停止")
                try:
                    httpd.shutdown()
                except Exception:
                    pass
                try:
                    httpd.server_close()
                except Exception:
                    pass
                # 立即退出主进程，避免需要再次 Ctrl+C
                sys.exit(0)
    except OSError as e:
        if 'Address already in use' in str(e) or getattr(e, 'errno', None) in (98, 48):
            print("❌ 端口被占用 (可能处于 TIME_WAIT)。")
            print("提示: 可换一个端口 (--port)，或稍候重试。")
            print("已启用 SO_REUSEADDR/SO_REUSEPORT，若仍失败说明确有进程占用该端口。")
        else:
            raise


# ============================================================================
# 主程序入口
# ============================================================================

if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="OQQWall Web Review Panel - 校园墙投稿审核系统",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
使用示例:
  python web_review.py                    # 使用默认设置启动
  python web_review.py --host 127.0.0.1  # 仅本地访问
  python web_review.py --port 8080       # 使用自定义端口
        """
    )
    
    parser.add_argument(
        '--host', 
        type=str, 
        default='0.0.0.0', 
        help='服务器监听的地址 (默认: 0.0.0.0)'
    )
    parser.add_argument(
        '--port', 
        type=int, 
        default=10923, 
        help='服务器监听的端口 (默认: 10923)'
    )
    
    args = parser.parse_args()
    run_server(host=args.host, port=args.port)
