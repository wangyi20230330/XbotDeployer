# 关于本 fork（FORK-NOTES）

- **上游**：<https://github.com/tom613951/XbotDeployer>（作者 tom613951）
- **本 fork**：<https://github.com/wangyi20230330/XbotDeployer>
- **改动**：只做**元素库随迁移走**的修复（见 [docs/ELEMENTS-FIX.md](docs/ELEMENTS-FIX.md)），
  不改上游其它行为；默认开启，可用 `XBOT_INCLUDE_ELEMENTS=0` 一键回退。
- **为什么 fork 而不是只提 PR**：本机业务依赖这条迁移链路，需要可控版本；
  同时也**欢迎把该修复合并回上游**（改动只有 2 个文件 + 环境变量开关）。
- **许可证**：上游**未声明 LICENSE**。按 GitHub 规则，fork 是允许的；本 fork 保留上游署名，
  不对上游代码作额外授权声明。若你打算对外分发/商用，请先取得上游作者许可。
- **同步上游**：

```bash
git remote add upstream https://github.com/tom613951/XbotDeployer.git   # 若还没有
git fetch upstream && git switch main && git merge upstream/main
```
