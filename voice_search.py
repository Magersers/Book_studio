"""Searchable voice picker retaining stable avatar IDs and inheritance entry."""
from ui_language import tr
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QDialog,QVBoxLayout,QLineEdit,QListWidget,QListWidgetItem,QDialogButtonBox,QLabel

def choose(combo):
    dialog=QDialog(combo);dialog.setWindowTitle(tr('Выбрать голос'));dialog.resize(530,470)
    layout=QVBoxLayout(dialog);layout.addWidget(QLabel(tr('Поиск по имени аватара или папке')))
    search=QLineEdit();search.setPlaceholderText(tr('Например: Дети, Сергей…'));search.setClearButtonEnabled(True);layout.addWidget(search)
    voices=QListWidget();layout.addWidget(voices)
    entries=[(combo.itemText(i),combo.itemData(i)) for i in range(combo.count())]
    def refresh(query=''):
        voices.clear();selected=None
        for label,aid in entries:
            if query.casefold().strip() not in label.casefold():continue
            item=QListWidgetItem(label);item.setData(Qt.ItemDataRole.UserRole,aid);voices.addItem(item)
            if aid==combo.currentData():selected=item
        if selected:voices.setCurrentItem(selected)
        elif voices.count():voices.setCurrentRow(0)
        buttons.button(QDialogButtonBox.StandardButton.Ok).setEnabled(voices.count()>0)
    buttons=QDialogButtonBox(QDialogButtonBox.StandardButton.Ok|QDialogButtonBox.StandardButton.Cancel)
    buttons.button(QDialogButtonBox.StandardButton.Ok).setText(tr('Выбрать'));buttons.button(QDialogButtonBox.StandardButton.Cancel).setText(tr('Отмена'))
    buttons.accepted.connect(dialog.accept);buttons.rejected.connect(dialog.reject);layout.addWidget(buttons)
    search.textChanged.connect(refresh);voices.itemDoubleClicked.connect(lambda *_:dialog.accept());refresh();search.setFocus()
    if dialog.exec() and voices.currentItem():return voices.currentItem().data(Qt.ItemDataRole.UserRole)
    return None
