# 动态快运网络优化网页

这是一个纯静态的 Vite + React + TypeScript 演示站点。页面不调用 Gurobi、强化学习或任何后端接口，只读取 `public/data` 中预处理后的 JSON。

## 本地启动

```powershell
cd web
npm install
npm run dev
```

生产构建与本地预览：

```powershell
npm test
npm run build
npm run preview
```

## 更新实验数据

在项目根目录运行：

```powershell
python scripts/build_web_data.py
```

脚本从 `results/gurobi_v6_12/test` 读取12个真实MILP结果，生成首屏汇总、案例明细和逐案例动画分片。它会校验：

- 12个正式案例均完成并通过独立验证；
- 首屏静态数据不超过500KB；
- 单个动画JSON不超过5MB；
- Benders＋列生成和分层Q学习仅生成带 `dataStatus: mock` 的固定种子接口占位数据。

不要把221MB原始结果直接复制到 `public`。网页通过 `animationManifest` 按案例懒加载动画。

## 数据状态规则

- `real`：可进入真实结论和验证摘要。
- `mock`：仅验证图表/动画组件，必须显示模拟水印，不能用于排名或统计结论。
- `planned`：技术路线完成，但尚无实验数据。

接入新方法真实结果时，保持统一字段协议，先通过独立验证，再把该方法的 `dataStatus` 改为 `real`。页面会据此移除对应水印。

## GitHub Pages

仓库已包含 `.github/workflows/deploy-pages.yml`。推送到GitHub后，在仓库 Settings → Pages 中将 Source 设为 **GitHub Actions**。工作流会自动安装依赖、运行测试、构建并发布 `web/dist`。Vite使用相对资源路径，因此仓库项目页子路径和锚点刷新均不依赖服务端路由。
