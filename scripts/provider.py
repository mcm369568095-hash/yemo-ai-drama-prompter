# -*- coding: utf-8 -*-
"""夜秣AI短剧生成器 · ③（可选）视频通道引擎

本技能的主产物是**提示词**，出片是加餐。这个脚本只做一件事：
**让「接一个新视频模型」变成改一行 yaml，而不是改一堆代码。**

三种通道：
    local_ffmpeg  —— Ken Burns 兜底（成本 0，永不失败）
    http_api      —— REST 风格（异步轮询 / 同步都支持）
    cli           —— 本地或云端命令行工具

任何通道失败 → 自动回落到 kenburns，流水线永不断电。

🔴 本脚本**不含任何密钥**。http_api 通道从环境变量读 key（配置里写 key_env 名字）。
"""
import os
import re
import json
import time
import base64
import shutil
import subprocess
from abc import ABC, abstractmethod

# ---------------- ffmpeg 定位：环境变量 > PATH ----------------
FFMPEG = os.environ.get("FFMPEG") or shutil.which("ffmpeg") or "ffmpeg"
FFPROBE = os.environ.get("FFPROBE") or shutil.which("ffprobe") or "ffprobe"

CFG = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                   "providers", "providers.yaml")


def log(*a):
    print(*a, flush=True)


