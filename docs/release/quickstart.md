# Alpha Engine Quickstart

Alpha Engine 是 Python 量化研究引擎，Web 产品是静态 GitHub Pages/PWA Research Artifact Studio。

## 1. 直接查看研究成果

打开：

- <https://liuh886.github.io/alpha_engine/>

应用无需登录，可安装为 PWA，并支持：

- 打开公开研究成果；
- 打开本地目录、文件集合或 ZIP；
- 校验 `alpha-engine-bundle.json`、路径、大小和 SHA-256；
- 首次访问后离线加载应用壳。

## 2. 安装 Python 研究环境

```bash
git clone https://github.com/liuh886/alpha_engine.git
cd alpha_engine
uv sync --extra dev
make doctor
```

## 3. 运行研究

```bash
make data
make train-us       # 或 make train-cn
make backtest
```

高级研究任务包括 walk-forward、因子衰减、每日决策和周度报告，统一通过 Makefile、Python 脚本或 GitHub Actions 执行。

## 4. 导出成果包

```bash
make research-bundle
```

然后在 PWA 的 **Library** 中打开：

```text
artifacts/research-bundle/
```

成果包必须以 `alpha-engine-bundle.json` 为根。浏览器不会读取 manifest 外的文件，也不会向仓库或云端上传本地成果。

## 5. 前端开发

```bash
cd qlib-dashboard
npm ci
VITE_RUNTIME_MODE=static_artifact npm run dev
```

前端只支持：

```text
static_artifact
local_artifact
```

不得增加后台任务、网络取数、认证或写操作。

## 6. 完整验证

```bash
make ci
```

静态浏览器验收：

```bash
cd qlib-dashboard
npx playwright test --config=playwright.static.config.ts
```

## 7. 研究边界

- `research_only=true`
- `trade_ready=false`
- 不连接券商或执行订单
- 不在浏览器训练模型
- 不用后端数据替代缺失证据
- 特征重要性不等于因子有效性
