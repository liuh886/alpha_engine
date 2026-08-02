# Security Review: Research Artifact Studio

**Date:** 2026-08-02  
**Scope:** Static PWA, local research bundles and Python research workflows

## 1. Product boundary

Research Artifact Studio 是静态只读浏览器产品：

- 不运行应用服务器；
- 不维护用户会话；
- 不提供浏览器任务执行或写入能力；
- 不连接券商；
- 不上传本地成果包；
- 不把研究结果标记为可交易信号。

因此，旧架构中的服务认证、跨域策略、远程任务停止和运行时端口不再构成产品安全边界。

## 2. 成果完整性

每个成果包由 `alpha-engine-bundle.json` 约束：

- schema version；
- 规范化相对路径；
- 文件字节数；
- SHA-256；
- research scope；
- warnings 和 blocked gates；
- 数据、模型、股票池、基准和时间窗口 identity。

目录穿越、摘要不匹配、不支持的版本或缺失必需文件均 fail closed。

## 3. 本地文件隐私

本地目录、文件集合或 ZIP 通过浏览器文件能力读取：

- 不上传到 GitHub 或外部服务；
- 目录 handle 仅在浏览器允许时保存在 IndexedDB；
- 权限失效时必须由用户重新授权；
- 浏览器缓存可由用户清理。

公开 Pages 成果与本地成果在 UI 中明确区分。

## 4. 浏览器攻击面

主要风险与控制：

| Risk | Control |
| --- | --- |
| 恶意 manifest 路径 | 拒绝绝对路径、父目录跳转和根目录逃逸 |
| 被篡改成果 | 校验大小和 SHA-256 |
| 超大文件或压缩包 | 文件数量和大小预算；拒绝不支持的 ZIP 格式 |
| 不可信富文本 | 报告按受控方式呈现，不执行成果中的脚本 |
| 网络数据静默替换 | 生产前端没有数据接口调用 |
| 离线内容陈旧 | 显示成果发布日期、数据截止和 identity |

## 5. Python 研究环境

Python 研究流程仍可能使用数据源密钥或外部集成：

- 密钥只通过环境变量或 GitHub Secrets 提供；
- `.env` 不提交；
- SEC 数据源使用真实、可联系的 `SEC_USER_AGENT`；
- 输出中不写入明文密钥；
- 计划任务以最小权限运行；
- 研究失败不得通过跳过质量门禁解决。

独立 MCP JSON-RPC 工具可使用 `ALPHA_DEVELOPER_TOKEN`，但不得成为前端运行依赖或重新引入浏览器执行能力。

## 6. Supply chain

- Python 依赖由 `uv.lock` 锁定；
- Node 依赖由 `package-lock.json` 锁定；
- CI 使用冻结安装；
- 直接 Web 服务器依赖已从项目依赖移除；
- MCP 所需的传递依赖按独立协议边界审查；
- Pages 构建、PWA 产物、bundle budget 和 Chromium 验收进入发布门禁。

## 7. Residual limitations

- ZIP64、加密 ZIP 和不支持的压缩方法会被拒绝；
- 浏览器无法证明研究方法本身正确，只能验证已声明成果完整性；
- 公开静态成果任何人可访问，不应包含秘密或受限数据；
- 本系统仍为研究用途，不能替代交易风控、合规审批或人工判断。

## Verdict

静态成果阅读架构显著缩小了远程攻击面。发布安全的核心从“保护运行服务器”转为“限制公开内容、验证成果完整性、锁定供应链并保持浏览器永久只读”。
