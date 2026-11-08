# SU-30SM2 / SU-33 实验状态

更新：2026-11-06。**重启后已复查完整贴图、静态喷口对齐及开合；飞行验收仍未完成。**

## 最新：音效与UserSkin（14:53）

两机WT音效已重新导出并通过GTerm真实声音patch检查；SU-30SM2已安装Shadow22，保留默认skin 0，导入为skin 1，机身和喷口同步。临时新模型路径皮肤测试及932面玻璃检查通过；正式同名模型仍缓存单皮肤，需完全重启GMod后重生复验。GUI Source/Glide导出新增ZIP导入选项，独立EXE已于15:18重建至 `dist/DagorAssetExplorer/DagorAssetExplorer.exe`，待用户手动测试。最新Python回归64项通过，详见 [USER_SKINS.md](USER_SKINS.md)。下文为此前测试历史，不代表这些新功能已经完成试飞或人耳听感验收。

## 座舱盖与材质问题（后续修正）

用户指出机身上下材质违和、后部座舱盖缺失，因此此前“贴图可见”不代表外观正确。原生低分辨率 diffuse 也有深灰上表面/浅蓝下表面，但反射、法线和光照一致性尚未验收，未通过改色掩盖。

后部 `blister1` 的932个玻璃面使用 `dynamic_glass_chrome`、opacity=0.17、仅t3=`rainbow_light_coating*`。旧材质命名跳过t3，导致空名、`.vmt` 和空SMD引用。已在 `MaterialData.__generateName__` 修复命名回退，新增回归；58项Python测试通过。需要重编译机身才能修复已导出的模型，仅添加VMT不够。`test_canopy.lua` 检查编译模型中932个玻璃三角面及材质，并生成座舱近景。

已重编译并覆盖独立SU-30SM2机身及staging；备份 `%TEMP%/wtp/backups/su30_canopy_20261106_141358`。GTerm通过临时模型路径 `su_30sm2_canopy_check.mdl` 验证932面/正确VMT并捕获 `data/dae_su30_canopy.png`，近景可见透明罩。当前会话正式路径仍返回旧216312-byte MDL，新磁盘模型为216520 bytes；`r_flushlod` 后仍旧，须重启后重生复验。临时验证模型已删，正式文件保留。玻璃镀膜仍用Source近似，未实现WT干涉色；机身上下材质观感问题仍未结案。

## 重启后复查（13:37–13:44）

- GTerm恢复client/server可达。两机组件动画再次通过（99/195、115/193），完整贴图可见，修正预览后双尾焰从喷口出口向后延伸。
- 修复 `test_sukhoi.lua` 的离屏相机错误：显式传入预览eye/viewAngles，热扰动改用同尺寸scene RT。此前细线和绿色片状伪影不能作为运行时视觉证据。测试定义不再注册覆盖游戏实体。
- SU-30SM2的Source喷口曝光由0.10调为0.065（仅该实验机型）；保持原断言，实测白色261/4234亮像素（6.16%），亮点峰值255、中心约7.09、环约709.93，喷口/热扰动检查通过。SU-33仍为0.10，白色2247/24607（9.13%），检查通过。
- 安装器和SU-30SM2磁盘runtime均已修改；Lua include仍读旧版本，因此直接编译磁盘runtime测试并重注册客户端实体成功。已有实体建议重新生成；新会话仍需确认加载版本。未重建旧 `data/*_final.gma`，那些归档不含本次曝光修改。
- runtime备份：`%TEMP%/wtp/backups/su30_exposure_20261106_134200.lua`。回归57项通过。
- 这轮是离屏组件/渲染验证，未冒充真实飞行、矢量喷口或完整WT视觉还原。下文失败记录和连接阻塞为历史结果。

## 安装与模型