def load_cfg(path=CFG):
    import yaml
    with open(path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def run(cmd, timeout=300, **kw):
    kw.setdefault("capture_output", True)
    kw.setdefault("text", True)
    kw.setdefault("encoding", "utf-8")
    kw.setdefault("errors", "ignore")
    try:
        return subprocess.run(cmd, timeout=timeout, **kw)
    except subprocess.TimeoutExpired:
        return subprocess.CompletedProcess(cmd, -9, "", "TIMEOUT")


def dur(p):
    r = run([FFPROBE, "-v", "error", "-show_entries", "format=duration",
             "-of", "default=nw=1:nk=1", str(p)], timeout=60)
    try:
        return float((r.stdout or "0").strip())
    except Exception:
        return 0.0


# ==================================================================
# 镜头语法表 —— Ken Burns 的灵魂，让静态图也能有呼吸感
#   zoom  : z 从 z0 走到 z1
#   pan   : 画面中心沿向量漂移
#   punch : 前 35% 帧数完成 80% 的推进（冲击感，用于高潮句）
# ==================================================================
LENS = {
    "kb_in":     dict(z0=1.00, z1=1.18, pan=(0.00, 0.00), punch=False),
    "kb_out":    dict(z0=1.18, z1=1.00, pan=(0.00, 0.00), punch=False),
    "kb_left":   dict(z0=1.10, z1=1.10, pan=(-0.06, 0.00), punch=False),
    "kb_right":  dict(z0=1.10, z1=1.10, pan=(0.06, 0.00), punch=False),
    "kb_up":     dict(z0=1.10, z1=1.10, pan=(0.00, -0.05), punch=False),
    "kb_down":   dict(z0=1.10, z1=1.10, pan=(0.00, 0.05), punch=False),
    "kb_in_l":   dict(z0=1.00, z1=1.16, pan=(-0.04, 0.00), punch=False),
    "zoom_punch": dict(z0=1.00, z1=1.32, pan=(0.00, 0.00), punch=True),
    "static":    dict(z0=1.00, z1=1.00, pan=(0.00, 0.00), punch=False),
}


def _zoompan_filter(cfg_dur, fps, W, H, lens):
    L = LENS.get(lens, LENS["kb_in"])
    frames = max(int(cfg_dur * fps), 2)
    z0, z1 = L["z0"], L["z1"]
    px, py = L["pan"]

    if z1 == z0 and px == 0 and py == 0:          # static：不用 zoompan
        return f"scale={W*2}:{H*2},crop={W}:{H},fps={fps}"

    span = max(z1 - z0, 1e-6)
    if L["punch"]:
        zexpr = (f"if(lte(on,{int(frames*0.35)}),{z0}+{span}*(on/{max(int(frames*0.35),1)})^2*0.8,"
                 f"{z0}+{span}*0.8+{span}*0.2*((on-{int(frames*0.35)})/{max(frames-int(frames*0.35),1)}))")
    else:
        zexpr = f"{z0}+{span}*(on/{frames})"

    xexpr = f"iw/2-(iw/zoom/2)+iw*{px}*(on/{frames})"
    yexpr = f"ih/2-(ih/zoom/2)+ih*{py}*(on/{frames})"
    pre = f"scale={W*2}:{H*2}:force_original_aspect_ratio=increase,crop={W*2}:{H*2},"
    return (pre + f"zoompan=z='{zexpr}':x='{xexpr}':y='{yexpr}'"
                  f":d={frames}:s={W}x{H}:fps={fps}")


# ==================================================================
# Provider 基类与三种实现
# ==================================================================
class Provider(ABC):
    def __init__(self, key, cfg):
        self.key, self.cfg = key, cfg or {}

    @abstractmethod
    def gen(self, shot, out, seconds, size, fps, crf):
        """生成单个镜头，返回 True/False"""


class KenBurnsProvider(Provider):
    """本地 ffmpeg：把一张静态图推拉成有呼吸感的运动镜头。成本 0，永不失败。"""

    def image_of(self, shot, workdir):
        for k in ("image", "first_frame", "still"):
            p = shot.get(k)
            if p and os.path.exists(p):
                return p
        fid = shot.get("id")
        if fid:
            for sub in ("ff", "frames", "images"):
                for ext in (".png", ".jpg", ".jpeg"):
                    cand = os.path.join(workdir, sub, f"{fid}{ext}")
                    if os.path.exists(cand):
                        return cand
        return None

    def gen(self, shot, out, seconds, size, fps, crf):
        W, H = (int(x) for x in size.split("x"))
        img = self.image_of(shot, shot.get("_workdir", "."))
        if not img:
            log(f"    [KB] 找不到底图 shot={shot.get('id')}")
            return False
        lens = shot.get("lens", "kb_in")
        vf = _zoompan_filter(seconds, fps, W, H, lens)
        fade = f",fade=t=in:st=0:d=0.4,fade=t=out:st={max(seconds-0.4,0.01)}:d=0.4"
        cmd = [FFMPEG, "-y", "-loop", "1", "-i", img, "-vf", vf + fade,
               "-t", str(seconds), "-c:v", "libx264", "-crf", str(crf),
               "-pix_fmt", "yuv420p", "-r", str(fps), "-an", out]
        os.makedirs(os.path.dirname(os.path.abspath(out)), exist_ok=True)
        r = run(cmd, timeout=300)
        if r.returncode != 0 or not os.path.exists(out):
            log(f"    [KB] FAIL shot={shot.get('id')} :: {(r.stderr or '')[-260:]}")
            return False
        return True


class HttpApiProvider(Provider):
    """REST 视频模型：提交 → 轮询 → 下载。适配绝大多数云端视频 API。"""

    def _dig(self, obj, path):
        cur = obj
        for seg in (path or "").split("."):
            if cur is None:
                return None
            if isinstance(cur, dict):
                cur = cur.get(seg)
            elif isinstance(cur, list) and seg.isdigit():
                cur = cur[int(seg)]
            else:
                return None
        return cur

    def gen(self, shot, out, seconds, size, fps, crf):
        import requests
        key = os.environ.get(self.cfg.get("key_env", ""), "")
        hdr = {"Content-Type": "application/json"}
        if key:
            tok = (self.cfg.get("auth_header") or "Authorization: Bearer {key}").replace("{key}", key)
            k, _, v = tok.partition(":")
            hdr[k.strip()] = v.strip()

        body = {}
        for k, v in (self.cfg.get("request") or {}).items():
            body[k] = _fill(str(v), shot, seconds, size, out)
        if self.cfg.get("model"):
            body.setdefault("model", self.cfg["model"])

        endpoint = self.cfg["endpoint"]
        try:
            r = requests.post(endpoint, headers=hdr, json=body, timeout=90)
        except Exception as e:
            log(f"    [API] 提交异常: {str(e)[:140]}")
            return False
        if r.status_code >= 400:
            log(f"    [API] HTTP {r.status_code} :: {r.text[:220]}")
            return False
        data = json.loads(r.content.decode("utf-8"))

        poll = self.cfg.get("poll")
        if not poll:  # 同步返回
            return self._save(data, out)

        tid = self._dig(data, poll.get("task_id_path", "id"))
        if not tid:
            log(f"    [API] 拿不到任务 ID：{json.dumps(data, ensure_ascii=False)[:200]}")
            return False
        status_url = poll.get("status_url") or endpoint
        if poll.get("status_url_tpl"):
            status_url = poll["status_url_tpl"].replace("{id}", str(tid))
        q = poll.get("status_query") or ""
        if q:
            status_url = f"{status_url}{'&' if '?' in status_url else '?'}{q.replace('{id}', str(tid))}"

        waited, iv = 0, int(poll.get("interval", 8))
        maxw = int(poll.get("max_wait", 600))
        done = poll.get("status_done") or ["succeeded", "success", "completed"]
        fail = poll.get("status_fail") or ["failed", "error", "cancelled"]
        while waited < maxw:
            time.sleep(iv)
            waited += iv
            try:
                rr = requests.get(status_url, headers=hdr, timeout=60)
                d = json.loads(rr.content.decode("utf-8"))
            except Exception as e:
                log(f"    [API] 轮询异常 {str(e)[:100]}")
                continue
            st = str(self._dig(d, poll.get("status_path", "status"))).lower()
            if st in [s.lower() for s in done]:
                return self._save(d, out)
            if st in [s.lower() for s in fail]:
                log(f"    [API] 任务失败 status={st} :: {json.dumps(d, ensure_ascii=False)[:200]}")
                return False
        log(f"    [API] 轮询超时 {maxw}s")
        return False

    def _save(self, data, out):
        import requests
        poll = self.cfg.get("poll") or {}
        os.makedirs(os.path.dirname(os.path.abspath(out)), exist_ok=True)
        if (poll.get("result_kind") or "url") == "base64":
            b64 = self._dig(data, poll.get("result_path", "data.video"))
            if not b64:
                return False
            with open(out, "wb") as f:
                f.write(base64.b64decode(b64))
            return os.path.exists(out)
        url = self._dig(data, poll.get("result_path") or "data.video_url")
        if not url:
            log(f"    [API] 响应里找不到视频地址：{json.dumps(data, ensure_ascii=False)[:200]}")
            return False
        dh = dict(self.cfg.get("download_headers") or {})
        dh.setdefault("User-Agent", "Mozilla/5.0")
        r = requests.get(str(url).replace("http://", "https://"), headers=dh, timeout=240, stream=True)
        if r.status_code >= 400:
            log(f"    [API] 下载失败 {r.status_code}")
            return False
        with open(out, "wb") as f:
            for c in r.iter_content(1 << 16):
                f.write(c)
        return os.path.exists(out) and os.path.getsize(out) > 1024


class CliProvider(Provider):
    def gen(self, shot, out, seconds, size, fps, crf):
        os.makedirs(os.path.dirname(os.path.abspath(out)), exist_ok=True)
        tpl = self.cfg["cmd"]
        cmd = _fill(tpl, shot, seconds, size, out)
        r = run(cmd, timeout=int(self.cfg.get("timeout", 600)),
                shell=bool(self.cfg.get("shell", False)))
        if r.returncode != 0 or not os.path.exists(out):
            log(f"    [CLI] FAIL :: {(r.stderr or '')[-240:]}")
            return False
        return True


def _fill(tpl, shot, seconds, size, out):
    return (tpl.replace("{prompt}", str(shot.get("prompt", "")))
               .replace("{duration}", str(int(seconds)))
               .replace("{size}", str(size))
               .replace("{out}", str(out))
               .replace("{first_frame}", str(shot.get("first_frame", ""))))


def build(kind, cfg_all=None):
    cfg_all = cfg_all or load_cfg()
    node = (cfg_all.get("providers") or {}).get(kind) or {}
    t = node.get("type", "local_ffmpeg")
    return {"local_ffmpeg": KenBurnsProvider, "http_api": HttpApiProvider,
            "cli": CliProvider}.get(t, KenBurnsProvider)(kind, node)


def gen_shot(shot, outdir, cfg_all=None, verbose=True):
    """带兜底的单镜头生成。返回最终用到的 provider key。"""
    cfg_all = cfg_all or load_cfg()
    pol = cfg_all.get("policy") or {}
    outcfg = cfg_all.get("output") or {}
    size = outcfg.get("size", "1920x1080")
    fps = int(outcfg.get("fps", 25))
    crf = int(outcfg.get("crf", 20))
    seconds = float(shot.get("duration") or 6)

    want = shot.get("provider") or cfg_all.get("default", "kenburns")
    getout = lambda k: os.path.join(outdir, f"{shot.get('id','s00')}.mp4")
    out = getout(want)

    if os.path.exists(out) and os.path.getsize(out) > 2048:
        return want

    order = [want]
    fb = pol.get("fallback_to", "kenburns")
    if fb != want:
        order.append(fb)
    for kind in order:
        p = build(kind, cfg_all)
        retries = 1 if kind == want else 0
        for att in range(retries + 1):
            try:
                ok = p.gen(shot, getout(kind), seconds, size, fps, crf)
            except Exception as e:
                ok = False
                log(f"    [{kind}] EXC {str(e)[:160]}")
            if ok and os.path.exists(getout(kind)) and os.path.getsize(getout(kind)) > 2048:
                if verbose:
                    log(f"    [{kind}] OK {shot.get('id')}  {round(dur(getout(kind)),2)}s")
                return kind
            if att < retries:
                time.sleep(3)
        if verbose:
            log(f"    [{kind}] 失败，降级中…")
    return None
