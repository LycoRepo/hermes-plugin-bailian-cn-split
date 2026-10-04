# hermes-plugin-bailian-cn-split

把阿里云百炼（中国站 / DashScope 兼容端点）在 Hermes 的模型选择器里**拆成两行**显示：

| provider | 显示名 | 内容 |
|---|---|---|
| `alibaba-cn` | **Qwen** | 阿里自家品牌（qwen / qwq / qvq / tongyi），173 个 |
| `bailian-others` | **Bailian Third-party** | 百炼上的第三方模型（kimi / glm / deepseek / minimax ...），67 个 |

两者共用同一个端点和同一个 key。拆开是因为百炼兼容端点上有 240 多个模型，全挤在一行里很难挑；
拆完之后 Qwen 那一行只有自家品牌，第三方模型单独一行。

## 安装

```bash
hermes plugins install LycoRepo/hermes-plugin-bailian-cn-split
```

或者手动：把本仓库的 `plugin.yaml` + `__init__.py` 放进
`$HERMES_HOME/plugins/hermes-plugin-bailian-cn-split/`（平铺在 `plugins/` 下，
**不要**放进 `plugins/model-providers/`——放那里 Hermes 一样会加载，但 Hermes 桌面端的插件页不会列出它）。

## 需要什么

- `DASHSCOPE_API_KEY` —— 阿里云百炼 / DashScope 的 key（必填）
- `DASHSCOPE_CN_BASE_URL` —— 可选，覆盖默认端点

## 说明

- 这是 `kind: model-provider` 插件：只要目录放在 `$HERMES_HOME/plugins/` 下就会被
  providers 发现并加载，`plugins.enabled` / `plugins.disabled` 对它的加载没有实际作用。
- 模型清单是**静态生成**的（`supports_model_listing=False`），所以不会每次去拉全量目录。
  要更新清单或改显示名，直接改 `__init__.py` 里的 `QWEN_MODELS` / `OTHERS_MODELS` / `display_name`。

## 许可

MIT
