
import sys
from os import path

sys.path.append(path.dirname(path.dirname(path.abspath(__file__))))

from PyQt5.QtGui import QPalette, QColor, QFont
from PyQt5.QtWidgets import QApplication, QStyleFactory
from util.enums import THEME_DARK, THEME_LIGHT
from util.misc import getResPath

_COLORS = {
	THEME_DARK: {
		"window": "#1e1f22",
		"surface": "#2b2d31",
		"base": "#232428",
		"alt": "#27292d",
		"border": "#3a3c42",
		"hover": "#35373c",
		"text": "#e3e5e8",
		"muted": "#949ba4",
		"disabled": "#5c6068",
		"accent": "#4f8cff",
		"accentHover": "#6a9dff",
		"accentText": "#ffffff",
		"selection": "#2f4a7a",
	},
	THEME_LIGHT: {
		"window": "#f3f4f6",
		"surface": "#ffffff",
		"base": "#ffffff",
		"alt": "#f8f9fb",
		"border": "#d6d9de",
		"hover": "#e9ecf1",
		"text": "#1f2328",
		"muted": "#656d76",
		"disabled": "#a8afb8",
		"accent": "#2f6fed",
		"accentHover": "#4a83f0",
		"accentText": "#ffffff",
		"selection": "#cfe0ff",
	},
}

_QSS = """
QWidget {{
	color: {text};
}}
QMainWindow, QDialog {{
	background: {window};
}}
QToolTip {{
	background: {surface};
	color: {text};
	border: 1px solid {border};
	border-radius: 4px;
	padding: 4px 6px;
}}

/* Menus */
QMenuBar {{
	background: {window};
	border-bottom: 1px solid {border};
	padding: 2px 4px;
}}
QMenuBar::item {{
	background: transparent;
	padding: 5px 10px;
	border-radius: 4px;
}}
QMenuBar::item:selected, QMenuBar::item:pressed {{
	background: {hover};
}}
QMenu {{
	background: {surface};
	border: 1px solid {border};
	border-radius: 6px;
	padding: 4px;
}}
QMenu::item {{
	padding: 6px 28px 6px 14px;
	border-radius: 4px;
}}
QMenu::item:selected {{
	background: {accent};
	color: {accentText};
}}
QMenu::item:disabled {{
	color: {disabled};
}}
QMenu::separator {{
	height: 1px;
	background: {border};
	margin: 4px 8px;
}}

/* Toolbar */
QToolBar {{
	background: {window};
	border: none;
	border-bottom: 1px solid {border};
	padding: 4px 8px;
	spacing: 4px;
}}
QToolBar::separator {{
	background: {border};
	width: 1px;
	margin: 4px 6px;
}}
QToolButton {{
	background: transparent;
	border: 1px solid transparent;
	border-radius: 6px;
	padding: 5px 10px;
}}
QToolButton:hover {{
	background: {hover};
	border-color: {border};
}}
QToolButton:pressed {{
	background: {border};
}}

/* Tabs */
QTabWidget::pane {{
	background: {surface};
	border: 1px solid {border};
	border-radius: 8px;
	top: -1px;
}}
QTabBar::tab {{
	background: transparent;
	color: {muted};
	padding: 8px 16px;
	margin-right: 2px;
	border: none;
	border-bottom: 2px solid transparent;
}}
QTabBar::tab:hover {{
	color: {text};
}}
QTabBar::tab:selected {{
	color: {text};
	border-bottom: 2px solid {accent};
}}

/* Inputs */
QLineEdit, QComboBox {{
	background: {base};
	border: 1px solid {border};
	border-radius: 6px;
	padding: 6px 10px;
	selection-background-color: {accent};
	selection-color: {accentText};
}}
QLineEdit:focus, QComboBox:focus {{
	border-color: {accent};
}}
QLineEdit:disabled {{
	color: {muted};
	background: {alt};
}}
QComboBox::drop-down {{
	border: none;
	width: 24px;
}}
QComboBox::down-arrow {{
	image: url({arrow});
	width: 10px;
	height: 6px;
}}
QStatusBar {{
	background: {window};
	border-top: 1px solid {border};
}}
QStatusBar QLabel {{
	padding: 2px 8px;
}}
QComboBox QAbstractItemView {{
	background: {surface};
	border: 1px solid {border};
	selection-background-color: {accent};
	selection-color: {accentText};
	outline: 0;
}}

/* Buttons */
QPushButton {{
	background: {surface};
	border: 1px solid {border};
	border-radius: 6px;
	padding: 6px 16px;
	min-height: 18px;
}}
QPushButton:hover {{
	background: {hover};
}}
QPushButton:pressed {{
	background: {border};
}}
QPushButton:disabled {{
	color: {disabled};
	background: {alt};
}}
QPushButton:checked {{
	background: {accent};
	border-color: {accent};
	color: {accentText};
}}
QPushButton:checked:hover {{
	background: {accentHover};
}}
QPushButton[primary="true"] {{
	background: {accent};
	border-color: {accent};
	color: {accentText};
}}
QPushButton[primary="true"]:hover {{
	background: {accentHover};
}}
QPushButton[primary="true"]:disabled {{
	background: {alt};
	border-color: {border};
	color: {disabled};
}}

QCheckBox {{
	spacing: 8px;
	padding: 3px 0;
}}
QCheckBox:disabled {{
	color: {disabled};
}}

/* Trees */
QTreeView {{
	background: {base};
	alternate-background-color: {alt};
	border: 1px solid {border};
	border-radius: 6px;
	outline: 0;
	selection-background-color: {selection};
	selection-color: {text};
}}
QTreeView::item {{
	padding: 3px 2px;
}}
QTreeView::item:hover {{
	background: {hover};
}}
QTreeView::item:selected {{
	background: {selection};
	color: {text};
}}
QHeaderView {{
	background: {base};
	border: none;
}}
QHeaderView::section {{
	background: {base};
	color: {muted};
	border: none;
	border-bottom: 1px solid {border};
	border-right: 1px solid {border};
	padding: 6px 8px;
	font-weight: 600;
}}
QHeaderView::section:last {{
	border-right: none;
}}

/* Scrolling */
QScrollArea {{
	background: transparent;
	border: 1px solid {border};
	border-radius: 6px;
}}
QScrollArea > QWidget > QWidget {{
	background: transparent;
}}
QScrollBar:vertical {{
	background: transparent;
	width: 12px;
	margin: 2px;
}}
QScrollBar:horizontal {{
	background: transparent;
	height: 12px;
	margin: 2px;
}}
QScrollBar::handle:vertical, QScrollBar::handle:horizontal {{
	background: {border};
	border-radius: 4px;
	min-height: 24px;
	min-width: 24px;
}}
QScrollBar::handle:vertical:hover, QScrollBar::handle:horizontal:hover {{
	background: {muted};
}}
QScrollBar::add-line, QScrollBar::sub-line {{
	width: 0;
	height: 0;
}}
QScrollBar::add-page, QScrollBar::sub-page {{
	background: transparent;
}}

/* Progress */
QProgressBar {{
	background: {base};
	border: 1px solid {border};
	border-radius: 5px;
	height: 10px;
	text-align: center;
}}
QProgressBar::chunk {{
	background: {accent};
	border-radius: 4px;
}}

QLabel[muted="true"] {{
	color: {muted};
}}
QLabel[heading="true"] {{
	font-size: 11pt;
	font-weight: 600;
}}
"""

