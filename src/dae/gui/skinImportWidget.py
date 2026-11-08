from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout, QListWidget, QListWidgetItem, QPushButton, QFileDialog, QMessageBox, QLabel
from util.i18n import tr
from util.wtskins import SkinArchive
from zipfile import BadZipFile


class SkinImportWidget(QWidget):
	"""Ordered ZIPs become MDL skins 1..N; skin 0 remains the original."""
	def __init__(self, parent=None, modelName=None):
		super().__init__(parent)
		self.modelName = modelName
		layout = QVBoxLayout(self)
		layout.addWidget(QLabel(tr("Original paint is skin 0; imported ZIPs become skins 1, 2, ...")))
		self.files = QListWidget()
		layout.addWidget(self.files)
		buttons = QHBoxLayout()
		for label, callback in (("Import WT skin ZIP...", self.addSkins), ("Remove selected skin", self.removeSkin)):
			button = QPushButton(tr(label))
			button.clicked.connect(callback)
			buttons.addWidget(button)
		layout.addLayout(buttons)

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
