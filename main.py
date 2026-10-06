"""Brojač kalorija - PySide6 (Qt6) + JSON skladište (bez baze podataka).

Fajlovi:
  foods.json  - sve namirnice (ugrađene + tvoje)
  diary.json  - dnevnik unosa i dnevni cilj
  images/     - slike namirnica
"""
import json
import shutil
import sys
import uuid
from dataclasses import dataclass, field, fields
from datetime import date
from pathlib import Path

from PySide6.QtCore import QDate, QSize, Qt
from PySide6.QtGui import QColor, QFont, QIcon, QPainter, QPixmap
from PySide6.QtWidgets import (
    QAbstractItemView, QApplication, QDateEdit, QDialog, QDialogButtonBox,
    QDoubleSpinBox, QFileDialog, QFormLayout, QGroupBox, QHBoxLayout,
    QHeaderView, QLabel, QLineEdit, QListWidget, QListWidgetItem,
    QMainWindow, QMessageBox, QProgressBar, QPushButton, QSpinBox,
    QTableWidget, QTableWidgetItem, QTabWidget, QVBoxLayout, QWidget,
)

if getattr(sys, "frozen", False):  # pokrenuto kao spakovan program
    BUNDLE_DIR = Path(sys._MEIPASS)           # ovde PyInstaller raspakuje fajlove
    APP_DIR = Path.home() / ".kalorije"       # ovde se čuvaju podaci korisnika
    APP_DIR.mkdir(exist_ok=True)
    if not (APP_DIR / "foods.json").exists():  # prvo pokretanje: kopiraj seed
        shutil.copy2(BUNDLE_DIR / "foods.json", APP_DIR / "foods.json")
        if (BUNDLE_DIR / "images").exists():
            shutil.copytree(BUNDLE_DIR / "images", APP_DIR / "images", dirs_exist_ok=True)
else:
    APP_DIR = Path(__file__).resolve().parent
    
FOODS_FILE = APP_DIR / "foods.json"
DIARY_FILE = APP_DIR / "diary.json"
IMG_DIR = APP_DIR / "images"

_TR = str.maketrans({"š": "s", "đ": "d", "č": "c", "ć": "c", "ž": "z"})


def norm(text: str) -> str:
    """Za pretragu: mala slova, bez dijakritika ('šargarepa' == 'sargarepa')."""
    return text.lower().translate(_TR).replace("dj", "d")


# ----------------------------------------------------------------- MODEL ---
@dataclass
class Food:
    """Namirnica; sve nutritivne vrednosti su na 100 g."""
    name: str
    kcal: float
    protein: float
    carbs: float
    fat: float
    image: str = ""
    wiki: str = ""
    custom: bool = False
    id: str = field(default_factory=lambda: uuid.uuid4().hex[:8])

    def scaled(self, grams: float) -> dict:
        k = grams / 100.0
        return {
            "name": self.name,
            "grams": grams,
            "kcal": round(self.kcal * k, 1),
            "protein": round(self.protein * k, 1),
            "carbs": round(self.carbs * k, 1),
            "fat": round(self.fat * k, 1),
        }


class Storage:
    """Čitanje/pisanje JSON fajlova."""

    def __init__(self):
        IMG_DIR.mkdir(exist_ok=True)
        known = {f.name for f in fields(Food)}
        raw = self._read(FOODS_FILE, [])
        self.foods = [Food(**{k: v for k, v in d.items() if k in known}) for d in raw]
        self.diary = self._read(DIARY_FILE, {})
        self.diary.setdefault("goal", 2000)
        self.diary.setdefault("days", {})

    @staticmethod
    def _read(path: Path, default):
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (FileNotFoundError, json.JSONDecodeError):
            return default

    @staticmethod
    def _write(path: Path, data):
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        tmp.replace(path)

    def save_foods(self):
        self._write(FOODS_FILE, [f.__dict__ for f in self.foods])

    def save_diary(self):
        self._write(DIARY_FILE, self.diary)

    def food_by_id(self, food_id):
        return next((f for f in self.foods if f.id == food_id), None)

    def entries(self, day: str) -> list:
        return self.diary["days"].get(day, [])

    def add_entry(self, day: str, food: Food, grams: float):
        self.diary["days"].setdefault(day, []).append(food.scaled(grams))
        self.save_diary()

    def remove_entry(self, day: str, index: int):
        items = self.diary["days"].get(day, [])
        if 0 <= index < len(items):
            items.pop(index)
            if not items:
                del self.diary["days"][day]
            self.save_diary()

    @staticmethod
    def totals(entries: list) -> dict:
        return {k: round(sum(e[k] for e in entries), 1)
                for k in ("kcal", "protein", "carbs", "fat")}


