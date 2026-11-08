# 飞机挂载武器点调研：SU-30SM2 / SU-33

日期：2026-11-06。范围：本机已安装 WT 数据与当前导出器；不是所有 WT 飞机的通用格式保证。

**结论：原始资源足以恢复挂点、可选武器和挂架可见性；当前导出器没有完成外挂武器支持。** 两机均有12个外部槽位，加内置武器槽0。不能把槽编号直接当成 pylon 编号，也不能只导出导弹模型后按位置平移。

> SU 实机测试尚未最终验收：GTerm 在最终材质刷新后失去执行能力，SU-30SM2喷口还有过曝失败项。本文先完成离线调研；实测状态单独见 `SUKHOI_STATUS.md`，不将报告交付等同于测试完成。

## 1. 证据与方法

- `War Thunder/aces.vromfs.bin`：`gamedata/flightmodels/su_30sm2.blk`、`su_33.blk`，其 `weapon_presets.preset[].blk` 指向完整挂载方案。
- `content/base/res/aircrafts/air.grp`：两机 DynModel 与 GeomNodeTree；调用 `computeData()` 后读取节点 `wtm`。
- `gamedata/weapons/rocketguns/su_r_73.blk`：发射器/武器定义示例；其他武器路径由槽内 `Weapon.blk` 取得，不猜文件名。
- 解析入口：`src/dae/util/vromfs.py:VROMFS.readBlk`；`src/dae/util/glide.py:findAircraftBlk`、`gamePos`、`builtinPreset`、`aircraftWeapons`、`aircraftHiddenNodes`、`aircraftKeepBones`。
- 离线核对脚本与结果：`%TEMP%/wtp/hardpoints_probe.py`、`hardpoints_probe.log`。遍历全部外部槽位，检查 emitter 存在、读取每个武器文件、验证每份整机 preset 的 slot/preset 引用；断言通过。临时文件可能被系统清理，关键结果保存在本文。

| 核对项目 | SU-30SM2 | SU-33 |
|---|---:|---:|
| 槽位总数（含0） | 13 | 13 |
| 整机预设文件数 | 34 | 14 |
| 外挂配置引用的不同 emitter | 98 | 68 |
| 在原生骨架找不到的 emitter | 0 | 0 |
| 外挂武器 BLK 路径数 | 44 | 25 |
| 这些 BLK 中不同顶层 mesh 名 | 37 | 16 |
| 无效的整机 slot/preset 引用 | 0 | 0 |

`mesh` 数量不是完整模型资产核验：本次没有将所有武器 mesh 定位到 GRP、导出或实机挂载。

## 2. 数据链路：槽位、方案、武器和挂架

```text
飞机 weapon_presets.preset[].blk
  → 整机预设 Weapon[] {slot, preset}
  → 飞机 WeaponSlots.WeaponSlot[index]
  → 该槽位 WeaponPreset[name]
      ├─ ShowNodes：应显示的挂架/导轨组件
      ├─ reqModification / BannedWeaponPreset：解锁及互斥约束
      └─ Weapon（字典或列表）
          ├─ emitter → GeomNodeTree节点及矩阵
          ├─ blk → 武器配置 → mesh / rocket / bomb 等数据
          └─ trigger、bullets、external、separate、order
```

例如 `su_33_r73.blk` 选中槽1、2、3、10、11、12的R-73方案；槽1和12都叫 `r73_default`，因此**preset名称只在槽内唯一**，不能全机按名称建立单一字典。

槽2的 R-73 使用 `pylon_5_r_73`，显示 `pylon_5` 和 `pylon_5_apu_73`。SU-30SM2同槽还可选择R-27ER或R-77：对应 emitter 和挂架不同。R-77配置包含 AKU-170 connector、gear、spring 等多个节点，说明“一个槽配一个固定挂架网格”不足以表达原始数据。

SU-30SM2槽6的某些方案含 `BannedWeaponPreset {slot=7,preset=grom2_slot7}`。互斥必须按实际规则处理，不能只检查弹药重量。`order` 在两机数据中可能位于槽层或 Weapon 层，须保留两层信息，不能假设固定位置。`tier` 不等于空间位置或发射顺序。

武器示例 `su_r_73.blk`：顶层 `mesh=su_r_73`，`rocket.bulletName=su_r_73`、`rocket.mass=105`，带光学导引和发动机参数。`offsetForDemonstration` / `rollForDemonstration` 名称指向展示用途，**没有证据应将其直接应用为实战挂载偏移**。

## 3. 槽位与坐标实测

下表每槽仅展示**第一个方案**的 emitter。坐标是当前导出器 `gamePos` 算得的 Source 模型局部位置，不是游戏世界位置，也不是已实机验收的 attachment。

