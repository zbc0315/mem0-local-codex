# Mem0 Local for Codex

An independent fork of the Mem0 Codex plugin for the self-hosted Mem0 OSS REST API.

当前版本为 [v0.3.3-local.1 预览版](https://github.com/zbc0315/mem0-local-codex/releases/tag/v0.3.3-local.1)。

Codex 插件与自托管 Mem0 Docker REST 服务直接通信。插件随 Codex 提供
自动捕获、自动回忆、搜索工具、子代理会话记录和六个记忆操作技能。
运行需要 Mem0 Docker 服务，以及 Codex 进程的 `PATH` 中可用的 Python 3.10 或更新版本。
搜索工具由 Codex 随插件启动。

本项目基于 [Mem0 Codex 插件 0.3.3 的上游提交](https://github.com/mem0ai/mem0/commit/a330119bda245ad05bf1d5e6779fc588b5f19443)，
修改了后台协议、凭据来源和遥测行为。详见 [Apache-2.0 许可证](LICENSE)和[上游归属与修改说明](NOTICE)。

## 配置

1. 按 [Mem0 自托管指南](https://docs.mem0.ai/open-source/setup) 启动
   支持 `POST /memories`、`POST /search` 和 `GET /memories` 的 Docker 版，
   完成管理员初始化，并在管理面板创建独立的 API Key。服务器仍需要
   配置提取模型和向量模型。模型请求是否离开你的机器取决于 Docker
   服务的供应商配置。
2. 在当前 Codex 所在的机器创建 `~/.config/mem0-codex/config.json`，
   权限设为 `600`。填写 REST 根地址和 Docker 实例签发的 API Key。
   如果服务跨机器访问，使用你信任的 HTTPS 地址或 SSH 转发。

   ```json
   {
     "url": "http://127.0.0.1:8888",
     "api_key": "m0sk_REPLACE_FROM_YOUR_LOCAL_DASHBOARD"
   }
   ```

   可通过 `MEM0_LOCAL_URL`、`MEM0_LOCAL_API_KEY` 和
   `MEM0_LOCAL_CONFIG` 覆盖。插件拒绝 Mem0 云域名和 HTTP 重定向，
   API Key 只送给配置的 REST 服务。插件没有联网遥测。
3. 从桌面端使用的同一 Codex 安装插件，然后重新加载 Codex。插件的
   MCP 服务名为 `mem0-local`，提供 `search_memories` 工具。按 Codex 提示检查并信任其钩子。

   ```sh
   codex plugin marketplace add zbc0315/mem0-local-codex --ref v0.3.3-local.1
   codex plugin add mem0-local@self-hosted-memory
   ```

4. 在测试目录操作，先用 `mem0-local:status` 检查 API，再说一句可复用、
   无敏感信息的测试偏好。等待本轮后台捕获完成，然后使用
   `mem0-local:search` 或重开同目录聊天验证回忆。

## 自托管语义

- 保留官方插件的本地 SQLite 证据缓存和后台 flush worker。Docker 的
  `POST /memories` 同步完成提取，插件收到成功响应后记录批次进度。
  如果服务已经写入但响应丢失，重试仍可能重复提取。服务端按其自身
  规则对记忆去重。
- 记忆保留项目、目录、用户和会话筛选。类别由 Docker 版的提取模型
  生成文本标签。模型遗漏标签的记录仍能正常搜索，按类别筛选时可能
  看不到。Docker REST 的有范围列表最多返回 1,000 条。达到上限时，
  清理命令中止，避免误报已完整删除。
- 插件沿用上游脱敏逻辑，并补充本机 API Key 和 TOTP 字段的识别。
  对禁止捕获的会话可用 `mem0-local:pause`。恢复用
  `mem0-local:resume`，已存在的记忆仍可检索。
- 此插件不迁移原来的 Qdrant 数据。旧 mem0 MCP、Claude Code hooks
  以及新 Docker 实例是独立接入。关闭旧服务前，先在新实例验收读写，
  并核对历史记忆是否已迁移。未带插件作用域标签的旧数据不会自动混入
  新插件的按仓库回忆。

## 开发验证

```sh
python3 -m pytest -q plugin/tests
```

测试覆盖 Codex 钩子和插件清单，以及使用本地 HTTP 测试服务验证
Mem0 OSS 的认证、请求结构、同步提交、检索去重和删除范围。

发布前还在 Mem0 OSS 2.2.1 Docker REST 服务和 PostgreSQL/pgvector 上
验证了 API Key 认证、后台双作用域写入、跨会话自动回忆、按类别和会话
搜索、暂停恢复与作用域删除。该隔离测试使用固定输出的模型夹具，验证的
是集成行为。提取质量取决于实际部署所选的模型。
