#!/usr/bin/env python3
"""校准本插件的静态模型清单（Qwen / Bailian Third-party 两行）。

清单是 `fallback_models` 里的**静态快照**（`supports_model_listing=False`），不会自己去拉目录：
百炼换名／下线后，条目会静默失效——Hermes 选择器里照样列出，选中必然报错。这个脚本用来重算它。

判据（踩过才知道，别简化）：

1. **不在目录里 ≠ 调不通**。百炼的 `/models` 目录不是可用性清单：`qwen-turbo` 不在目录里、调用却正常。
   所以脚本对「声明 − 目录」的每个条目都发一次最小 chat 请求，只有确认 `does not exist` 才算死条目；
   403（未开通）/429（限流）/「缺参数」一律归「待人工」，**绝不自动删**。
2. **目录里有、但调不通的也不能加**（`qwen1.5-7b-chat` 这类）。
3. 图像／语音／嵌入等非聊天模型（image / wan / tts / asr / realtime / embedding …）在 chat 端点必然
   报 `model_not_found`，但这不是「下线」，只是不该进聊天行；`sre-` / `test-` 这类内部测试项同理。
4. 两行共用同一端点，所以要**按端点整体算差集**：分别按行算的话，Qwen 行会把第三方模型全当新增。

用法：

    python tools/calibrate.py                      # 只读体检，打印报告（有要动作的条目时退出码 1）
    python tools/calibrate.py --no-probe           # 只做目录 diff，不发探测请求
    python tools/calibrate.py --apply              # 把确认下线的条目从清单里删掉（改 __init__.py）
    python tools/calibrate.py --add glm-5.4 --to OTHERS_MODELS   # 手工加入条目到指定清单开头

key：环境变量 `DASHSCOPE_API_KEY` 优先，其次 `./.env`（本仓库根目录），再其次 `$HERMES_HOME/.env`。

`--apply` 只改清单本身：改完请 `git diff` 过一眼、更新 README 里的计数与 plugin.yaml 的 version，
再 commit。脚本不碰 README、不碰版本号、不 commit。
"""
import argparse
import json
import os
import re
import sys
import time
import urllib.error
import urllib.request

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/124 Safari/537.36")
NON_CHAT = ("tts", "asr", "speech", "realtime", "livetranslate", "image", "wanx", "wan2",
            "z-image", "embedding", "rerank", "ocr", "seedream", "moderation", "bge", "whisper")
NOISE = ("sre-", "test-", "test_", "-test", "internal", "debug", "sandbox", "dummy")
REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LIST_CAP = 12


def is_chat(mid):
    return not any(k in str(mid).lower() for k in NON_CHAT)


def is_noise(mid):
    return any(k in str(mid).lower() for k in NOISE)


def env_key(name, env_file):
    if os.environ.get(name):
        return os.environ[name]
    for path in (env_file, os.path.join(os.environ.get("HERMES_HOME", ""), ".env")):
        if not path or not os.path.exists(path):
            continue
        with open(path, encoding="utf-8", errors="ignore") as fh:
            for line in fh:
                m = re.match(r"^\s*([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(.*)$", line)
                if m and m.group(1) == name:
                    return m.group(2).strip().strip('"').strip("'")
    return ""


def tuple_block(src, name):
    """返回 (起点, 终点前, 条目列表)；找不到返回 None。"""
    marker = "%s = (" % name
    i = src.find(marker)
    if i < 0:
        return None
    j = src.find("\n)", i)
    if j < 0:
        return None
    return i, j, re.findall(r'"([^"]+)"', src[i:j])


def parse_providers(src):
    out = []
    for chunk in src.split("register_provider(")[1:]:
        end = chunk.find("\n)")
        block = chunk[:end if end >= 0 else len(chunk)]
        if "fallback_models" not in block:
            continue

        def grab(key, _b=block):
            m = re.search(r'%s\s*=\s*"([^"]*)"' % key, _b)
            return m.group(1) if m else ""

        envs = re.search(r"env_vars\s*=\s*\((.*?)\)", block, re.S)
        m = re.search(r"fallback_models\s*=\s*([A-Za-z_][A-Za-z0-9_]*)", block)
        tb = tuple_block(src, m.group(1)) if m else None
        out.append({"name": grab("name"), "display_name": grab("display_name"),
                    "base_url": grab("base_url"),
                    "env_vars": re.findall(r'"([^"]+)"', envs.group(1)) if envs else [],
                    "tuple": m.group(1) if m else "", "models": tb[2] if tb else []})
    return out