| 槽 | 示例 emitter | SU-30SM2方案数 | SU-33方案数 | SU-30SM2 (x,y,z) |
|---:|---|---:|---:|---|
| 1 | pylon_7_r_73 | 1 | 1 | (-74.65, 292.48, -12.59) |
| 2 | pylon_5_r_73 | 3 | 1 | (-85.43, 248.16, -21.96) |
| 3 | pylon_3_r_72 | 44 | 28 | (-33.39, 187.76, -21.73) |
| 4 | pylon_11_r_27 | 19 | 1 | (-14.63, 141.86, -26.27) |
| 5 | pylon_9_r_27 | 25 | 10 | (17.14, 49.73, -67.73) |
| 6 | pylon_2_r_27 | 13 | 9 | (-123.82, 0, -29.08) |
| 7 | pylon_1_r_27 | 18 | 9 | (69.82, 0, -28.87) |
| 8 | pylon_10_r_27 | 23 | 10 | (17.14, -49.70, -67.73) |
| 9 | pylon_12_r_27 | 19 | 1 | (-14.63, -142.04, -26.27) |
| 10 | pylon_4_r_72 | 44 | 28 | (-33.39, -187.62, -21.73) |
| 11 | pylon_6_r_73 | 3 | 1 | (-85.43, -248.16, -21.96) |
| 12 | pylon_8_r_73 | 1 | 1 | (-74.65, -292.49, -12.59) |

注意 `r_72` 是实际 emitter 名，不能因方案叫R-73就自动更正字符串。

SU-33与上表不同的代表位置：槽4 `(-5.63,136.74,-23.47)`，槽6 `(-124.33,0,-29.88)`，槽7 `(64.91,0,-29.16)`，槽9 `(-5.63,-136.73,-23.47)`。其他列出示例在两位小数精度下相同；不代表所有挂载配置或动画姿态都相同。

### 位置、方向与动画

当前 `gamePos` 公式：

```text
Source局部位置 = (WT.x, WT.z, WT.y) × 40
```

不要重复施加 QC 的 `$upaxis Y` / `$origin ... -90`：上式是本项目最终运行时位置约定；SMD中间空间还包含镜像。`getReducedSMD` 使用旋转归零的绑定姿态，不能直接把 WT 原始节点欧拉角填进最终骨骼。

方向仍需单独验证。例如 `pylon_7_r_73.wtm` 的3×3部分近似：

```text
[ 0.999391,  0.034899,  0 ]
[-0.034899,  0.999391,  0 ]
[ 0,         0,        -1 ]
```

它含反射，不是可直接转成 Source Angle 的纯旋转矩阵。后续需同时考虑飞机和武器模型的坐标基、镜像、武器自身原点，核对转换后的前向/上向；左右对称挂点都要验证。

对动态挂点，保留原 emitter 到保留祖先的相对矩阵，再跟随祖先动画，或保留必要 emitter/挂架骨骼并导出附件。只存静态 `Vector` 无法保证折翼、挂架展开时仍对齐。SU-33折翼挂点的完整驱动链尚未验证。

## 4. 当前导出器缺口

1. `aircraftWeapons()`只返回槽0的非dummy武器，所以能导出内置GSh-301不代表支持外部导弹。
2. `findAircraftBlk()`仅通过上述函数补充 `weaponBlk`；外挂武器没有自动全部展开。
3. `aircraftHiddenNodes()`依据 `HideNodes` 隐藏非内置方案挂架。已导出的空载模型缺失相应网格时，单改Lua无法恢复，需重新导出网格或单独挂架子模型。
4. `aircraftKeepBones()`的显式保留正则不匹配本次98/68个外挂 emitter。`EMITTER_KEEP=[]`表示没有直接请求保留，**不等于已经证明每个编译模型中完全不存在这些名字**；祖先保留及编译优化须另查。
5. 两机已因喷口骨骼超预算采用机身/喷口拆分；外挂系统不宜再无选择地将所有候选 emitter和挂架运动骨骼塞进主模型。

## 5. 建议的最小实现顺序（未实施）

1. 先做一个明确的原生预设，例如SU-33六枚R-73；用原生slot/preset选择而非猜测左右挂点。
2. 导出该方案需要的挂架网格、导弹模型、完整挂载变换；首先验证静态对齐和动画跟随，不同时开发全部武器行为。
3. 单独验证两侧翼尖、翼下和机腹的方向、坐标、脱离位置；测试折翼/操纵动作不会让武器留在原地。
4. 使用Glide现有武器机制接入服务端发射、弹药消耗及客户端外观同步；具体API本次尚未实查，不把WT导引参数直接等同Glide实现。
5. 然后支持多预设与互斥。原始质量约束：两机总外挂8040，SU-30SM2左右翼各3100、SU-33各3000，最大不平衡1500；不能仅统计发射体质量，挂架/吊舱质量规则还需核实。

最低验收：所有配置引用可解析、没有静默忽略缺失节点、两侧模型不镜像错误、发射从当前挂点出发、消耗弹药后模型正确移除、服务端验证换装与射击、重生/删除无残留子模型。

## 6. 未证明事项

- 所有武器mesh资源包位置、批量导出、完整挂架运动控制器。
- 原生旋转/镜像与Source最终附件方向的一致性。
- 挂载武器的实机定位、发射、制导、网络同步、折翼和多人性能。
- WT专有shader完全还原及Workshop独立分发；这与挂点数据可解析是不同问题。

本轮仅调研与报告，没有新增外挂武器运行时，也没有将上述未完成项标记为已实现。
