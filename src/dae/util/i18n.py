
import sys
from os import path

sys.path.append(path.dirname(path.dirname(path.abspath(__file__))))

from PyQt5.QtCore import QLocale
from PyQt5.QtWidgets import QWidget, QAction, QAbstractButton, QLabel, QLineEdit, QTabWidget, QMenu, QGroupBox
from util.settings import SETTINGS
from util.enums import SETTINGS_LANGUAGE

LANG_AUTO = "auto"
LANG_EN = "en"
LANG_ZH_CN = "zh_CN"

# English source text -> translation. Placeholders use str.format named fields.
_ZH_CN = {
	# Main window
	"Asset tree": "资源树",
	"Search...": "搜索…",
	"Map prop layout exporter": "地图道具布局导出",
	"File": "文件",
	"View": "视图",
	"Toolbar": "工具栏",
	"Open asset folder": "打开资源文件夹",
	"Open assets": "打开资源文件",
	"Open level file": "打开关卡文件",
	"Collapse all": "全部折叠",
	"Expand all": "全部展开",
	"Unmount all assets": "卸载所有资源",
	"Close": "退出",
	"Settings...": "设置…",
	"All supported files": "所有支持的文件",
	"Dagor Binary Level Data": "Dagor 二进制关卡数据",
	"Mounting assets": "正在挂载资源",
	"Loading files...": "正在加载文件…",
	"Expanding items...": "正在展开项目…",
	"Loading {path}": "正在加载 {path}",
	"Loading map...": "正在加载地图…",
	"Loading map data...": "正在加载地图数据…",
	"Loading cell entities...": "正在加载单元格实体…",
	"Writing DPL": "正在写入 DPL",
	"Exporting assets": "正在导出资源",
	"An error occured during the process. Check the console for details.": "处理过程中发生错误，详情请查看控制台。",
	"Ready": "就绪",

	# Progress / message box
	"Progress status": "进度状态",
	"Cancel": "取消",
	"Unfunny!": "出错了！",

	# Tree view
	"Name": "名称",
	"Type": "类型",
	"Size": "大小",
	"Folder": "文件夹",
	"Drag and drop files here or open assets through the \"File\" menu": "将文件拖放到此处，或通过“文件”菜单打开资源",
	"Export LOD...": "导出 LOD…",
	"Failed to compute preliminary data. Check the console for details.": "预计算数据失败，详情请查看控制台。",
	"Open file location": "打开文件所在位置",
	"Open parent location": "打开父级文件所在位置",
	"Copy path to clipboard": "复制路径到剪贴板",
	"Copy name to clipboard": "复制名称到剪贴板",
	"Save to": "保存到",
	"Extract": "提取",
	"Extracting {file}": "正在提取 {file}",
	"Extract all": "全部提取",
	"Extracting files from {file}": "正在从 {file} 提取文件",
	"Export to DDS": "导出为 DDS",
	"Exporting to {file}": "正在导出到 {file}",
	"Export all to DDS": "全部导出为 DDS",
	"Exporting files from {file} to DDS": "正在将 {file} 中的文件导出为 DDS",
	"Preview LOD {lod}": "预览 LOD {lod}",
	"Previewing {file}": "正在预览 {file}",
	"Export LOD {lod} to Source engine": "导出 LOD {lod} 到 Source 引擎",
	"Exporting LOD {lod} to {file}": "正在导出 LOD {lod} 到 {file}",
	"Generating model data": "正在生成模型数据",
	"Exporting model data to QC, SMD and VMT": "正在导出模型数据为 QC、SMD 和 VMT",
	"Compiling": "正在编译",
	"Exporting textures": "正在导出纹理",
	"Converting textures to VTF": "正在将纹理转换为 VTF",
	"Export all LODs to Source engine": "导出所有 LOD 到 Source 引擎",
	"Exporting all LODs from {name} to Source engine": "正在将 {name} 的所有 LOD 导出到 Source 引擎",
	"Export LOD {lod} to {format}": "导出 LOD {lod} 为 {format}",
	"Exporting LOD to {file}": "正在导出 LOD 到 {file}",
	"Export all LODs to {format}": "导出所有 LOD 为 {format}",
	"Exporting all LODs from {name} to {format}": "正在将 {name} 的所有 LOD 导出为 {format}",
	"Exporting {name}": "正在导出 {name}",
	"Export all models to LOD 0 {format}": "将所有模型导出为 LOD 0 {format}",
	"Exporting LOD 0 models from {file} to {format}": "正在将 {file} 中的 LOD 0 模型导出为 {format}",
	"Export skeleton to {file}": "导出骨骼到 {file}",
	"Exporting skeleton to {file}": "正在导出骨骼到 {file}",

	# Settings
	"Dagor Asset Explorer - Settings": "Dagor Asset Explorer - 设置",
	"General": "常规",
	"Create a folder when batch-extracting packed files": "批量提取打包文件时创建文件夹",
	"Create a folder when batch-exporting packed files": "批量导出打包文件时创建文件夹",
	"Convert textures to DXT5": "将纹理转换为 DXT5",
	"Disable \"Save to...\" dialog and save everything to the \"output\" folder": "禁用“保存到…”对话框，全部保存到 “output” 文件夹",
	"Do not export textures when exporting models": "导出模型时不导出纹理",
	"Expand all items by default": "默认展开所有项目",
	"Streamlining": "Source 引擎流程",
	"<b>WIP / DEMO</b> - Streamline model production to the Source Engine": "<b>开发中 / 演示</b> - 简化导出到 Source 引擎的模型制作流程",
	"Features basic VMT, VTF, QC and SMD generation + skeleton support (max 128 bones)": "支持基础的 VMT、VTF、QC、SMD 生成以及骨骼（最多 128 根骨骼）",
	"Browse...": "浏览…",
	"Export SMDs": "导出 SMD",
	"Export collision models": "导出碰撞模型",
	"Do not compile to .mdl": "不编译为 .mdl",
	"Export to the game's \"models\" and \"materials\" folders": "导出到游戏的 “models” 和 “materials” 文件夹",
	"Do not export existing textures": "不导出已存在的纹理",
	"Blender DMF / DPL importer": "Blender DMF / DPL 导入插件",
	"Select StudioMDL binary": "选择 StudioMDL 可执行文件",
	"Set a valid {tool} file in Settings before exporting. Current path: {path}": "请在设置中选择有效的 {tool} 文件后再导出。当前路径：{path}",
	"Select VTFCmd binary": "选择 VTFCmd 可执行文件",
	"Export to Gmod Glide addon": "导出为 Gmod Glide 插件",
	"Exporting {file} to Gmod Glide": "正在将 {file} 导出到 Gmod Glide",
	"Writing Glide addon": "正在写入 Glide 插件",
	"Select gameinfo.txt": "选择 gameinfo.txt",
	"Appearance": "外观",
	"Language": "语言",
	"Theme": "主题",
	"System default": "跟随系统",
	"Dark": "深色",
	"Light": "浅色",
	"Language changes take effect after restarting the application.": "语言更改将在重启程序后生效。",

	# Map tab
	"Dagor Asset Explorer - Per-cell map prop layout export": "Dagor Asset Explorer - 按单元格导出地图道具布局",
	"Path to map file": "地图文件路径",
	"Map info...": "地图信息…",
	"Enlisted map": "Enlisted 地图",
	"Export vegetation": "导出植被",
	"Export non-vegetation": "导出非植被",
	"Export loaded assets": "导出已加载的资源",
	"Export to DPL...": "导出为 DPL…",
	"{models} unique models\n{props} props\n{veg} vegetation": "{models} 个独立模型\n{props} 个道具\n{veg} 个植被",
	"Total cell count: {count}": "单元格总数：{count}",
	"Exportable cells count: {count}": "可导出单元格数：{count}",
	"Cell size: {width}x{height}": "单元格尺寸：{width}x{height}",
	"Total prop count: {count}": "道具总数：{count}",
	"Total vegetation count: {count}": "植被总数：{count}",
}