def _buildPalette(c:dict) -> QPalette:
	pal = QPalette()

	roles = {
		QPalette.Window: c["window"],
		QPalette.WindowText: c["text"],
		QPalette.Base: c["base"],
		QPalette.AlternateBase: c["alt"],
		QPalette.ToolTipBase: c["surface"],
		QPalette.ToolTipText: c["text"],
		QPalette.PlaceholderText: c["muted"],
		QPalette.Text: c["text"],
		QPalette.Button: c["surface"],
		QPalette.ButtonText: c["text"],
		QPalette.BrightText: "#ff5555",
		QPalette.Highlight: c["accent"],
		QPalette.HighlightedText: c["accentText"],
		QPalette.Link: c["accent"],
		QPalette.LinkVisited: c["accent"],
		QPalette.Light: c["hover"],
		QPalette.Midlight: c["border"],
		QPalette.Mid: c["border"],
		QPalette.Dark: c["window"],
		QPalette.Shadow: "#000000",
	}

	for role, color in roles.items():
		pal.setColor(role, QColor(color))
	
	for role in (QPalette.WindowText, QPalette.Text, QPalette.ButtonText):
		pal.setColor(QPalette.Disabled, role, QColor(c["disabled"]))

	return pal

def applyTheme(app:QApplication, theme:str, chinese:bool = False):
	colors = dict(_COLORS.get(theme, _COLORS[THEME_DARK]))
	colors["arrow"] = getResPath(f"arrow_down_{theme if theme in _COLORS else THEME_DARK}.svg").replace("\\", "/")

	app.setStyle(QStyleFactory.create("Fusion"))
	app.setPalette(_buildPalette(colors))

	font = QFont()
	families = ["Segoe UI", "Microsoft YaHei UI", "PingFang SC", "Noto Sans CJK SC"]

	if chinese: # prefer a CJK font so Latin and Chinese glyphs share metrics
		families = ["Microsoft YaHei UI", "Segoe UI", "PingFang SC", "Noto Sans CJK SC"]
	
	font.setFamilies(families)
	font.setPointSize(10)
	app.setFont(font)

	app.setStyleSheet(_QSS.format(**colors))
