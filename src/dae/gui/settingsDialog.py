
import sys
from os import path

sys.path.append(path.dirname(path.dirname(path.abspath(__file__))))

from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import QDialog, QWidget, QCheckBox, QLineEdit, QPushButton, QFileDialog, QVBoxLayout, QTabWidget, QLabel, QComboBox, QFormLayout, QApplication
from PyQt5.uic import loadUi
from util.misc import getUIPath, openFile
from util.enums import *
from util.settings import SETTINGS
from util.i18n import tr, translateUi, LANG_AUTO, LANG_EN, LANG_ZH_CN, LANGUAGE
from gui.theme import applyTheme


SETTINGSUI_PATH = getUIPath("settings.ui")

class SettingsDialog(QDialog):
	vLayout:QVBoxLayout

	exportFolder:QCheckBox
	expandAll:QCheckBox
	extractFolder:QCheckBox
	noTexExport:QCheckBox
	outputFolder:QCheckBox
	exportSourceCollision:QCheckBox
	exportGameInfo:QCheckBox
	exportSMD:QCheckBox
	noMDL:QCheckBox
	dontExportExistingTextures:QCheckBox
	convertTex:QCheckBox

	studiomdlLine:QLineEdit
	studioMdlBtn:QPushButton
	vtfCmdLine:QLineEdit
	vtfCmdBtn:QPushButton
	gameInfoLine:QLineEdit
	gameInfoBtn:QPushButton

	tabWidget:QTabWidget
	label_2:QLabel
	githubLabel:QLabel
	label:QLabel
	label_3:QLabel

	exportGameInfoLayout:QVBoxLayout
	exportSMDLayout:QVBoxLayout

	
	def __init__(self, parent:QWidget):
		super().__init__(parent)

		loadUi(SETTINGSUI_PATH, self)

		self.label_2.setText("<b>WIP / DEMO</b> - Streamline model production to the Source Engine")
		translateUi(self)

		self.setWindowFlags(self.windowFlags() & ~Qt.WindowContextHelpButtonHint)
		self.vLayout.setContentsMargins(12, 12, 12, 12)
		self.label_2.setProperty("heading", True)
		self.label_3.setProperty("muted", True)
		self.label_3.setWordWrap(True)

		linkColor = self.palette().link().color().name()
		self.githubLabel.setText(f'<a href="https://github.com/Gredwitch/Dagor-Asset-Explorer" style="color:{linkColor}; text-decoration:none;">GitHub</a>')
		self.label.setText(f'<a href="https://github.com/Gredwitch/Dagor-Asset-Explorer-Tools" style="color:{linkColor}; text-decoration:none;">{tr("Blender DMF / DPL importer")}</a>')

		self.setupAppearanceTab()

		self.setupCheckBox(self.exportFolder, SETTINGS_EXPORT_FOLDER)
		self.setupCheckBox(self.convertTex, SETTINGS_FORCE_DDS_CONVERSION)
		self.setupCheckBox(self.expandAll, SETTINGS_EXPAND_ALL)
		self.setupCheckBox(self.extractFolder, SETTINGS_EXTRACT_FOLDER)
		self.setupCheckBox(self.noTexExport, SETTINGS_NO_TEX_EXPORT)
		self.setupCheckBox(self.outputFolder, SETTINGS_OUTPUT_FOLDER)
		self.setupCheckBox(self.exportSourceCollision, SETTINGS_STUDIOMDL_EXPORT_COLLISION)
		self.setupCheckBox(self.exportGameInfo, SETTINGS_EXPORT_GAMEINFO, self.exportGameInfoLayout)
		self.setupCheckBox(self.exportSMD, SETTINGS_EXPORT_SMD, self.exportSMDLayout)
		self.setupCheckBox(self.noMDL, SETTINGS_NO_MDL)
		self.setupCheckBox(self.dontExportExistingTextures, SETTINGS_DONT_EXPORT_EXISTING_TEXTURES)


		self.studiomdlLine.setText(SETTINGS.getValue(SETTINGS_STUDIOMDL_PATH))
		self.studioMdlBtn.clicked.connect(lambda: self.selectFile(tr("Select StudioMDL binary"), ["*.exe"], SETTINGS_STUDIOMDL_PATH, self.studiomdlLine))

		self.vtfCmdLine.setText(SETTINGS.getValue(SETTINGS_VTFCMD_PATH))
		self.vtfCmdBtn.clicked.connect(lambda: self.selectFile(tr("Select VTFCmd binary"), ["*.exe"], SETTINGS_VTFCMD_PATH, self.vtfCmdLine))

		self.gameInfoLine.setText(SETTINGS.getValue(SETTINGS_GAMEINFO_PATH))
		self.gameInfoBtn.clicked.connect(lambda: self.selectFile(tr("Select gameinfo.txt"), ["gameinfo.txt"], SETTINGS_GAMEINFO_PATH, self.gameInfoLine))
	
	def setupAppearanceTab(self):
		tab = QWidget()
		form = QFormLayout(tab)
		form.setLabelAlignment(Qt.AlignLeft | Qt.AlignVCenter)
		form.setHorizontalSpacing(16)
		form.setVerticalSpacing(10)

		self.languageBox = QComboBox()
		self.languageBox.addItem(tr("System default"), LANG_AUTO)
		self.languageBox.addItem("English", LANG_EN)
		self.languageBox.addItem("简体中文", LANG_ZH_CN)
		self.selectComboData(self.languageBox, SETTINGS.getValue(SETTINGS_LANGUAGE))
		self.languageBox.currentIndexChanged.connect(self.languageChanged)

		self.themeBox = QComboBox()
		self.themeBox.addItem(tr("Dark"), THEME_DARK)
		self.themeBox.addItem(tr("Light"), THEME_LIGHT)
		self.selectComboData(self.themeBox, SETTINGS.getValue(SETTINGS_THEME))
		self.themeBox.currentIndexChanged.connect(self.themeChanged)

		self.restartLabel = QLabel(tr("Language changes take effect after restarting the application."))
		self.restartLabel.setProperty("muted", True)
		self.restartLabel.setWordWrap(True)

		form.addRow(tr("Language"), self.languageBox)
		form.addRow(tr("Theme"), self.themeBox)
		form.addRow(self.restartLabel)

		self.tabWidget.addTab(tab, tr("Appearance"))
	
	@staticmethod
	def selectComboData(box:QComboBox, data:str):
		idx = box.findData(data)
		box.setCurrentIndex(idx if idx >= 0 else 0)
	
	def languageChanged(self):
		SETTINGS.setValue(SETTINGS_LANGUAGE, self.languageBox.currentData())

	def themeChanged(self):
		theme = self.themeBox.currentData()

		SETTINGS.setValue(SETTINGS_THEME, theme)
		applyTheme(QApplication.instance(), theme, LANGUAGE == LANG_ZH_CN)

	def selectFile(self, title:str, nameFilters:list[str], settingKey:str, lineEdit:QLineEdit):
		dialog = openFile(self, title = title, nameFilters = nameFilters, fileMode = QFileDialog.ExistingFile)

		if dialog is None:
			return
		
		path = dialog.selectedFiles()[0]

		lineEdit.setText(path)
		SETTINGS.setValue(settingKey, path)
		SETTINGS.saveSettings()

	def setupCheckBox(self, cBox:QCheckBox, setting:str, layout:QVBoxLayout = None):
		val = SETTINGS.getValue(setting)
		cBox.setChecked(val)
		cBox.stateChanged.connect(lambda: self.toggleSetting(setting, layout))

		if layout is not None:
			self.handleLayout(layout, not val)

	def handleLayout(self, layout:QVBoxLayout, enable:bool):
		for i in range(layout.count()):
			child = layout.itemAt(i).widget()

			if not isinstance(child, QCheckBox):
				continue

			child.setDisabled(enable)

	def toggleSetting(self, setting:str, layout:QVBoxLayout = None):
		newVal = not SETTINGS.getValue(setting)

		SETTINGS.setValue(setting, newVal)

		if layout is not None:
			self.handleLayout(layout, not newVal)