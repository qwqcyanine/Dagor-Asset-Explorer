from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import QDialog, QWidget, QComboBox, QDoubleSpinBox, QFormLayout, QDialogButtonBox
from util.i18n import tr


class GlideOptionsDialog(QDialog):
	"""Lets the user tweak the tank stats before a Glide export. Values come prefilled from util.glide.defaultOptions."""

	def __init__(self, parent:QWidget, options:dict):
		super().__init__(parent)

		self.setWindowTitle(tr("Glide export options"))
		self.setWindowFlags(self.windowFlags() & ~Qt.WindowContextHelpButtonHint)

		form = QFormLayout(self)
		form.setContentsMargins(12, 12, 12, 12)

		self.transmission = QComboBox()
		self.transmission.addItem(tr("Single differential (pivot on one track)"), True)
		self.transmission.addItem(tr("Double differential (neutral steer)"), False)
		self.transmission.setCurrentIndex(0 if options["singleFlow"] else 1)
		form.addRow(tr("Transmission"), self.transmission)

		self.armor = QComboBox()
		self.armor.addItem(tr("Upgraded (all modifications researched)"), True)
		self.armor.addItem(tr("Stock"), False)
		self.armor.setCurrentIndex(0 if options["upgraded"] else 1)
		form.addRow(tr("Armor kit"), self.armor)

		self.spins = {}

		for key, label, lo, hi, suffix in (
			("mass", tr("Mass"), 1000, 50000, " kg"),
			("maxFwdSpeed", tr("Max forward speed"), 5, 150, " km/h"),
			("maxRevSpeed", tr("Max reverse speed"), 1, 150, " km/h"),
		):
			spin = QDoubleSpinBox()
			spin.setRange(lo, hi)
			spin.setDecimals(0)
			spin.setSuffix(suffix)
			spin.setValue(options[key])
			form.addRow(label, spin)
			self.spins[key] = spin

		buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
		buttons.accepted.connect(self.accept)
		buttons.rejected.connect(self.reject)
		form.addRow(buttons)

	def options(self) -> dict:
		return {"singleFlow": self.transmission.currentData(), "upgraded": self.armor.currentData(), **{k:s.value() for k, s in self.spins.items()}}
