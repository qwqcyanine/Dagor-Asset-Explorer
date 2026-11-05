from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import QDialog, QWidget, QComboBox, QDoubleSpinBox, QFormLayout, QDialogButtonBox
from util.i18n import tr


class GlideOptionsDialog(QDialog):
	"""Lets the user tweak vehicle stats before a Glide export. Values come prefilled from util.glide.defaultOptions."""

	def __init__(self, parent:QWidget, options:dict):
		super().__init__(parent)

		self.setWindowTitle(tr("Glide export options"))
		self.setWindowFlags(self.windowFlags() & ~Qt.WindowContextHelpButtonHint)

		self.form = QFormLayout(self)
		self.form.setContentsMargins(12, 12, 12, 12)

		self.vehicleType = QComboBox()
		self.vehicleType.addItem(tr("Ground vehicle"), "ground")
		self.vehicleType.addItem(tr("Fixed-wing aircraft"), "plane")
		self.vehicleType.addItem(tr("Helicopter"), "heli")
		initKind = ("heli" if options.get("helicopter") else "plane") if options.get("aircraft") else "ground"
		self.vehicleType.setCurrentIndex({"ground": 0, "plane": 1, "heli": 2}[initKind])
		self.form.addRow(tr("Vehicle type"), self.vehicleType)

		self.transmission = QComboBox()
		self.transmission.addItem(tr("Single differential (pivot on one track)"), True)
		self.transmission.addItem(tr("Double differential (neutral steer)"), False)
		self.transmission.setCurrentIndex(0 if options.get("singleFlow", True) else 1)
		self.wheeled = options.get("wheeled", False)
		self.form.addRow(tr("Transmission"), self.transmission)

		self.armor = QComboBox()
		self.armor.addItem(tr("Upgraded (all modifications researched)"), True)
		self.armor.addItem(tr("Stock"), False)
		self.armor.setCurrentIndex(0 if options.get("upgraded", True) else 1)
		self.form.addRow(tr("Armor kit"), self.armor)

		self.spins = {}

		for key, label, lo, hi, suffix, fallback in (
			("mass", tr("Mass"), 100, 50000, " kg", 20000),
			("maxFwdSpeed", tr("Max forward speed"), 5, 150, " km/h", 60),
			("maxRevSpeed", tr("Max reverse speed"), 1, 150, " km/h", 15),
			("maxSpeed", tr("Max flight speed"), 500, 10000, "", 2400),
			("engineForce", tr("Engine thrust"), 50, 2000, "", 350),
		):
			spin = QDoubleSpinBox()
			spin.setRange(lo, hi)
			spin.setDecimals(0)
			spin.setSuffix(suffix)
			spin.setValue(options.get(key, fallback))
			self.form.addRow(label, spin)
			self.spins[key] = spin

		buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
		buttons.accepted.connect(self.accept)
		buttons.rejected.connect(self.reject)
		self.form.addRow(buttons)

		self.vehicleType.currentIndexChanged.connect(self._updateRows)
		self._updateRows()

	def _setRowVisible(self, widget:QWidget, visible:bool):
		label = self.form.labelForField(widget)
		if label is not None:
			label.setVisible(visible)
		widget.setVisible(visible)

	def _updateRows(self):
		kind = self.vehicleType.currentData()
		ground = kind == "ground"
		plane = kind == "plane"
		self._setRowVisible(self.transmission, ground and not self.wheeled)
		self._setRowVisible(self.armor, ground)
		self._setRowVisible(self.spins["maxFwdSpeed"], ground)
		self._setRowVisible(self.spins["maxRevSpeed"], ground)
		self._setRowVisible(self.spins["maxSpeed"], plane)
		self._setRowVisible(self.spins["engineForce"], plane)
		self.adjustSize()

	def options(self) -> dict:
		kind = self.vehicleType.currentData()
		if kind != "ground":
			return {
				"aircraft": True,
				"helicopter": kind == "heli",
				"mass": self.spins["mass"].value(),
				"maxSpeed": self.spins["maxSpeed"].value(),
				"engineForce": self.spins["engineForce"].value(),
			}
		return {
			"aircraft": False,
			"helicopter": False,
			"singleFlow": self.transmission.currentData(),
			"wheeled": self.wheeled,
			"upgraded": self.armor.currentData(),
			"mass": self.spins["mass"].value(),
			"maxFwdSpeed": self.spins["maxFwdSpeed"].value(),
			"maxRevSpeed": self.spins["maxRevSpeed"].value(),
		}
