# 修复：元素库（`xbot_selectors/`）不随迁移走

> 本 fork 的**核心修复**。上游 `tom613951/XbotDeployer` 在迁移后，收件方拿到的应用
> **没有元素库**（`xbot_selectors/` 为空或不存在），打开后所有元素引用失效。
> 本文说明根因、改动与**实测验证结果**。

## 1. 现象

用上游版本迁移后，收件方账号里的应用：

| 检查项 | 上游版本结果 |
|---|---|
| `xbot_robot/`（流程） | ✅ 正常（`.pybx` 齐全） |
| `xbot_selectors/element_*`（元素实体） | ❌ **一个都没有** |
| `package.json.selectordependencies`（元素声明） | ❌ 被清空/为空 |
| 云端应用注册里的 `elementLibraryCodes` | ❌ 写死 `[]` |

→ 打开应用一切正常，但**跑起来所有元素都找不到**。

## 2. 根因（源码级，两处）

| # | 位置 | 上游行为 | 后果 |
|---|---|---|---|
| 1 | `core/packager.py::build_app_package(robot_dir)` | `shutil.copytree(robot_dir)` —— `robot_dir` 是应用的 **`xbot_robot/`**，只复制它 | 兄弟目录 **`xbot_selectors/` 从不进入 `package.bot`** |
| 2 | `core/deployer.py::create_develop_app()` | 注册 payload 写死 `"elementLibraryCodes": []`、`"elementLibraryStatus": 0` | 云端认为该应用**没有元素库**，收件端不会去取 |

## 3. 修复（本 fork）

**① `core/packager.py`：把元素库打进 `package.bot`**

- 新增 `INCLUDE_ELEMENTS`（默认开）：把 `<应用目录>/xbot_selectors/` 整体写入 `package.bot`，
  路径为 **包根下的 `xbot_selectors/…`**（与流程文件同级）。
- 新增 `_collect_element_codes()`：元素 code 集合 = **磁盘上 `element_*` 目录 ∪ `package.json.selectordependencies`**，
  并回填 `package.json.selectordependencies`（避免"声明与实体不一致"）。
- `ELEMENTS_LAYOUT=wrap` 时改为包根放 `xbot_robot/` + `xbot_selectors/`（实验用，**未验证**）。

**② `core/deployer.py`：注册时带上元素库信息**

- `"elementLibraryCodes"`：由 `[]` 改为 `sorted(set(pkg_data["selectordependencies"]))`；
- `"elementLibraryStatus"`：由写死 `0` 改为可配置，默认 `1`。

**③ 开关（环境变量，便于回退/A-B）**

| 变量 | 默认 | 说明 |
|---|---|---|
| `XBOT_INCLUDE_ELEMENTS` | `1` | 设 `0` 完全恢复上游行为（不带元素） |
| `XBOT_ELEMENTS_LAYOUT` | `root` | `root`=包根放 `xbot_selectors/`（已实测有效）；`wrap`=包根放 `xbot_robot/`+`xbot_selectors/`（未验证） |
| `XBOT_ELEMENT_STATUS` | `1` | 注册时 `elementLibraryStatus` 取值（`0`=上游行为） |

## 4. 实测验证（2026-09-21，影刀 6.3.22）

**环境**：源应用在 A 账号（App 49 个 `.pybx`、10 组元素、222 个元素文件）；
目标为 B 账号（社区免费版）。用本 fork 的 `deploy_single_app` 上传。

**上传端日志**

```
[elements] 元素组 10 个：element_03840be7, element_1348fdf3, element_16adc168, element_2a715c55,
                         element_41626a95, element_b5c9f6bd, element_bb81fb2a, element_ce2dcd30,
                         element_dab44cb0, element_efd5239d
[elements] 已写入 xbot_selectors/：222 个文件（layout=root）
✅ 打包完成 | 包大小: 8809501 字节
✅ 资源上传完成，正在接收方账号注册创建应用...
🔍 接收方云端应用列表校验通过：应用已成功注册就绪！
```

**收件方客户端日志**（自动完成，无需手工补元素）

```
[DevelopmentPackageFactory] RefreshLocalData, uuid: c7dfbf5f-…
Download file from: https://winrobot-pri-a.oss-accelerate.aliyuncs.com/robots/robot-c7dfbf5f-…/v-1/package.bot?Expires=…
Start open studio, document.uuid: c7dfbf5f-… name: …(带元素试验)
start do [OpenStudio] check-sigstore
Watch: [OpenStudio] check-sigstore cast : 65 ms        ← 通过，无异常
End open studio
AsyncPythonTaskCenter … requirements: requests==2.31.0, pillow-heif==0.12.0, …
```

**落地结果对照**

| 项目 | 源应用 | 收件方（本 fork 迁移后） |
|---|---|---|
| 流程 `.pybx` | 49 | **49** ✅ |
| 元素组 | 10 | **10** ✅ |
| `xbot_selectors` 文件数 | 222 | **222** ✅ |
| `package.json.selectordependencies` | 10 | **10** ✅ |
| 市场扩展 `xbot_extensions` | 11 目录 | **1986 个文件**（客户端自动下发）✅ |
| Python 依赖 | — | **客户端自动 pip 安装** ✅ |
| 打开应用 | — | **无 sigstore / 无权限错误** ✅ |

**结论**：所谓"云端带不了元素"不成立 —— 之前丢元素是**本工具没把元素交上去**。
修好上述两处后，**元素库 + 流程 + 扩展 + 依赖全部由官方云链路自动完成**，收件方双击即可用。

## 5. 已知边界 / 未验证

- `elementLibraryStatus = 1` 的**确切语义未验证**（上游写死 0）。若遇到异常，先设
  `XBOT_ELEMENT_STATUS=0` 再试，并把结果反馈到 issue。
- `ELEMENTS_LAYOUT=wrap` **未验证**；本次只验证了默认的 `root`。
- 本工具是**第三方**云上传通道：需要**收件方账号密码**换取 token（与上游行为一致）。
  若双方都是创业版/企业版，更推荐影刀官方的"发版 → 分享给个人"。
- 上游仓库**未声明 LICENSE**：本 fork 仅作 GitHub fork 维护与内部使用，请遵守上游说明。

## 6. 回滚

```bash
# 完全恢复上游行为（不带元素库）
set XBOT_INCLUDE_ELEMENTS=0
python main.py deploy ...
```