def fetch_catalogue(base_url, key, timeout=40):
    req = urllib.request.Request(base_url.rstrip("/") + "/models",
                                 headers={"Authorization": "Bearer " + key, "User-Agent": UA})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        data = json.loads(resp.read())
    if data.get("has_more"):
        print("! /models 返回 has_more=true，分页没取全，差集不可信", file=sys.stderr)
    return [m.get("id") for m in data.get("data", []) if m.get("id")]


def probe_one(base_url, key, model, timeout=30):
    body = json.dumps({"model": model, "messages": [{"role": "user", "content": "hi"}],
                       "max_tokens": 1}).encode()
    req = urllib.request.Request(base_url.rstrip("/") + "/chat/completions", data=body,
                                 headers={"Authorization": "Bearer " + key,
                                          "Content-Type": "application/json",
                                          "User-Agent": UA})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            json.loads(resp.read())
        return "alive", ""
    except urllib.error.HTTPError as exc:
        txt = exc.read().decode("utf-8", "ignore")
        if "does not exist" in txt or "model_not_found" in txt or "Model not exist" in txt:
            return "dead", txt[:160]
        return "other", "HTTP %s %s" % (exc.code, txt[:160])
    except Exception as exc:  # noqa: BLE001
        return "other", str(exc)[:160]


def short(items):
    shown = ", ".join(items[:LIST_CAP])
    if len(items) > LIST_CAP:
        shown += " …（还有 %d 条）" % (len(items) - LIST_CAP)
    return shown


def rewrite_tuple(src, name, models):
    """按原格式重写元组（4 空格缩进、每行一条、结尾 `)`）。

    注意：src 是 **LF 归一化**后的文本，这里也一律用 `\\n`，最后统一转回原行尾——
    混用会让写回变成 `\\r\\r\\n`。尾部从 `j + 2`（跳过 `\\n)`）续上，多跳一位会吞掉紧随其后的字符。
    """
    i, j, _old = tuple_block(src, name)
    body = "%s = (\n%s)" % (name, "".join('    "%s",\n' % (m,) for m in models))
    return src[:i] + body + src[j + 2:]


