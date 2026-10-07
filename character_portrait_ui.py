from ui_language import tr
from PySide6.QtWidgets import QDialog,QVBoxLayout,QLabel,QTextEdit,QDialogButtonBox,QMessageBox
import book_engine as books
import book_state as state
from character_portrait import read,describe

def show(parent,name):
    with books.connect(parent.book_id) as db:row=db.execute('SELECT * FROM characters WHERE name=?',(name,)).fetchone()
    if not row:return
    dialog=QDialog(parent);dialog.setWindowTitle(tr('Портрет · ')+name);dialog.resize(650,650)
    layout=QVBoxLayout(dialog)
    title=QLabel(name);title.setStyleSheet('font-size:22px;font-weight:600;');layout.addWidget(title)
    label=QLabel(tr('Портрет по тексту книги · ИИ дополняет его при разметке'));label.setWordWrap(True);layout.addWidget(label)
    portrait=QTextEdit();portrait.setReadOnly(True);portrait.setPlainText(describe(read(row['portrait'])));layout.addWidget(portrait,3)
    label=QLabel(tr('Твои дополнения и исправления. Они передаются ИИ и не перезаписываются. Применяются при следующей разметке; готовое аудио не меняется.'));label.setWordWrap(True);layout.addWidget(label)
    notes=QTextEdit();notes.setPlaceholderText(tr('Например: Басен — младший брат Кейла. Спокоен и сдержан. Для голоса подойдёт молодой мужской аватар.'));notes.setPlainText(row['user_notes']);layout.addWidget(notes,2)
    buttons=QDialogButtonBox(QDialogButtonBox.StandardButton.Save|QDialogButtonBox.StandardButton.Cancel)
    buttons.button(QDialogButtonBox.StandardButton.Save).setText(tr('Сохранить заметки'));buttons.button(QDialogButtonBox.StandardButton.Cancel).setText(tr('Закрыть'))
    def accept():
        if len(notes.toPlainText())>1500:
            QMessageBox.information(dialog,tr('Слишком длинные заметки'),tr('Оставьте до 1500 символов, чтобы заметки помещались в контекст ИИ.'));return
        dialog.accept()
    buttons.accepted.connect(accept);buttons.rejected.connect(dialog.reject);layout.addWidget(buttons)
    if dialog.exec():
        with books.connect(parent.book_id) as db:db.execute('UPDATE characters SET user_notes=? WHERE name=?',(notes.toPlainText()[:1500],name))
        state.snapshot(parent.book_id);parent.refresh_cast()
