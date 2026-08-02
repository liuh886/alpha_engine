# Static PWA Deployment

Alpha Engine 的唯一 Web 发布路径是 GitHub Pages 上的 Research Artifact Studio。浏览器产品由静态文件和版本化研究成果包组成，不运行 Python 服务。

## Build contract

```bash
make research-bundle
make static-pwa
```

发布内容必须包含：

```text
qlib-dashboard/dist/
  index.html
  manifest.webmanifest
  service worker assets

artifacts/research-bundle/
  alpha-engine-bundle.json
  manifest-declared evidence files
```

GitHub Actions 的 Pages 工作流负责：

1. 安装锁定的 Python 与 Node 依赖；
2. 导出公开研究成果包；
3. 运行 TypeScript、Lint、单元测试和静态构建；
4. 校验 PWA manifest、service worker 和 bundle budget；
5. 运行桌面、平板和移动端 Chromium 验收；
6. 发布 Pages artifact。

## Runtime properties

- 浏览器不连接 Python 进程；
- 不需要用户账号、服务端会话或网络端点；
- 本地成果包不上传；
- 首次成功访问后应用壳可离线加载；
- 公开成果的真实性由 manifest、路径、字节数和 SHA-256 约束。

## Rollback

静态发布的回滚单位是 Git 提交或 Pages artifact：

1. 确认上一已知良好提交；
2. revert 引入问题的提交；
3. 重新运行 Pages 工作流；
4. 验证 Library、Evidence、Reference、离线重载和零网络请求。

不要通过恢复旧服务器来回滚前端。研究执行仍由 Python CLI、脚本或 GitHub Actions 完成。

## Acceptance

发布前必须通过：

```bash
make ci
cd qlib-dashboard
npx playwright test --config=playwright.static.config.ts
```

验收重点：

- 无登录墙；
- 无浏览器数据接口请求；
- 公开和本地成果均可打开；
- 不兼容成果明确失败；
- 三种视口无横向溢出；
- 离线重载成功；
- 旧运维路由不可达。