def main():
    ap = argparse.ArgumentParser(description="校准插件静态模型清单")
    ap.add_argument("--file", default=os.path.join(REPO, "__init__.py"), help="插件 __init__.py")
    ap.add_argument("--key-env", default="DASHSCOPE_API_KEY")
    ap.add_argument("--env-file", default=os.path.join(REPO, ".env"))
    ap.add_argument("--no-probe", action="store_true", help="只做目录 diff，不发探测请求")
    ap.add_argument("--sleep", type=float, default=0.25, help="探测间隔秒数")
    ap.add_argument("--max-probe", type=int, default=120, help="探测上限")
    ap.add_argument("--apply", action="store_true", help="把确认下线的条目从清单删掉")
    ap.add_argument("--add", default="", help="要加入的模型名，逗号分隔")
    ap.add_argument("--to", default="", help="配合 --add：目标元组名，如 OTHERS_MODELS")
    ap.add_argument("--json", dest="json_out", default="", help="把结果写到 JSON")
    args = ap.parse_args()

    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:  # noqa: BLE001
        pass

    raw = open(args.file, "rb").read()
    eol = "\r\n" if b"\r\n" in raw else "\n"
    src = raw.decode("utf-8").replace("\r\n", "\n")

    providers = parse_providers(src)
    if not providers:
        sys.exit("在 %s 里找不到带 fallback_models 的 provider" % args.file)
    print("校准 %s（%s 行尾）" % (args.file, "CRLF" if eol == "\r\n" else "LF"))

    key = ""
    for pv in providers:
        for env_name in pv["env_vars"] + [args.key_env]:
            key = key or env_key(env_name, args.env_file)
    if not key:
        sys.exit("拿不到 key：设 %s，或写进 %s / $HERMES_HOME/.env" % (args.key_env, args.env_file))

    base_url = providers[0]["base_url"]
    catalogue = set(fetch_catalogue(base_url, key))
    union = [m for pv in providers for m in pv["models"]]
    print("端点 %s\n声明 %d（%s）/ 目录 %d\n"
          % (base_url, len(union),
             " + ".join("%s(%s) %d" % (pv["name"], pv["tuple"], len(pv["models"])) for pv in providers),
             len(catalogue)))

    budget = [args.max_probe]

    def probe(m):
        if args.no_probe:
            return "alive", ""
        if budget[0] <= 0:
            return "other", "探测预算用尽"
        v, d = probe_one(base_url, key, m)
        budget[0] -= 1
        time.sleep(args.sleep)
        return v, d

    dead, other, alive, unprobed = [], {}, [], []
    for pv in providers:
        for m in pv["models"]:
            if m in catalogue:
                continue
            if args.no_probe:
                unprobed.append(m)
                continue
            v, d = probe(m)
            if v == "dead":
                dead.append(m)
            elif v == "alive":
                alive.append(m)
            else:
                other[m] = d

    print("【清单里不在目录的条目】")
    if not any(m not in catalogue for m in union):
        print("  无：清单里的模型都还在目录中")
    if unprobed:
        print("  · 未探测（--no-probe，调没调通未知，别据此删）：%s" % short(unprobed))
    for m in alive:
        print("  = %s  不在目录里但调用正常 → 保留" % m)
    for m in dead:
        print("  x %s  已下线 → 建议移除" % m)
    for m, d in other.items():
        print("  ? %s  %s" % (m, d))

    extra = [m for m in sorted(catalogue) if m not in set(union)]
    cand = [m for m in extra if is_chat(m) and not is_noise(m)]
    noise = [m for m in extra if is_chat(m) and is_noise(m)]
    nonchat = [m for m in extra if not is_chat(m)]
    joinable, cdead, cother = [], [], {}
    for m in cand:
        v, d = probe(m)
        if v == "alive":
            joinable.append(m)
        elif v == "dead":
            cdead.append(m)
        else:
            cother[m] = d

    print("\n【目录里有、清单里没有的条目】")
    if not extra:
        print("  无")
    if joinable:
        print("  + 可加入（需人工判断归哪一行）：%s" % short(joinable))
    if cdead:
        print("  x 目录里有但调不通，别加：%s" % short(cdead))
    for m, d in list(cother.items())[:5]:
        print("  ? %s  %s" % (m, d))
    if noise:
        print("  · 内部测试项，默认不加：%s" % short(noise))
    if nonchat:
        print("  · 非聊天（image/tts/asr/realtime…），不进聊天行：%d 条 %s"
              % (len(nonchat), short(nonchat)))

    changed = False
    if args.add:
        names = [n.strip() for n in args.add.split(",") if n.strip()]
        target = args.to or providers[0]["tuple"]
        tb = tuple_block(src, target)
        if not tb:
            sys.exit("找不到元组 %s" % target)
        src = rewrite_tuple(src, target, names + [m for m in tb[2] if m not in names])
        print("\n--add：%s 前插入 %s" % (target, ", ".join(names)))
        changed = True
    if args.apply:
        if not dead:
            print("\n--apply：没有确认下线的条目，清单未改")
        else:
            for name in {pv["tuple"] for pv in providers}:
                tb = tuple_block(src, name)
                if not tb:
                    continue
                kept = [m for m in tb[2] if m not in dead]
                if len(kept) != len(tb[2]):
                    src = rewrite_tuple(src, name, kept)
            print("\n--apply：从清单移除 %d 条已下线条目" % len(dead))
            changed = True

    if changed:
        open(args.file, "wb").write(src.replace("\n", eol).encode("utf-8"))
        counts = {pv["tuple"]: len(tuple_block(src, pv["tuple"])[2]) for pv in providers}
        print("已写 %s；现在计数 %s" % (args.file, counts))
        print("下一步：git diff 过一眼 → 更新 README 计数与 plugin.yaml 的 version → commit")

    if args.json_out:
        json.dump({"dead": dead, "alive": alive, "other": other, "joinable": joinable,
                   "new_dead": cdead, "new_other": cother, "new_nonchat": nonchat, "new_noise": noise},
                  open(args.json_out, "w", encoding="utf-8"), ensure_ascii=False, indent=1)

    todo = bool(dead or joinable)
    print("\n%s" % ("需要动作：有 %d 条下线 / %d 条可加入" % (len(dead), len(joinable)) if todo
                    else "清单与 live 目录一致，无需动作"))
    return 1 if (todo and not changed) else 0


if __name__ == "__main__":
    sys.exit(main())
