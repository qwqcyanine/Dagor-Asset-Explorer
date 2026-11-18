from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout, QListWidget, QListWidgetItem, QPushButton, QFileDialog, QMessageBox, QLabel, QComboBox
from util.i18n import tr, LANGUAGE
from util.wtskins import SkinArchive, builtinSkins
from zipfile import BadZipFile


class SkinImportWidget(QWidget):
	"""Ordered ZIPs and built-in WT skins become MDL skins 1..N; skin 0 remains the original."""
	def __init__(self, parent=None, modelName=None, gameRoot=None):
		super().__init__(parent)
		self.modelName = modelName
		self.gameRoot = gameRoot
		self.builtins = builtinSkins(gameRoot, modelName, LANGUAGE) if gameRoot and modelName else []
		layout = QVBoxLayout(self)
		layout.addWidget(QLabel(tr("Original paint is skin 0; imported ZIPs become skins 1, 2, ...")))
		self.builtinRow = QWidget(self)
		builtinLayout = QHBoxLayout(self.builtinRow)
		builtinLayout.setContentsMargins(0, 0, 0, 0)
		self.builtinCombo = QComboBox(self.builtinRow)
		for skin in self.builtins:
			self.builtinCombo.addItem(skin["label"], skin["id"])
		builtinLayout.addWidget(self.builtinCombo, 1)
		for label, callback in (("Add built-in skin", self.addBuiltinSkin), ("Add all built-in skins", self.addAllBuiltinSkins)):
			btn = QPushButton(tr(label), self.builtinRow)
			btn.clicked.connect(callback)
			builtinLayout.addWidget(btn)
		self.builtinRow.setVisible(bool(self.builtins))
		layout.addWidget(self.builtinRow)
		self.files = QListWidget()
		layout.addWidget(self.files)
		buttons = QHBoxLayout()
		for label, callback in (("Import WT skin ZIP...", self.addSkins), ("Remove selected skin", self.removeSkin)):
			button = QPushButton(tr(label))
			button.clicked.connect(callback)
			buttons.addWidget(button)
		layout.addLayout(buttons)

	def _appendSkinItem(self, text: str, value: str):
		if not value or value in self.paths():
			return
		item = QListWidgetItem(text)
		item.setData(Qt.UserRole, value)
		item.setToolTip(text)
		self.files.addItem(item)

	def addBuiltinSkin(self):
		idx = self.builtinCombo.currentIndex()
		if idx >= 0:
			self._appendSkinItem(f"[WT] {self.builtinCombo.itemText(idx)}", self.builtinCombo.itemData(idx))

	def addAllBuiltinSkins(self):
		for idx in range(self.builtinCombo.count()):
			self._appendSkinItem(f"[WT] {self.builtinCombo.itemText(idx)}", self.builtinCombo.itemData(idx))

	def addSkins(self):
		files, _ = QFileDialog.getOpenFileNames(self, tr("Import WT skin ZIP..."), "", "War Thunder UserSkin (*.zip)")
		for filename in files:
			if filename in self.paths():
				continue
			try:
				skin = SkinArchive(filename, self.modelName)
			except (ValueError, OSError, UnicodeError, BadZipFile) as exc:
				QMessageBox.warning(self, tr("Skin import failed"), str(exc))
				continue
			item = QListWidgetItem(f"{filename} → {skin.manifest}")
			item.setData(Qt.UserRole, filename)
			item.setToolTip(item.text())
			self.files.addItem(item)

	def removeSkin(self):
		self.files.takeItem(self.files.currentRow())

	def paths(self):
		return [self.files.item(i).data(Qt.UserRole) or self.files.item(i).text() for i in range(self.files.count())]