# ------------------------------------------------------------------ IKONE ---
_icon_cache: dict = {}


def food_icon(food: Food) -> QIcon:
    if food.id in _icon_cache:
        return _icon_cache[food.id]
    pm = QPixmap()
    if food.image:
        pm = QPixmap(str(APP_DIR / food.image))
    if pm.isNull():  # rezervna ikona: obojen krug sa početnim slovom
        pm = QPixmap(64, 64)
        pm.fill(Qt.transparent)
        p = QPainter(pm)
        p.setRenderHint(QPainter.Antialiasing)
        p.setBrush(QColor.fromHsv(sum(map(ord, food.name)) % 360, 110, 215))
        p.setPen(Qt.NoPen)
        p.drawEllipse(2, 2, 60, 60)
        p.setPen(Qt.white)
        p.setFont(QFont("Sans", 26, QFont.Bold))
        p.drawText(pm.rect(), Qt.AlignCenter, food.name[:1].upper())
        p.end()
    icon = QIcon(pm)
    _icon_cache[food.id] = icon
    return icon


# ------------------------------------------------------- DIJALOG NAMIRNICA ---
class FoodDialog(QDialog):
    def __init__(self, parent=None, food: Food | None = None):
        super().__init__(parent)
        self.setWindowTitle("Izmena namirnice" if food else "Nova namirnica")
        self.food = food
        self.new_image: Path | None = None

        self.name = QLineEdit()
        self.kcal = self._spin(" kcal")
        self.protein = self._spin(" g")
        self.carbs = self._spin(" g")
        self.fat = self._spin(" g")

        self.preview = QLabel()
        self.preview.setFixedSize(96, 96)
        self.preview.setAlignment(Qt.AlignCenter)
        self.preview.setStyleSheet("border: 1px solid #888; border-radius: 6px;")
        pick = QPushButton("Izaberi sliku...")
        pick.clicked.connect(self.pick_image)

        form = QFormLayout()
        form.addRow("Naziv:", self.name)
        form.addRow("Kalorije (na 100 g):", self.kcal)
        form.addRow("Proteini (na 100 g):", self.protein)
        form.addRow("Ugljeni hidrati (na 100 g):", self.carbs)
        form.addRow("Masti (na 100 g):", self.fat)
        img_row = QHBoxLayout()
        img_row.addWidget(self.preview)
        img_row.addWidget(pick, alignment=Qt.AlignTop)
        form.addRow("Slika:", img_row)

        buttons = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout = QVBoxLayout(self)
        layout.addLayout(form)
        layout.addWidget(buttons)

        if food:
            self.name.setText(food.name)
            self.kcal.setValue(food.kcal)
            self.protein.setValue(food.protein)
            self.carbs.setValue(food.carbs)
            self.fat.setValue(food.fat)
            self.preview.setPixmap(food_icon(food).pixmap(96, 96))

    @staticmethod
    def _spin(suffix):
        s = QDoubleSpinBox()
        s.setRange(0, 10000)
        s.setDecimals(1)
        s.setSuffix(suffix)
        return s

    def pick_image(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "Izaberi sliku", "", "Slike (*.png *.jpg *.jpeg *.webp)")
        if path:
            self.new_image = Path(path)
            self.preview.setPixmap(QPixmap(path).scaled(
                96, 96, Qt.KeepAspectRatio, Qt.SmoothTransformation))

    def accept(self):
        if not self.name.text().strip():
            QMessageBox.warning(self, "Greška", "Unesi naziv namirnice.")
            return
        super().accept()

    def get_food(self) -> Food:
        food = self.food or Food("", 0, 0, 0, 0, custom=True)
        food.name = self.name.text().strip()
        food.kcal = self.kcal.value()
        food.protein = self.protein.value()
        food.carbs = self.carbs.value()
        food.fat = self.fat.value()
        if self.new_image:  # kopiraj sliku u images/ da ostane sačuvana
            dest = IMG_DIR / f"{food.id}{self.new_image.suffix.lower()}"
            shutil.copy2(self.new_image, dest)
            food.image = f"images/{dest.name}"
            _icon_cache.pop(food.id, None)
        return food


