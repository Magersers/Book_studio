from ui_language import tr
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QMenu,QMessageBox,QInputDialog,QApplication
from pathlib import Path
import avatar_store as store
import book_engine as books
import book_edit as edit

def install(w):
    def submenu(menu,title):
        sub=QMenu(title,menu);menu.addMenu(sub)
        if not hasattr(menu,'_submenu_refs'):menu._submenu_refs=[]
        menu._submenu_refs.append(sub)
        return sub
    def run(fn):
        if w.running:return
        try:fn();w.refresh_library(w.book_id)
        except (ValueError,OSError) as exc:QMessageBox.warning(w,tr('Не удалось изменить'),str(exc))
    def confirm(title,text,fn):
        if QMessageBox.question(w,title,text,QMessageBox.StandardButton.Yes|QMessageBox.StandardButton.No,QMessageBox.StandardButton.No)==QMessageBox.StandardButton.Yes:run(fn)
    def rename(title,value,fn):
        value,ok=QInputDialog.getText(w,title,tr('Новое название:'),text=value)
        if ok and value.strip():run(lambda:fn(value.strip()))
    def voices(menu,fn,inherit=False,inherit_label=tr('Голос автора')):
        sub=submenu(menu,tr('Сменить рассказчика') if not inherit else tr('Назначить голос'))
        def search():
            from book_design import VoicePicker
            from voice_search import choose
            picker=VoicePicker(placeholder=inherit_label if inherit else tr('Выберите голос'))
            picker.setParent(w)
            if not inherit:picker.removeItem(0)
            selected=choose(picker);picker.deleteLater()
            if selected is not None:run(lambda:fn(selected))
        sub.addAction(tr('Поиск голоса…'),search)
        if inherit:sub.addAction(inherit_label,lambda:run(lambda:fn('')))
        from avatar_folders import labels
        folders=labels()
        for a in store.avatars():sub.addAction(a['name']+' · '+folders.get(a['id'],tr('Без папки')),lambda checked=False,aid=a['id']:run(lambda:fn(aid)))
        if not store.avatars():sub.addAction(tr('Сначала создайте аватар')).setEnabled(False)
    def set_author(aid):
        edit.editable(w.book_id);w.default_voice.reload(aid);w.save_defaults()
    def set_chapter_voice(aid):
        edit.editable(w.book_id);w.chapter_voice.reload(aid);w.save_chapter()
    def execute(menu,widget,pos):
        if not menu.actions():return
        w.shelf_timer.stop()
        try:menu.exec(widget.viewport().mapToGlobal(pos) if hasattr(widget,'viewport') else widget.mapToGlobal(pos))
        finally:w.shelf_timer.start()
    def shelf(pos):
        if w.running:return
        item=w.shelf.itemAt(pos);menu=QMenu(w)
        if item:
            w.shelf.setCurrentItem(item);bid=w.book_id;title=books.metadata(bid)['title']
            menu.addAction(tr('Переименовать книгу'),lambda:rename(tr('Название книги'),title,lambda name:edit.rename_book(bid,name)))
            menu.addAction(tr('Дополнить новыми главами'),w.append_book)
            menu.addAction(tr('Озвучить книгу заново'),lambda:w.render(False,restart=True))
            voices(menu,set_author);menu.addSeparator()
            menu.addAction(tr('Удалить книгу'),lambda:confirm(tr('Удалить книгу?'),('«' + f'{title}' + tr('» будет перемещена в корзину приложения. Исходный документ останется на месте.')),lambda:edit.delete_book(bid)))
        deleted=[m for m in books.library() if m.get('status')=='deleted']
        if deleted:
            sub=submenu(menu,tr('Восстановить из корзины'))
            for m in deleted:sub.addAction(m['title'],lambda checked=False,bid=m['id']:run(lambda:edit.restore_book(bid)))
        execute(menu,w.shelf,pos)
    def chapters(pos):
        if w.running:return
        item=w.chapters.itemAt(pos)
        if not item:return
        w.chapters.setCurrentItem(item);cid=w.chapter_id;bid=w.book_id;title=w.chapter_rows[w.chapters.currentRow()]['title'];menu=QMenu(w)
        menu.addAction(tr('Озвучить главу заново'),lambda:w.render(True,restart=True))
        menu.addAction(tr('Переименовать главу'),lambda:rename(tr('Название главы'),title,lambda name:edit.rename_chapter(bid,cid,name)))
        voices(menu,set_chapter_voice,True);menu.addAction(tr('Прослушать главу'),w.play_chapter);menu.addAction(tr('Скачать главу · MP3'),lambda:w.export(selected_chapter=True)).setEnabled(not w.running);menu.addSeparator()
        menu.addAction(tr('Удалить главу'),lambda:confirm(tr('Удалить главу?'),(tr('Удалить «') + f'{title}' + tr('» и её фрагменты из книги? Итоговый MP3 потребуется собрать заново.')),lambda:edit.delete_chapter(bid,cid)))
        execute(menu,w.chapters,pos)
    def cast(pos):
        if w.running:return
        row=w.cast.indexAt(pos).row()
        if row<0:return
        name=w.cast.item(row,0).data(Qt.ItemDataRole.UserRole);bid=w.book_id;menu=QMenu(w)
        if not name:
            category=w.cast.item(row,0).data(Qt.ItemDataRole.UserRole+1)
            if category:voices(menu,lambda aid:w.set_group_voice(category,aid),True);execute(menu,w.cast,pos)
            return
        menu.addAction(tr('Переименовать персонажа'),lambda:rename(tr('Имя персонажа'),name,lambda new:edit.character(bid,name,new)))
        menu.addAction(tr('Портрет и заметки'),lambda:w.show_portrait(row))
        voices(menu,lambda aid:w.set_cast_voice(name,aid),True,tr('Голос категории'))
        menu.addAction(tr('Удалить персонажа'),lambda:confirm(tr('Удалить персонажа?'),(tr('Удалить «') + f'{name}' + tr('»? Его реплики будет читать автор. Голосовой аватар останется в общей библиотеке.')),lambda:edit.character(bid,name)))
        execute(menu,w.cast,pos)
    def segments(pos):
        row=w.segments.indexAt(pos).row()
        if row<0:return
        w.segments.selectRow(row);record=w.segment_rows[row];bid=w.book_id;menu=QMenu(w)
        if record.get('wav') and Path(record['wav']).is_file():
            def listen():
                from ready_player import ReadyPlayer
                ReadyPlayer(w,[record['wav']],0).exec()
            menu.addAction(tr('Прослушать фрагмент'),listen)
            if record.get('audio_review') and not w.running:
                def reviewed():
                    import book_state
                    with books.connect(bid) as db:db.execute('UPDATE segments SET audio_review=0 WHERE id=?',(record['id'],))
                    book_state.snapshot(bid,record['chapter']);w.refresh_segments()
                menu.addAction(tr('Начало проверено — убрать пометку'),reviewed)
        menu.addAction(tr('Копировать текст'),lambda:QApplication.clipboard().setText(record['text']))
        if not w.running:
            menu.addAction(tr('Редактировать текст'),lambda:w.edit_text(row,0))
            sub=submenu(menu,tr('Назначить говорящего'))
            for i in range(w.speaker.count()):
                def assign(index=i):w.speaker.setCurrentIndex(index);w.assign_speaker()
                sub.addAction(w.speaker.itemText(i),lambda checked=False,index=i:assign(index))
            menu.addAction(tr('Удалить фрагмент'),lambda:confirm(tr('Удалить фрагмент?'),tr('Удалить выбранный текст из книги?'),lambda:edit.delete_segment(bid,record['id'])))
        execute(menu,w.segments,pos)
    def author(pos):
        if w.running or not w.book_id:return
        menu=QMenu(w);voices(menu,set_author);execute(menu,w.default_voice,pos)
    def chapter_voice(pos):
        if w.running or not w.chapter_id:return
        menu=QMenu(w);voices(menu,set_chapter_voice,True);execute(menu,w.chapter_voice,pos)
    for widget,callback in [(w.shelf,shelf),(w.chapters,chapters),(w.cast,cast),(w.segments,segments),(w.default_voice,author),(w.chapter_voice,chapter_voice)]:
        widget.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu);widget.customContextMenuRequested.connect(callback)
    w.cast_context_menu=cast
