# WT UserSkin ZIP → MDL skin

## GUI

最新独立 EXE：`dist/DagorAssetExplorer/DagorAssetExplorer-autoSplit.exe`（包含自动BLK选择及Glide超限拆分）；旧`autoBLK.exe`不含拆分。也可启动源码版：`python src/dae`。运行 EXE 时保留同目录下的 `res/`、`lib/`、`ui/`。

- **Glide导出**：在导出选项中使用“Import WT skin ZIP...”对应的导入按钮。
- **Source导出**：在“MDL skins”对话框选择ZIP。
- 保留原涂装为 **skin 0**，列表中的ZIP依次成为 **skin 1、2……**；可移除选中项。
- 必须启用SMD和贴图导出，并配置StudioMDL、gameinfo及VTFCmd。皮肤在编译前写入QC的`$texturegroup`，不是运行时随意换材质。

ZIP可包含一份或多机型的UserSkin `.blk`和引用的贴图。多BLK时按当前导出模型名精确匹配BLK文件名（忽略大小写，例如`su_30sm2`→`全年龄/su_30sm2.blk`），GUI显示所选BLK，`skins.json`也记录它。无匹配或多个同名候选时报错，不按SU30系列名称模糊猜测；仅解析选中的BLK，其他机型的规则不干扰导入。当前支持`replace_tex`及DDS/TGA/PNG，复用WT→Source法线通道和透明度转换。`set_tex`、include、歧义匹配、不安全路径和缺失贴图会报错，不会静默忽略。未匹配规则记录在导出目录的`source_export/skins.json`。

## 已安装示例：SU-30SM2 Shadow22

输入：`Su_30sm2_Shadow22.zip`。

- 独立addon：`garrysmod/addons/wt_su_30sm2`，原`addons/su30`未改。
- **skin 0：原涂装；skin 1：Shadow22。** 颜色、法线、挂架贴图规则均匹配；机身与独立喷口模型均编译为2个skin family，喷口组件跟随机身skin。
- GTerm临时新模型路径验证皮肤切换及932个座舱玻璃面保留通过；截图为`garrysmod/data/dae_su30_skin_0.png`和`dae_su30_skin_1.png`。
- 当前游戏会话仍把正式同名模型缓存为1个skin，**需要完全退出并重启GMod，然后重新生成飞机**。使用实体的皮肤菜单切换至skin 1；尚未完成重启后的正式实体复验。
- 不要重新挂载旧`data/dae_su_*_final.gma`，这些临时包不含最新修复。

新版GUI的 **Glide导出** 在保留骨骼超过256时自动拆分机身和`nozzle1_/nozzle2_`喷口，分别编译并同步动画、skin和清理；无需手工删骨骼。保留祖先骨骼和顶点权重；若拆分后仍超限或权重跨越组件边界，明确报错，不静默丢动画。普通Source导出不包含组件运行时，不自动拆分。

这只接入了模型拆分，不代表普通导出包含实验自定义喷焰shader。已暂存模型的专用皮肤导入脚本仍是`import_sukhoi_skin.py`，使用`install_sukhoi.py`可恢复苏霍伊实验实体/喷焰；不要认为普通重导出会保留实验shader补丁。

## 本次音效修复

SU-30SM2/SU-33重新导出并安装WT的AL-31F怠速、军推、加力循环。修复安装器遗漏音效参数导致Glide默认声音回退、循环混入一次性加力点火，以及声音patch未启动。GTerm验证真实patch启动、油门交叉淡化、原音高与熄火静音通过；听感仍需用户试飞确认，未宣称完整复刻WT的动态FMOD混音。

## 验证与备份

自动拆分更新后：`python -m unittest discover -s tests`：67项通过。包含GUI双编译目标、实体组件引用、skin family、动画及带权重顶点重映射检查。

本次备份在`%TEMP%/wtp/backups/`：
- `su30_skin_20261106_144359`
- `wt_su_30sm2_20261106_145103_941745`
- `wt_su_33_20261106_145124_648750`

其中后两份是最终实体安装前的状态，不等同于导入Shadow22前的原始模型。完整原生材质响应、玻璃干涉色、多人和飞行性能尚未验收。