# --------------------------------------------------------- GLAVNI PROZOR ---
class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Brojač kalorija")
        self.resize(1100, 680)
        self.store = Storage()

        tabs = QTabWidget()
        tabs.addTab(self._build_diary_tab(), "Dnevnik")
        tabs.addTab(self._build_history_tab(), "Istorija")
        tabs.currentChanged.connect(lambda _: self.refresh_history())
        self.setCentralWidget(tabs)

        self.populate_foods()
        self.refresh_day()
        self.refresh_history()

    # ---- izgradnja UI ----
    def _build_diary_tab(self) -> QWidget:
        # leva strana: namirnice
        self.search = QLineEdit()
        self.search.setPlaceholderText("Pretraži namirnice...")
        self.search.setClearButtonEnabled(True)
        self.search.textChanged.connect(self.populate_foods)

        self.food_list = QListWidget()
        self.food_list.setIconSize(QSize(48, 48))
        self.food_list.itemDoubleClicked.connect(lambda _: self.add_to_diary())

        new_btn = QPushButton("Nova")
        edit_btn = QPushButton("Izmeni")
        del_btn = QPushButton("Obriši")
        new_btn.clicked.connect(self.new_food)
        edit_btn.clicked.connect(self.edit_food)
        del_btn.clicked.connect(self.delete_food)
        crud = QHBoxLayout()
        for b in (new_btn, edit_btn, del_btn):
            crud.addWidget(b)

        self.grams = QDoubleSpinBox()
        self.grams.setRange(1, 5000)
        self.grams.setValue(100)
        self.grams.setSuffix(" g")
        add_btn = QPushButton("Dodaj u dnevnik")
        add_btn.clicked.connect(self.add_to_diary)
        add_row = QHBoxLayout()
        add_row.addWidget(QLabel("Količina:"))
        add_row.addWidget(self.grams)
        add_row.addWidget(add_btn, 1)

        left_box = QGroupBox("Namirnice")
        left = QVBoxLayout(left_box)
        left.addWidget(self.search)
        left.addWidget(self.food_list)
        left.addLayout(crud)
        left.addLayout(add_row)

        # desna strana: dan
        prev_btn, next_btn, today_btn = QPushButton("◀"), QPushButton("▶"), QPushButton("Danas")
        self.date_edit = QDateEdit(QDate.currentDate())
        self.date_edit.setCalendarPopup(True)
        self.date_edit.setDisplayFormat("dd.MM.yyyy.")
        self.date_edit.dateChanged.connect(self.refresh_day)
        prev_btn.clicked.connect(lambda: self.date_edit.setDate(self.date_edit.date().addDays(-1)))
        next_btn.clicked.connect(lambda: self.date_edit.setDate(self.date_edit.date().addDays(1)))
        today_btn.clicked.connect(lambda: self.date_edit.setDate(QDate.currentDate()))
        date_row = QHBoxLayout()
        for w in (prev_btn, self.date_edit, next_btn, today_btn):
            date_row.addWidget(w)
        date_row.addStretch()

        self.table = QTableWidget(0, 6)
        self.table.setHorizontalHeaderLabels(
            ["Namirnica", "Gram", "kcal", "Proteini", "Ugljeni h.", "Masti"])
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)

        remove_btn = QPushButton("Ukloni izabrano")
        remove_btn.clicked.connect(self.remove_selected)

        self.totals_label = QLabel()
        self.totals_label.setStyleSheet("font-size: 15px; font-weight: bold;")
        self.goal = QSpinBox()
        self.goal.setRange(500, 10000)
        self.goal.setSingleStep(50)
        self.goal.setSuffix(" kcal")
        self.goal.setValue(int(self.store.diary["goal"]))
        self.goal.valueChanged.connect(self.goal_changed)
        self.progress = QProgressBar()
        goal_row = QHBoxLayout()
        goal_row.addWidget(QLabel("Dnevni cilj:"))
        goal_row.addWidget(self.goal)
        goal_row.addWidget(self.progress, 1)

        right_box = QGroupBox("Dnevni unos")
        right = QVBoxLayout(right_box)
        right.addLayout(date_row)
        right.addWidget(self.table)
        right.addWidget(remove_btn, alignment=Qt.AlignRight)
        right.addWidget(self.totals_label)
        right.addLayout(goal_row)

        page = QWidget()
        lay = QHBoxLayout(page)
        lay.addWidget(left_box, 4)
        lay.addWidget(right_box, 5)
        return page

    def _build_history_tab(self) -> QWidget:
        self.history = QTableWidget(0, 5)
        self.history.setHorizontalHeaderLabels(
            ["Datum", "kcal", "Proteini (g)", "Ugljeni h. (g)", "Masti (g)"])
        self.history.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.history.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.history.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.history.cellDoubleClicked.connect(self.open_day_from_history)
        page = QWidget()
        lay = QVBoxLayout(page)
        lay.addWidget(QLabel("Dvoklik na dan otvara taj dan u dnevniku."))
        lay.addWidget(self.history)
        return page

    # ---- lista namirnica ----
    def populate_foods(self):
        query = norm(self.search.text().strip())
        self.food_list.clear()
        for f in sorted(self.store.foods, key=lambda x: norm(x.name)):
            if query and query not in norm(f.name):
                continue
            item = QListWidgetItem(
                food_icon(f),
                f"{f.name}\n{f.kcal:.0f} kcal/100g  ·  P {f.protein:g}  U {f.carbs:g}  M {f.fat:g}")
            item.setData(Qt.UserRole, f.id)
            self.food_list.addItem(item)
        if self.food_list.count():
            self.food_list.setCurrentRow(0)

    def selected_food(self) -> Food | None:
        item = self.food_list.currentItem()
        return self.store.food_by_id(item.data(Qt.UserRole)) if item else None

    def new_food(self):
        dlg = FoodDialog(self)
        if dlg.exec():
            self.store.foods.append(dlg.get_food())
            self.store.save_foods()
            self.search.clear()
            self.populate_foods()

    def edit_food(self):
        food = self.selected_food()
        if not food:
            return
        dlg = FoodDialog(self, food)
        if dlg.exec():
            dlg.get_food()
            self.store.save_foods()
            self.populate_foods()

    def delete_food(self):
        food = self.selected_food()
        if food and QMessageBox.question(
                self, "Brisanje", f"Obrisati „{food.name}“ iz liste namirnica?\n"
                "(Već uneti obroci u dnevniku ostaju.)") == QMessageBox.Yes:
            self.store.foods.remove(food)
            self.store.save_foods()
            self.populate_foods()

    # ---- dnevnik ----
    def current_day(self) -> str:
        return self.date_edit.date().toString("yyyy-MM-dd")

    def add_to_diary(self):
        food = self.selected_food()
        if not food:
            QMessageBox.information(self, "Info", "Prvo izaberi namirnicu.")
            return
        self.store.add_entry(self.current_day(), food, self.grams.value())
        self.refresh_day()
        self.refresh_history()

    def remove_selected(self):
        row = self.table.currentRow()
        if row >= 0:
            self.store.remove_entry(self.current_day(), row)
            self.refresh_day()
            self.refresh_history()

    def goal_changed(self, value):
        self.store.diary["goal"] = value
        self.store.save_diary()
        self.refresh_day()

    def refresh_day(self):
        entries = self.store.entries(self.current_day())
        self.table.setRowCount(len(entries))
        for r, e in enumerate(entries):
            values = [e["name"], f'{e["grams"]:g}', f'{e["kcal"]:g}',
                      f'{e["protein"]:g}', f'{e["carbs"]:g}', f'{e["fat"]:g}']
            for c, v in enumerate(values):
                item = QTableWidgetItem(v)
                if c:
                    item.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
                self.table.setItem(r, c, item)
        t = self.store.totals(entries)
        self.totals_label.setText(
            f'Ukupno: {t["kcal"]:g} kcal   |   P {t["protein"]:g} g   '
            f'U {t["carbs"]:g} g   M {t["fat"]:g} g')
        goal = self.goal.value()
        self.progress.setMaximum(goal)
        self.progress.setValue(int(min(t["kcal"], goal)))
        self.progress.setFormat(f'{t["kcal"]:g} / {goal} kcal')
        over = t["kcal"] > goal
        self.progress.setStyleSheet("QProgressBar::chunk { background: #d9534f; }" if over else "")

    # ---- istorija ----
    def refresh_history(self):
        days = sorted(self.store.diary["days"].items(), reverse=True)
        self.history.setRowCount(len(days))
        for r, (day, entries) in enumerate(days):
            t = self.store.totals(entries)
            d = QDate.fromString(day, "yyyy-MM-dd").toString("dd.MM.yyyy.")
            for c, v in enumerate([d, f'{t["kcal"]:g}', f'{t["protein"]:g}',
                                   f'{t["carbs"]:g}', f'{t["fat"]:g}']):
                item = QTableWidgetItem(v)
                item.setData(Qt.UserRole, day)
                self.history.setItem(r, c, item)

    def open_day_from_history(self, row, _col):
        day = self.history.item(row, 0).data(Qt.UserRole)
        self.date_edit.setDate(QDate.fromString(day, "yyyy-MM-dd"))
        self.centralWidget().setCurrentIndex(0)


if __name__ == "__main__":
    app = QApplication(sys.argv)
    win = MainWindow()
    win.show()
    sys.exit(app.exec())
