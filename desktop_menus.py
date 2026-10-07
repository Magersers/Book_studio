from ui_language import tr
from PySide6.QtCore import Qt,QUrl
from PySide6.QtWidgets import QMenu,QMessageBox,QApplication
import avatar_store as store

def install(w):
    def avatars(pos):
        item=w.avatar_list.itemAt(pos)
        menu=QMenu(w)
        if not item or not item.data(0,Qt.ItemDataRole.UserRole):
            w.avatar_list.folder_menu(menu,item);menu.exec(w.avatar_list.viewport().mapToGlobal(pos));return
        if not item.isSelected():w.avatar_list.setCurrentItem(item)
        menu.addAction(tr('Прослушать образец'),w.preview_reference).setEnabled(not w.busy)
        menu.addAction(tr('Редактировать аватар'),lambda:w.edit_avatar(True)).setEnabled(w.ready and not w.busy)
        menu.addAction(tr('Удалить из библиотеки'),w.archive_avatar).setEnabled(not w.busy)
        import avatar_folders
        sub=menu.addMenu(tr('Переместить в папку'));sub.setEnabled(not w.busy)
        sub.addAction(tr('Без папки'),lambda:w.avatar_list.move_selected(''))
        folder_paths=avatar_folders.paths()
        for folder in avatar_folders.load()['folders']:
            sub.addAction(folder_paths[folder['id']],lambda checked=False,fid=folder['id']:w.avatar_list.move_selected(fid))
        menu.addAction(tr('Создать папку'),lambda:w.avatar_list.new_folder()).setEnabled(not w.busy)
        menu.exec(w.avatar_list.viewport().mapToGlobal(pos))
    def history(pos):
        item=w.history_list.itemAt(pos)
        record=item.data(Qt.ItemDataRole.UserRole) if item else None
        if not record:return
        w.history_list.setCurrentItem(item);menu=QMenu(w)
        menu.addAction(tr('Прослушать'),w.player.play)
        menu.addAction(tr('Копировать текст'),lambda:QApplication.clipboard().setText(record['text']))
        menu.addAction(tr('Редактировать и озвучить заново'),lambda:w.editor.setPlainText(record['text'])).setEnabled(not w.busy)
        menu.addAction(tr('Экспорт MP3'),lambda:w.export('mp3'))
        def remove():
            if w.busy:return
            if QMessageBox.question(w,tr('Удалить запись?'),tr('Убрать запись из истории? Экспортированные файлы останутся.'),QMessageBox.StandardButton.Yes|QMessageBox.StandardButton.No,QMessageBox.StandardButton.No)!=QMessageBox.StandardButton.Yes:return
            store.atomic_json(store.DATA/'history.json',[r for r in store.history() if r['id']!=record['id']])
            w.player.stop();w.player.setSource(QUrl());w.current_record=None;w.refresh_history();w.update_controls()
        menu.addAction(tr('Удалить из истории'),remove).setEnabled(not w.busy)
        menu.exec(w.history_list.viewport().mapToGlobal(pos))
    for widget,callback in [(w.avatar_list,avatars),(w.history_list,history)]:
        widget.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu);widget.customContextMenuRequested.connect(callback)
