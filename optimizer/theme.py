"""Dark theme: colors, Qt stylesheet and palette."""
import os

from PySide6.QtGui import QColor, QPalette

ASSETS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "assets")
ICON_PATH = os.path.join(ASSETS_DIR, "icon.svg")

COLORS = {
    "bg": "#1e1f22",
    "panel": "#2b2d31",
    "border": "#3a3d44",
    "text": "#e6e6e6",
    "muted": "#9aa0a6",
    "disabled": "#6b7078",
    "accent": "#FFCC00",
    "accent_hover": "#FFDD55",
    "accent_dim": "#4a4120",
    "blue": "#1E90FF",
    "blue_hover": "#4169E1",
    "green": "#5cb85c",
    "green_hover": "#6cc66c",
    "red": "#c9302c",
}

STYLESHEET = """
QWidget { color: %(text)s; font-family: "Segoe UI"; font-size: 10pt; }
QMainWindow, #MainArea { background: %(bg)s; }
#Sidebar { background: %(panel)s; border-right: 1px solid %(border)s; }
#SidebarViewport, #SettingsPage { background: transparent; }
#AppTitle { font-size: 15pt; font-weight: 600; color: #ffffff; }
#Muted { color: %(muted)s; }
#Hint { color: %(muted)s; font-size: 9pt; }
#SectionTitle { color: %(muted)s; font-size: 8pt; font-weight: 700; padding-top: 6px; }
#Card { background: %(panel)s; border: 1px solid %(border)s; border-radius: 10px; }
#CardTitle { font-size: 11pt; font-weight: 600; }
#DropHint { color: %(muted)s; border: 2px dashed %(border)s; border-radius: 10px; font-size: 12pt; }
#PreviewImage { color: %(muted)s; }

QPushButton { background: %(border)s; border: 1px solid #4a4e57; border-radius: 6px; padding: 7px 12px; }
QPushButton:hover { background: #454953; }
QPushButton:pressed { background: #33363c; }
QPushButton:disabled { color: %(disabled)s; background: #2f3237; border-color: #383b41; }
QPushButton#Primary { background: %(accent)s; color: %(bg)s; border: none; font-weight: 600; }
QPushButton#Primary:hover { background: %(accent_hover)s; }
QPushButton#Rename { background: %(green)s; color: white; border: none; font-weight: 600; }
QPushButton#Rename:hover { background: %(green_hover)s; }
QPushButton#Browse { background: %(blue)s; color: white; border: none; font-weight: 600; }
QPushButton#Browse:hover { background: %(blue_hover)s; }
QPushButton#Browse:disabled, QPushButton#Rename:disabled, QPushButton#Primary:disabled {
    background: #2f3237; color: %(disabled)s; }
QPushButton#Danger { background: transparent; border: 1px solid %(red)s; color: #ff7b76; }
QPushButton#Danger:hover { background: %(red)s; color: white; }
QPushButton#Small { padding: 4px 10px; font-size: 9pt; }

#SegmentBar { background: %(bg)s; border-radius: 8px; }
QPushButton#Segment { background: transparent; border: none; border-radius: 6px; padding: 7px 10px; color: #b8bcc3; }
QPushButton#Segment:hover { color: #ffffff; }
QPushButton#Segment:checked { background: %(accent)s; color: %(bg)s; font-weight: 600; }

QLineEdit, QComboBox { background: %(bg)s; border: 1px solid %(border)s; border-radius: 6px; padding: 5px 8px; }
QLineEdit:focus, QComboBox:focus, QComboBox:on { border-color: %(accent)s; }
QLineEdit:disabled, QComboBox:disabled { color: %(disabled)s; }
QComboBox QAbstractItemView { background: %(panel)s; border: 1px solid %(border)s;
    selection-background-color: %(accent_dim)s; outline: none; }

QRadioButton, QCheckBox { spacing: 8px; padding: 2px 0; }
QRadioButton:disabled, QCheckBox:disabled { color: %(disabled)s; }
QRadioButton::indicator { width: 14px; height: 14px; border: 2px solid %(disabled)s; border-radius: 9px; background: %(bg)s; }
QRadioButton::indicator:hover, QCheckBox::indicator:hover { border-color: %(accent_hover)s; }
QRadioButton::indicator:checked { border-color: %(accent)s; background: qradialgradient(cx:0.5, cy:0.5, radius:0.5,
    fx:0.5, fy:0.5, stop:0 %(accent)s, stop:0.55 %(accent)s, stop:0.65 %(bg)s, stop:1 %(bg)s); }
QCheckBox::indicator { width: 14px; height: 14px; border: 2px solid %(disabled)s; border-radius: 4px; background: %(bg)s; }
QCheckBox::indicator:checked { border-color: %(accent)s; background: %(accent)s; image: url(%(check_icon)s); }

QSlider::groove:horizontal { height: 4px; background: %(border)s; border-radius: 2px; }
QSlider::sub-page:horizontal { background: %(accent)s; border-radius: 2px; }
QSlider::handle:horizontal { background: %(accent)s; width: 14px; height: 14px; margin: -5px 0; border-radius: 7px; }
QSlider::sub-page:horizontal:disabled { background: %(accent_dim)s; }
QSlider::handle:horizontal:disabled { background: %(disabled)s; }

QTableView { background: #232428; alternate-background-color: #27292d; border: none;
    selection-background-color: %(accent_dim)s; selection-color: #ffffff; outline: none; }
QHeaderView::section { background: %(panel)s; color: #c8ccd2; border: none; border-right: 1px solid %(border)s;
    border-bottom: 1px solid %(border)s; padding: 6px 8px; font-weight: 600; }
QTableCornerButton::section { background: %(panel)s; border: none; }

QProgressBar { background: %(bg)s; border: 1px solid %(border)s; border-radius: 5px; }
QProgressBar::chunk { border-radius: 4px; background: #FFA500; }
QProgressBar[state="processing"]::chunk { background: #FF4B4B; }
QProgressBar[state="done"]::chunk { background: #3fb950; }

QScrollBar:vertical { background: transparent; width: 10px; margin: 0; }
QScrollBar:horizontal { background: transparent; height: 10px; margin: 0; }
QScrollBar::handle:vertical { background: #4a4e57; border-radius: 4px; min-height: 30px; margin: 1px; }
QScrollBar::handle:horizontal { background: #4a4e57; border-radius: 4px; min-width: 30px; margin: 1px; }
QScrollBar::handle:hover { background: #5c616b; }
QScrollBar::add-line, QScrollBar::sub-line { width: 0; height: 0; }
QScrollBar::add-page, QScrollBar::sub-page { background: transparent; }

QStatusBar { background: %(panel)s; border-top: 1px solid %(border)s; }
QStatusBar::item { border: none; }
QSplitter::handle { background: %(bg)s; }
QScrollArea { border: none; background: transparent; }
QToolTip { background: %(panel)s; color: %(text)s; border: 1px solid %(border)s; padding: 4px; }
"""


