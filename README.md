# hermes-plugin-bailian-cn-split

把阿里云百炼（中国站 / DashScope 兼容端点）在 Hermes 的模型选择器里**拆成两行**显示：

| provider | 显示名 | 内容 |
|---|---|---|
| `alibaba-cn` | **Qwen** | 阿里自家品牌（qwen / qwq / qvq / tongyi），108 个 |
| `bailian-others` | **Bailian Third-party** | 百炼上的第三方模型（kimi / glm / deepseek / minimax ...），54 个 |

两者共用同一个端点和同一个 key。拆开是因为百炼兼容端点上可选的模型很多，全挤在一行里很难挑；
拆完之后 Qwen 那一行只有自家品牌，第三方模型单独一行。

## 安装

```bash
hermes plugins install LycoRepo/hermes-plugin-bailian-cn-split
```

或者手动：把本仓库的 `plugin.yaml` + `__init__.py` 放进
`$HERMES_HOME/plugins/bailian-cn-split/`（平铺在 `plugins/` 下，
**不要**放进 `plugins/model-providers/`——放那里 Hermes 一样会加载，但 Hermes 桌面端的插件页不会列出它）。

## 需要什么

- `DASHSCOPE_API_KEY` —— 阿里云百炼 / DashScope 的 key（必填）
- `DASHSCOPE_CN_BASE_URL` —— 可选，覆盖默认端点

## 说明

- 这是 `kind: model-provider` 插件：只要目录放在 `$HERMES_HOME/plugins/` 下就会被
  providers 发现并加载，`plugins.enabled` / `plugins.disabled` 对它的加载没有实际作用。
- 清单最近一次校准：**2026-10-11**——按百炼 `/models` 目录（175 条）+ 逐个探测校准，
  移除了 78 个已下线或不适用于 chat 的条目（其中 22 个是 TTS/ASR/realtime 语音模型），
  现为 Qwen 108 + Third-party 54 = 162 条。
- 模型清单是**静态生成**的（`supports_model_listing=False`），所以不会每次去拉全量目录。
  要更新清单或改显示名，改 `__init__.py` 里的 `QWEN_MODELS` / `OTHERS_MODELS` / `display_name`，
  或者用下面那条命令重算。

## 更新模型清单

```bash
export DASHSCOPE_API_KEY=sk-...        # 或写进本目录的 .env（已在 .gitignore 里）
python tools/calibrate.py              # 只读体检：清单里哪些已下线、目录里哪些是新的
python tools/calibrate.py --apply      # 把确认下线的条目删掉（改 __init__.py）
python tools/calibrate.py --add glm-5.4 --to OTHERS_MODELS   # 手工加入新模型
```

判据（别简化，都是踩过的坑）：

- **不在目录里 ≠ 调不通**：百炼的 `/models` 不是可用性清单——`qwen-turbo` 就不在目录里、调用却正常。
  脚本对「清单 − 目录」的每一条都发一次最小 chat 请求，只有明确 `does not exist` 才算下线；
  403（未开通）/ 429（限流）/缺参数一律归「待人工」，**不会自动删**。
- **目录里有、但调不通的也不能加**（`qwen1.5-7b-chat` 这类就是）。
- 图像 / 语音 / 嵌入等非聊天模型（image、wan、tts、asr、realtime、embedding…）在 chat 端点必然报错，
  但这不是「下线」；`sre-` / `test-` 这类内部测试项同理——两者都不进聊天行。
- 两行共用同一端点，差集要**按端点整体算**：分别按行算的话，Qwen 行会把第三方模型全当新增。

改完记得同步 README 的计数和 `plugin.yaml` 的 `version`，再 commit（`--apply` 只改清单，不碰版本号、不提交）。

## 许可

MIT