_TABLES = {
	LANG_ZH_CN: _ZH_CN,
}

def resolveLanguage(lang:str) -> str:
	if lang == LANG_AUTO:
		return LANG_ZH_CN if QLocale.system().name().startswith("zh") else LANG_EN
	
	return lang if lang in _TABLES else LANG_EN

# Language is fixed for the lifetime of the process (changing it requires a restart)
LANGUAGE = resolveLanguage(SETTINGS.getValue(SETTINGS_LANGUAGE))
_TABLE = _TABLES.get(LANGUAGE, {})

def tr(text:str, **kwargs) -> str:
	text = _TABLE.get(text, text)

	return text.format(**kwargs) if kwargs else text

def translateUi(root:QWidget):
	"""Translate the static strings of a widget tree loaded from a .ui file"""

	if not _TABLE:
		return
	
	for w in [root] + root.findChildren(QWidget):
		if w.isWindow() and w.windowTitle():
			w.setWindowTitle(tr(w.windowTitle()))
		
		if isinstance(w, (QAbstractButton, QLabel)) and w.text():
			w.setText(tr(w.text()))
		elif isinstance(w, QLineEdit) and w.placeholderText():
			w.setPlaceholderText(tr(w.placeholderText()))
		elif isinstance(w, QTabWidget):
			for i in range(w.count()):
				w.setTabText(i, tr(w.tabText(i)))
		elif isinstance(w, (QMenu, QGroupBox)):
			w.setTitle(tr(w.title()))
	
	for a in root.findChildren(QAction):
		a.setText(tr(a.text()))