def build_stylesheet():
    """Fill theme colors and asset paths into the stylesheet"""
    values = dict(COLORS, check_icon=os.path.join(ASSETS_DIR, "check.svg").replace("\\", "/"))
    return STYLESHEET % values


def dark_palette():
    """Palette for parts Qt draws itself (scrollbars, menus, dialogs)"""
    palette = QPalette()
    role = QPalette.ColorRole
    for color_role, color in (
        (role.Window, COLORS["bg"]), (role.WindowText, COLORS["text"]),
        (role.Base, COLORS["bg"]), (role.AlternateBase, "#27292d"),
        (role.Text, COLORS["text"]), (role.Button, COLORS["border"]),
        (role.ButtonText, COLORS["text"]), (role.ToolTipBase, COLORS["panel"]),
        (role.ToolTipText, COLORS["text"]), (role.Highlight, COLORS["accent"]),
        (role.HighlightedText, COLORS["bg"]), (role.PlaceholderText, COLORS["disabled"]),
        (role.Link, COLORS["blue"]),
    ):
        palette.setColor(color_role, QColor(color))
    for color_role in (role.Text, role.ButtonText, role.WindowText):
        palette.setColor(QPalette.ColorGroup.Disabled, color_role, QColor(COLORS["disabled"]))
    return palette
