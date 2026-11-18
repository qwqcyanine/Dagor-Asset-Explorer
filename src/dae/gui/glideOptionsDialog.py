from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import QDialog, QWidget, QComboBox, QDoubleSpinBox, QFormLayout, QDialogButtonBox, QPushButton, QScrollArea, QLabel
from util.enums import SETTINGS_VTF_FORMAT, VTF_FORMAT_DXT5, VTF_FORMAT_RGBA8888
from util.i18n import tr
from util.settings import SETTINGS
from util.wtloadout import presetLabel


class GlideOptionsDialog(QDialog):
	"""Lets the user tweak vehicle stats before a Glide export. Values come prefilled from util.glide.defaultOptions."""

	def __init__(self, parent:QWidget, options:dict, modelName=None, loadouts=(), slots=(), preview=None, weaponLabels=None, gameRoot=None):
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

		self.loadout = QComboBox()
		self.loadout.addItem(tr("No external weapons"), "")
		for name, presetPath in loadouts:
			self.loadout.addItem(name, presetPath)
		self.form.addRow(tr("Weapon loadout (export-time)"), self.loadout)
		self.slotCombos = {}
		self.slotPanel = QScrollArea()
		self.slotPanel.setWidgetResizable(True)
		self.slotPanel.setMaximumHeight(240)
		self.slotPanel.setToolTip(tr("Native choices per slot; cross-slot restrictions and payload limits are not checked."))
		slotWidget = QWidget()
		slotForm = QFormLayout(slotWidget)
		for index, choices in slots:
			combo = QComboBox()
			combo.addItem(tr("Empty hardpoint"), "")
			for name, preset in choices:
				label, tooltip = presetLabel(preset, weaponLabels or {})
				combo.addItem(label or name, name)
				combo.setItemData(combo.count() - 1, tooltip, Qt.ToolTipRole)
			slotForm.addRow(tr("Hardpoint {slot}", slot=index), combo)
			self.slotCombos[index] = combo
		self.slotPanel.setWidget(slotWidget)
		if self.slotCombos:
			self.loadout.addItem(tr("Custom hardpoints"), "__custom__")
		self.form.addRow(self.slotPanel)
		self.reloadSpins = {}
		for key, label in (("gun", "Gun reload time"), ("missile", "Missile reload time"), ("bomb", "Bomb reload time")):
			spin = QDoubleSpinBox()
			spin.setRange(0, 3600)
			spin.setDecimals(1)
			spin.setSpecialValueText(tr("WT default"))
			spin.setSuffix(" s")
			self.reloadSpins[key] = spin
			self.form.addRow(tr(label), spin)
		self.previewButton = QPushButton(tr("Preview selected loadout"))
		self.previewButton.setEnabled(preview is not None)
		self.previewButton.setToolTip(tr("Geometry preview only; Source shaders and animations are not simulated."))
		if preview is not None:
			self.previewButton.clicked.connect(lambda: preview(self.options()))
		self.form.addRow(self.previewButton)
		self.loadout.currentIndexChanged.connect(self._updateRows)

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

		for key, label, lo, hi, suffix, fallback, decimals in (
			("mass", tr("Mass"), 100, 50000, " kg", 20000, 0),
			("maxFwdSpeed", tr("Max forward speed"), 5, 150, " km/h", 60, 0),
			("maxRevSpeed", tr("Max reverse speed"), 1, 150, " km/h", 15, 0),
			("maxSpeed", tr("Max flight speed"), 500, 10000, "", 2400, 0),
			("engineForce", tr("Engine thrust"), 50, 2000, "", 350, 0),
			("suspensionSag", tr("Suspension sag"), 2.0, 50.0, " cm", 12.5, 1),
			("suspensionDamping", tr("Suspension damping"), 10.0, 100.0, " %", 50.0, 1),
		):
			spin = QDoubleSpinBox()
			spin.setRange(lo, hi)
			spin.setDecimals(decimals)
			spin.setSuffix(suffix)
			spin.setValue(options.get(key, fallback))
			self.form.addRow(label, spin)
			self.spins[key] = spin
		for key, tip in (
			("suspensionSag", tr("Auto-filled from War Thunder. Smaller = stiffer spring (5–9 cm stiff, 10–15 cm medium/MBT, 18–30+ cm soft).")),
			("suspensionDamping", tr("Auto-filled from War Thunder. Larger = firmer shock absorption & less bounce (20–35% soft/bouncy, 45–65% medium, 70–100% firm).")),
		):
			self.spins[key].setToolTip(tip)
			lbl = self.form.labelForField(self.spins[key])
			if lbl is not None:
				lbl.setToolTip(tip)

		self.suspensionHint = QLabel(tr(
			"Sag (smaller = stiffer): 5–9 cm stiff | 10–15 cm medium | 18–30+ cm soft\n"
			"Damping (larger = firmer): 20–35% bouncy | 45–65% medium | 70–100% firm"
		))
		self.suspensionHint.setProperty("muted", True)
		self.suspensionHint.setWordWrap(True)
		self.form.addRow(self.suspensionHint)

		self.vtfFormat = QComboBox()
		self.vtfFormat.addItem("DXT5", VTF_FORMAT_DXT5)
		self.vtfFormat.addItem("RGBA8888", VTF_FORMAT_RGBA8888)
		initFmt = options.get("vtfFormat") or SETTINGS.getValue(SETTINGS_VTF_FORMAT)
		fmtIdx = self.vtfFormat.findData(initFmt)
		self.vtfFormat.setCurrentIndex(fmtIdx if fmtIdx >= 0 else 0)
		self.form.addRow(tr("VTF texture format"), self.vtfFormat)

		from gui.skinImportWidget import SkinImportWidget
		self.skins = SkinImportWidget(self, modelName, gameRoot)
		self.form.addRow(tr("MDL skins"), self.skins)

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
		self._setRowVisible(self.loadout, not ground)
		self.slotPanel.setVisible(not ground and self.loadout.currentData() == "__custom__")
		self.previewButton.setVisible(not ground)
		for spin in self.reloadSpins.values():
			self._setRowVisible(spin, not ground)
		self._setRowVisible(self.spins["maxFwdSpeed"], ground)
		self._setRowVisible(self.spins["maxRevSpeed"], ground)
		self._setRowVisible(self.spins["suspensionSag"], ground)
		self._setRowVisible(self.spins["suspensionDamping"], ground)
		self.suspensionHint.setVisible(ground)
		self._setRowVisible(self.spins["maxSpeed"], plane)
		self._setRowVisible(self.spins["engineForce"], plane)
		self.adjustSize()

	def options(self) -> dict:
		kind = self.vehicleType.currentData()
		if kind != "ground":
			return {
				"skins": self.skins.paths(),
				"vtfFormat": self.vtfFormat.currentData(),
				"aircraft": True,
				"loadout": {index: combo.currentData() for index, combo in self.slotCombos.items()} if self.loadout.currentData() == "__custom__" else self.loadout.currentData(),
				"reloadTimes": {key: spin.value() for key, spin in self.reloadSpins.items() if spin.value() > 0},
				"helicopter": kind == "heli",
				"mass": self.spins["mass"].value(),
				"maxSpeed": self.spins["maxSpeed"].value(),
				"engineForce": self.spins["engineForce"].value(),
			}
		return {
			"skins": self.skins.paths(),
			"vtfFormat": self.vtfFormat.currentData(),
			"aircraft": False,
			"helicopter": False,
			"singleFlow": self.transmission.currentData(),
			"wheeled": self.wheeled,
			"upgraded": self.armor.currentData(),
			"mass": self.spins["mass"].value(),
			"maxFwdSpeed": self.spins["maxFwdSpeed"].value(),
			"maxRevSpeed": self.spins["maxRevSpeed"].value(),
			"suspensionSag": self.spins["suspensionSag"].value(),
			"suspensionDamping": self.spins["suspensionDamping"].value(),
		}