- 独立 addon：`wt_su_30sm2`、`wt_su_33`；未改原 `addons/su30`，本阶段未改 MiG 安装包。
- 外部模型、骨架、ANIM、animtree 来自 `content/base/res/aircrafts/air.grp`，碰撞来自 `aircraft_logic.grp`。
- 原模型超过 Source 256 骨骼限制：SU-30SM2 编译使用293，SU-33使用307。33个姿态采样中，各222个喷口骨骼的世界变形均不同，不能按相同运动无损合并。
- `split_sukhoi.py` 将机身与喷口拆成两个模型，而非删除动画。生成骨骼数：SU-30SM2 **101/195**，SU-33 **115/193**；四个模型均编译成功。实机 SU-30SM2 机身优化为99骨骼。
- `install_sukhoi.py` 安装前备份独立 addon 到 `%TEMP%/wtp/backups/`；兼容编译模型被常规导出移动至 `source_export/models/wt_glide` 的情况。
- 中断导出遗漏的贴图已补齐；最新安装日志 `%TEMP%/wtp/install_sukhoi_final.log` 两机均输出 `INSTALLED`。

## 原生配置与适配

| 参数 | SU-30SM2 | SU-33 |
|---|---|---|
| preset | `_jet_su_30sm_al_31fp` | `_jet_su_33_al_31f3` |
| min/maxHeight（米） | 8 / 12 | 9 / 13 |
| rampTextureOffset | 8（atlas行32–35） | 8（atlas行32–35） |
| min/maxRingCount | 13 / 16 | 13 / 16 |
| nozzle layers | 8 | 8 |
| startOffset（米） | -0.6 | 0.75 |
| nozzle mask indices | 0,1,2,4,4,5,5,5 | 同左 |
| nozzle ramp rows | 23,23,26,26,24,24,6,6 | 同左 |

运行时基于 MiG 重构算法，使用独立 Sukhoi PS、原生纹理和上述配置，不是 WT 原生 shader 的逐行移植。喷焰起点改用实际喷口中心，不再使用机身内部的 jet_flame 卡片 pivot；模型空间 x 约为 -245.05 / -239.82，z 约 -20.83 / -20.70。

## 已完成测试

- 两机客户端机身/喷口组件创建、喷口开合采样通过；已捕获侧、后、斜视图。
- Sukhoi体积 shader 的关闭、整面墙遮挡、部分油门、动画、内外视角检查通过。一次侧视连续性约0.752、动画约0.761。
- SU-33喷口/热扰动测试通过；热扰动改变15674个背景采样，关闭时与基线相同。
- SU-30SM2喷口测试**未通过过曝限制**：937白色像素 / 4494亮像素，约20.85%；内圈暗中心仍存在，但不能据此忽略过曝。
- 最新 Python 全量回归：**57 tests / OK**；`git diff --check` 无错误，仅有原文件 CRLF 提示。

## 最终复查阻塞

2026-11-06 13:20，最终贴图及起点修正已安装，`data/dae_su_30sm2_final.gma` / `dae_su_33_final.gma` 已挂载；随后 GTerm 报 client blocked、server unreachable，组合预览未执行。不要把早期缺贴图、旧起点的截图当成最终验收。

完整 addon 打包被 `sound/.../sources.json` 白名单拒绝；临时视觉 GMA 仅含 lua/materials/models，不含声音及 shaders。声音仍在 addon 目录，shader 已单独部署至游戏 `shaders/fxc`。这些 GMA **不是可独立分发的完整插件**。

## 恢复后检查

1. 本地地图开启 `sv_allowcslua 1`，确认 GTerm client/server 可达。
2. 必要时重新进图以加载新 addon；刷新模型缓存并重新生成两机。
3. 执行 `test_sukhoi.lua`，复查最终贴图、双喷口对齐、机身与喷口组件同步。
4. 修正 SU-30SM2 过曝，重新跑 nozzle/heat/volume 测试，不靠放宽断言掩盖问题。
5. 飞行、矢量喷口、折翼、多人和多机性能仍需测试；内部场景深度截断、热扰动软交界仍不完整。

挂点离线调研见 `AIRCRAFT_HARDPOINTS_REPORT.md`。因实机阻塞提前整理，不代表上述验收已经完成。普通GUI重导出会覆盖实验实体，需重新运行安装器。
