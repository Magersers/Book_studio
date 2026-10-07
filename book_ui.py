"""Audiobook library, cast mapping and paged editable fragment queue."""
from ui_language import tr
import shutil,json
import uuid
from pathlib import Path
from PySide6.QtCore import Qt,QUrl,QTimer,QSize
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (QDialog,QVBoxLayout,QHBoxLayout,QLabel,QPushButton,QComboBox,QListWidget,QTableWidget,QTableWidgetItem,QHeaderView,QFileDialog,QMessageBox,QInputDialog,QSpinBox,QTextEdit,QApplication,QProgressBar,QListWidgetItem)
import avatar_store as store
import book_engine as books
import book_state as state
from book_import import FORMATS

class BookDialog(QDialog):
    def __init__(self,parent):
        super().__init__(parent); self.host=parent; self.book_id=None; self.chapter_id=None; self.offset=0; self.running=False; self.loading=False; self.paused=False; self.wait_dialog=None; self.closing_target=None; self.allow_close=False
        self.setWindowTitle(tr('Vox Studio · Аудиокниги'))
        from book_design import build
        build(self)
        self.refresh_provider()
        self.refresh_library(); self.set_running(False)
        self.shelf_timer=QTimer(self); self.shelf_timer.setInterval(1200); self.shelf_timer.timeout.connect(self.refresh_shelf); self.shelf_timer.start()
        from book_menus import install
        install(self)
    def voice_combo(self,selected=''):
        from book_design import VoicePicker
        return VoicePicker(selected)
    def refresh_provider(self):
        import analysis_settings
        self.provider_label.setText(analysis_settings.label())
    def configure_analysis(self):
        if self.running:return
        from analysis_settings_ui import AnalysisSettingsDialog
        if AnalysisSettingsDialog(self).exec():
            self.refresh_provider()
            if hasattr(self.host,'refresh_analysis_provider'):self.host.refresh_analysis_provider()
    def analysis_ready(self):
        import analysis_settings
        try:analysis_settings.ready();return True
        except Exception:
            self.configure_analysis()
            try:analysis_settings.ready();return True
            except Exception:return False
    def refresh_library(self,selected=None):
        self.library.blockSignals(True); self.library.clear()
        for meta in books.library():
            if meta.get('status')=='ready': self.library.addItem(meta['title'],meta['id'])
        if selected: self.library.setCurrentIndex(max(0,self.library.findData(selected)))
        self.library.blockSignals(False); self.select_book(); self.refresh_shelf()
    def select_book(self,*args):
        self.book_id=self.library.currentData(); self.loading=True
        self.chapters.clear(); self.chapter_rows=[]
        if self.book_id:
            state.migrate(self.book_id)
            state.refresh_audio(self.book_id)
            meta=books.metadata(self.book_id)
            # Recognize an author row added manually in older versions.
            if not meta.get('default_avatar'):
                with books.connect(self.book_id) as db:
                    author=next((r for r in db.execute("SELECT name,avatar FROM characters WHERE avatar!=''") if r['name'].strip().casefold() in ('автор','рассказчик','narrator')),None)
                if author:meta=state.update(self.book_id,default_avatar=author['avatar'])
            self.default_voice.reload(meta.get('default_avatar','')); self.pause.setValue(meta.get('pause_ms',180)); self.book_mode.setCurrentIndex(max(0,self.book_mode.findData(meta.get('voice_mode','roles'))))
            with books.connect(self.book_id) as db: self.chapter_rows=[dict(r) for r in db.execute('SELECT * FROM chapters ORDER BY id')]
            for row in self.chapter_rows: self.chapters.addItem(f'{row["id"]}. {row["title"]}')
            self.note.setText((f"{meta['chapters']}" + tr(' глав · ') + f"{meta['segments']}" + tr(' фрагментов. '))+ ' '.join(meta.get('warnings',[])))
            if not meta.get('analysis_complete'):
                self.note.setText(self.note.text()+tr(' Нажмите «Разметить книгу», чтобы подготовить роли.'))
            elif not meta.get('roles_model','').endswith('v16-portraits'):
                self.note.setText(self.note.text()+tr(' Категории и портреты дополняются при разметке новых глав. Для всей старой книги нужна новая разметка.'))
        self.loading=False; self.sounds.refresh(); self.refresh_cast(); self.chapters.setCurrentRow(0); self.set_running(self.running)
        if not self.book_id:
            self.chapter_id=None;self.refresh_segments();self.default_voice.reload('');self.note.setText(tr('Добавьте книгу или восстановите её из корзины через правую кнопку.'));self.status.setText(tr('Библиотека пуста.'));self.progress.setValue(0)
        if self.book_id:
            meta=books.metadata(self.book_id); self.status.setText(self.summary(meta))
            self.progress.setRange(0,1000); self.progress.setValue(round(meta.get('render_percent',0)*10 if meta.get('stage')=='render' else meta.get('analysis_percent',0)*10)); self.progress.show()
    def save_defaults(self,*args):
        if self.loading or not self.book_id: return
        meta=books.metadata(self.book_id); changed=meta.get('default_avatar','')!=self.default_voice.currentData() or meta.get('voice_mode','roles')!=self.book_mode.currentData()
        meta.update(default_avatar=self.default_voice.currentData(),pause_ms=self.pause.value(),voice_mode=self.book_mode.currentData()); books.save_meta(self.book_id,meta)
        if changed:state.invalidate(self.book_id)
        state.snapshot(self.book_id); self.set_running(self.running); self.refresh_shelf()
    def select_chapter(self,index):
        self.chapter_id=self.chapter_rows[index]['id'] if 0<=index<len(self.chapter_rows) else None; self.offset=0
        self.loading=True
        if self.chapter_id:
            row=self.chapter_rows[index]; self.chapter_voice.reload(row['avatar']); self.mode.setCurrentIndex(max(0,self.mode.findData(row['mode'])))
        self.loading=False; self.refresh_segments()
    def save_chapter(self,*args):
        if self.loading or not self.chapter_id: return
        with books.connect(self.book_id) as db: db.execute('UPDATE chapters SET avatar=?,mode=? WHERE id=?',(self.chapter_voice.currentData(),self.mode.currentData(),self.chapter_id))
        row=self.chapter_rows[self.chapters.currentRow()]; row.update(avatar=self.chapter_voice.currentData(),mode=self.mode.currentData()); state.invalidate(self.book_id,self.chapter_id); state.snapshot(self.book_id,self.chapter_id)
    def refresh_cast(self):
        self.cast.setRowCount(0); self.speaker.clear(); self.speaker.addItem(tr('Рассказчик'),'')
        if not self.book_id:return
        from book_cast import CATEGORIES,counts
        with books.connect(self.book_id) as db:
            counts(db)
            rows=db.execute('SELECT * FROM characters ORDER BY mentions DESC,name').fetchall()
            groups={r['id']:r['avatar'] for r in db.execute('SELECT * FROM cast_categories')}
        rows=[r for r in rows if r['mentions'] or r['name'].strip().casefold() not in ('автор','рассказчик','narrator')]
        self.cast.setMinimumHeight(110)
        for category,title in CATEGORIES.items():
            members=[r for r in rows if r['category']==category]
            i=self.cast.rowCount();self.cast.insertRow(i)
            item=QTableWidgetItem(f'{tr(title)} · {len(members)}');item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable);item.setData(Qt.ItemDataRole.UserRole,None);self.cast.setItem(i,0,item)
            item.setData(Qt.ItemDataRole.UserRole+1,category)
            font=item.font();font.setBold(True);item.setFont(font)
            combo=self.voice_combo(groups.get(category,''));combo.placeholder=tr('Голос автора');combo.reload(groups.get(category,''))
            combo.currentIndexChanged.connect(lambda _,cat=category,c=combo:self.set_group_voice(cat,c.currentData()));self.cast.setCellWidget(i,1,combo)
            self.cast.setItem(i,2,QTableWidgetItem(tr('Общий голос группы')))
            for row in members:
                self.add_cast_row(row,CATEGORIES)
    def add_cast_row(self,row,categories):
        i=self.cast.rowCount(); self.cast.insertRow(i); item=QTableWidgetItem(f'{row["name"]} ({row["mentions"]})'); item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable); self.cast.setItem(i,0,item)
        item.setData(Qt.ItemDataRole.UserRole,row['name'])
        from character_portrait import read,describe
        item.setToolTip(row['category_reason']+'\n\n'+describe(read(row['portrait']))+tr('\n\nДвойной щелчок — портрет и заметки'))
        combo=self.voice_combo(row['avatar']);combo.placeholder=tr('Голос категории');combo.reload(row['avatar']); combo.currentIndexChanged.connect(lambda _,name=row['name'],c=combo:self.set_cast_voice(name,c.currentData())); self.cast.setCellWidget(i,1,combo); self.speaker.addItem(row['name'],row['name'])
        combo.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu);combo.customContextMenuRequested.connect(lambda pos,c=combo:self.cast_context_menu(c.mapTo(self.cast.viewport(),pos)))
        category=QComboBox()
        for key,title in categories.items():category.addItem(tr(title),key)
        category.setCurrentIndex(max(0,category.findData(row['category'])))
        category.currentIndexChanged.connect(lambda _,name=row['name'],c=category:self.set_category(name,c.currentData()))
        self.cast.setCellWidget(i,2,category)
    def cast_changed(self):
        state.refresh_audio(self.book_id);state.snapshot(self.book_id,output='',render_complete=False)
    def show_portrait(self,row=None,column=0):
        if self.running:return
        row=self.cast.currentRow() if row is None or isinstance(row,bool) else row
        item=self.cast.item(row,0) if row>=0 else None
        name=item.data(Qt.ItemDataRole.UserRole) if item else None
        if not name:
            QMessageBox.information(self,tr('Портрет персонажа'),tr('Выберите строку персонажа, а не название категории.'));return
        from character_portrait_ui import show
        show(self,name)
    def set_category(self,name,category):
        with books.connect(self.book_id) as db:db.execute('UPDATE characters SET category=?,category_manual=1 WHERE name=?',(category,name))
        self.cast_changed();QTimer.singleShot(0,self.refresh_cast)
    def set_group_voice(self,category,avatar):
        with books.connect(self.book_id) as db:db.execute('UPDATE cast_categories SET avatar=? WHERE id=?',(avatar,category))
        self.cast_changed()
    def set_cast_voice(self,name,avatar):
        with books.connect(self.book_id) as db: db.execute('UPDATE characters SET avatar=? WHERE name=?',(avatar,name))
        self.cast_changed()
    def new_character(self):
        name,ok=QInputDialog.getText(self,tr('Новый персонаж'),tr('Имя персонажа'))
        if ok and name.strip():
            if name.strip().casefold() in ('автор','рассказчик','narrator'):
                self.default_voice.setFocus();self.default_voice.showPopup();return
            with books.connect(self.book_id) as db: db.execute('INSERT OR IGNORE INTO characters(name) VALUES(?)',(name.strip()[:100],))
            self.refresh_cast()
    def refresh_segments(self):
        self.segments.setRowCount(0); self.segment_rows=[]
        count=books.metadata(self.book_id).get('audio_review_count',0) if self.book_id else 0
        role_count=books.metadata(self.book_id).get('role_review_count',0) if self.book_id else 0
        self.tabs.setTabText(1,tr('Текст и разметка')+((tr(' · роли: ') + f'{role_count}') if role_count else '')+((tr(' · звук: ') + f'{count}') if count else ''))
        self.segments.setColumnWidth(2,135)
        if not self.chapter_id:return
        with books.connect(self.book_id) as db:
            self.total=db.execute('SELECT count(*) FROM segments WHERE chapter=?',(self.chapter_id,)).fetchone()[0]
            self.segment_rows=[dict(r) for r in db.execute('SELECT * FROM segments WHERE chapter=? ORDER BY id LIMIT 60 OFFSET ?',(self.chapter_id,self.offset))]
        for row in self.segment_rows:
            i=self.segments.rowCount(); self.segments.insertRow(i)
            parts=json.loads(row.get('parts','[]'))
            labels={'toc':tr('Пропуск: оглавление'),'bibliography':tr('Пропуск: источники'),'credits':tr('Пропуск: выходные сведения'),'book_title':tr('Название книги · в начале')}
            speakers=' → '.join(labels.get(p.get('kind'),p['speaker'] or tr(tr('Автор'))) for p in parts) if parts else row['speaker'] or tr(tr('Автор'))
            check=tr('Проверить звук / пропуск') if row.get('audio_review') and row.get('signature') else (tr('Проверить роль') if row['review'] else '—')
            for j,text in enumerate([row['text'],speakers,check]): self.segments.setItem(i,j,QTableWidgetItem(text))
            self.segments.item(i,2).setToolTip(row.get('review_reason') or check)
            self.segments.item(i,1).setToolTip('\n'.join(f'{p["speaker"] or "Автор"}: {p["text"]}' for p in parts) or tr('Для выделения авторских вставок повторите разметку ролей.'))
        self.page_label.setText(f'{self.offset+1}–{min(self.offset+60,self.total)} / {self.total}'); self.prev.setEnabled(self.offset>0); self.next.setEnabled(self.offset+60<self.total)
    def page(self,direction):
        self.offset=max(0,self.offset+60*direction); self.refresh_segments()
    def assign_speaker(self):
        selected={item.row() for item in self.segments.selectedItems()}
        with books.connect(self.book_id) as db:
            for index in selected:
                record=self.segment_rows[index]; parts=json.loads(record.get('parts','[]'))
                from roles_text import reassign_parts
                parts=reassign_parts(parts,record['text'],self.speaker.currentData())
                db.execute("UPDATE segments SET speaker=?,review=0,review_reason='',manual=1,parts=?,wav='',signature='' WHERE id=?",(self.speaker.currentData(),json.dumps(parts,ensure_ascii=False),record['id']))
            if selected:db.execute("UPDATE chapters SET output='' WHERE id=?",(self.chapter_id,))
        if selected:state.update(self.book_id,output='',render_complete=False)
        state.snapshot(self.book_id,self.chapter_id)
        self.refresh_segments()
    def edit_text(self,row,column):
        if self.running:return
        record=self.segment_rows[row]; value,ok=QInputDialog.getMultiLineText(self,tr('Текст фрагмента'),tr('До 500 символов. Исправьте переносы или ошибки распознавания.'),record['text'])
        if ok and value.strip():
            if len(value)>500: QMessageBox.warning(self,tr('Слишком длинный фрагмент'),tr('Оставьте не более 500 символов.')); return
            with books.connect(self.book_id) as db: db.execute("UPDATE segments SET text=?,parts='[]' WHERE id=?",(value.strip(),record['id']))
            state.invalidate(self.book_id,self.chapter_id,analysis=True); self.refresh_segments(); self.set_running(False)
    def set_running(self,value):
        self.sounds.setEnabled(not value and bool(self.book_id))
        self.running=value
        self.analysis_settings_button.setEnabled(not value)
        self.portrait_button.setEnabled(not value and bool(self.book_id))
        if not value:self.paused=False
        self.progress.setVisible(bool(self.book_id))
        for widget in [self.library,self.shelf,self.import_button,self.append_button,self.default_voice,self.book_mode,self.pause,self.chapters,self.chapter_voice,self.mode,self.cast,self.add_character,self.analyze_button,self.assign,self.render_all,self.render_chapter,self.export_button]:
            widget.setEnabled(not value and (bool(self.book_id) or widget in (self.import_button,self.library,self.shelf)))
        complete=bool(self.book_id and books.metadata(self.book_id).get('analysis_complete'))
        self.restart_button.setEnabled(not value and complete); self.render_all.setEnabled(not value and complete); self.render_chapter.setEnabled(not value and complete)
        self.render_all.setToolTip(tr('Сначала завершите разметку книги до 100%.') if not complete else tr('Продолжить с сохранённого фрагмента'))
        if self.book_mode.currentData()=='single':
            self.cast.setEnabled(False);self.chapter_voice.setEnabled(False);self.mode.setEnabled(False)
        self.pause_button.setEnabled(value);self.pause_button.setText(tr('Продолжить') if self.paused else tr('Пауза'))
        self.stop_button.setEnabled(True)
        self.listen_ready.setEnabled(bool(self.book_id) and (not value or self.paused))
    def start(self,action,**kwargs):
        if not self.host.ready:return
        if action in ('book_analyze','book_import','book_append') and not self.analysis_ready():return
        self.action=action;self.paused=False
        (books.folder(self.book_id)/'pause').unlink(missing_ok=True)
        state.control(self.book_id,'run')
        self.set_running(True); self.host.set_busy(True)
        self.host.backend.send(dict(action=action,book_id=self.book_id,**kwargs))
    def import_file(self):
        if not self.analysis_ready():return
        path,_=QFileDialog.getOpenFileName(self,tr('Открыть книгу'),'',(tr('Книги (') + f'{FORMATS}' + tr(');;Все файлы (*)')))
        if path:
            self.book_id=uuid.uuid4().hex; books.folder(self.book_id).mkdir(parents=True); self.start('book_import',path=path)
    def analyze(self): self.start('book_analyze')
    def append_book(self):
        if self.running or not self.book_id:return
        kind,ok=QInputDialog.getItem(self,tr('Дополнить книгу'),tr('Добавить новые главы:'),[tr('Из файла'),tr('Вставить текст')],0,False)
        if not ok:return
        if kind==tr('Из файла'):
            path,_=QFileDialog.getOpenFileName(self,tr('Добавить главы'),'',(tr('Книги (') + f'{FORMATS}' + tr(');;Все файлы (*)')))
        else:
            text,ok=QInputDialog.getMultiLineText(self,tr('Новые главы'),tr('Вставьте текст с названиями глав. Существующие главы и голоса сохранятся.'))
            if not ok or not text.strip():return
            path=books.folder(self.book_id)/'imports'/f'{uuid.uuid4().hex}.txt';path.parent.mkdir(exist_ok=True)
            path.write_text(text,encoding='utf-8');path=str(path)
        if path:self.start('book_append',path=path)
    def restart_render(self):
        choice,ok=QInputDialog.getItem(self,tr('Озвучить заново'),tr('Что пересоздать?'),[tr('Выбранную главу'),tr('Всю книгу')],0,False)
        if ok:self.render(choice==tr('Выбранную главу'),restart=True)
    def render(self,chapter_only,restart=False):
        if self.running or not self.host.ready:return
        if chapter_only and self.chapter_id is None:return
        available={a['id'] for a in store.avatars()}
        if not self.book_id:return
        meta=books.metadata(self.book_id)
        if meta.get('default_avatar') not in available:
            QMessageBox.information(self,tr('Выберите автора'),tr('В блоке «Автор / рассказчик» выберите доступный аватар. Автор читает заголовки и повествование в каждой книге.'));self.default_voice.setFocus();self.default_voice.showPopup();return
        if not meta.get('analysis_complete'):
            QMessageBox.information(self,tr('Озвучка'),tr('Сначала завершите разметку книги.'));return
        if restart:
            scope=tr('выбранную главу') if chapter_only else tr('всю книгу')
            if QMessageBox.question(self,tr('Озвучить заново?'),(tr('Пересоздать ') + f'{scope}' + tr(' с начала? Разметка, голоса и звуки сохранятся. Готовые фрагменты выбранного объёма будут озвучены повторно.')),QMessageBox.StandardButton.Yes|QMessageBox.StandardButton.No,QMessageBox.StandardButton.No)!=QMessageBox.StandardButton.Yes:return
            try:state.restart_audio(self.book_id,self.chapter_id if chapter_only else None)
            except (OSError,ValueError) as exc:QMessageBox.warning(self,tr('Не удалось начать заново'),str(exc));return
        self.start('book_render',chapter_id=self.chapter_id if chapter_only else None)
    def toggle_pause(self):
        if not self.running:return
        state.control(self.book_id,'run' if self.paused else 'pause')
        self.status.setText(tr('Продолжаем…') if self.paused else tr('Сохраняем текущий фрагмент перед паузой…'))
        self.pause_button.setEnabled(False)
    def stop(self):
        self.request_stop()
    def request_stop(self,close_app=False,close_dialog=False,confirm=True):
        if self.wait_dialog:
            self.wait_dialog.raise_();return
        if confirm and QMessageBox.question(self,tr('Остановить работу?'), tr('Завершить текущую главу, сохранить прогресс и выгрузить модель из памяти?'),QMessageBox.StandardButton.Yes|QMessageBox.StandardButton.No,QMessageBox.StandardButton.No)!=QMessageBox.StandardButton.Yes:return
        self.closing_target='app' if close_app else ('dialog' if close_dialog else None)
        if not self.running:
            self.host.backend.send(dict(action='unload'));return
        self.was_paused=self.paused
        state.control(self.book_id,'stop')
        self.wait_dialog=QDialog(self);self.wait_dialog.setWindowTitle(tr('Сохраняем текущую главу'));self.wait_dialog.setModal(True);self.wait_dialog.resize(570,230)
        box=QVBoxLayout(self.wait_dialog)
        meta=books.metadata(self.book_id)
        api_analysis=meta.get('stage')=='analysis' and meta.get('roles_model','').startswith('deepseek-')
        waiting=(tr('Пожалуйста, подождите: завершим разметку текущей главы и сохраним данные.\n\nМожно завершить сейчас. Завершённые блоки API сохранятся. При продолжении будет заново отправлен только незавершённый блок; сервер мог уже начислить плату за прерванный запрос.') if api_analysis else tr('Пожалуйста, подождите: завершим текущую главу, сохраним данные и выгрузим модель.\n\nМожно завершить сейчас. Тогда незавершённую главу придётся разметить или озвучить заново; предыдущие главы сохранятся.'))
        label=QLabel(waiting);label.setWordWrap(True);box.addWidget(label)
        bar=QProgressBar();bar.setRange(0,0);box.addWidget(bar)
        row=QHBoxLayout();cancel=QPushButton(tr('Продолжить работу'));cancel.clicked.connect(self.cancel_wait);row.addWidget(cancel)
        force=QPushButton(tr('Закрыть сейчас') if close_app else tr('Остановить сейчас'));force.clicked.connect(self.force_stop);row.addWidget(force);box.addLayout(row)
        self.wait_dialog.rejected.connect(self.cancel_wait);self.wait_dialog.open()
    def cancel_wait(self):
        dialog=self.wait_dialog;self.wait_dialog=None;self.closing_target=None
        if self.running:state.control(self.book_id,'pause' if getattr(self,'was_paused',False) else 'run')
        if dialog:dialog.accept();dialog.deleteLater()
    def finish_wait(self):
        dialog=self.wait_dialog;self.wait_dialog=None
        if dialog:dialog.accept();dialog.deleteLater()
        target=self.closing_target;self.closing_target=None
        if target=='app':
            self.allow_close=True;self.host.force_close=True;QTimer.singleShot(0,self.host.close)
        elif target=='dialog':self.allow_close=True;self.done(0)
    def force_stop(self):
        self.host.backend.stop()
        if self.book_id:state.force_reset(self.book_id)
        self.set_running(False);self.host.set_busy(False);self.refresh_library(self.book_id)
        target=self.closing_target
        self.finish_wait()
        if target!='app':self.host.start_backend()
    def handle(self,event):
        kind=event['type']
        if kind in ('model_state','book_state') and self.book_id and self.library.findData(self.book_id)<0 and books.metadata(self.book_id).get('status')=='ready':
            self.refresh_library(self.book_id)
        if kind=='progress':
            self.status.setText(event['message']);self.progress.setRange(0,1000)
            meta=books.metadata(self.book_id) if self.book_id else {}
            saved=meta.get('render_percent',0) if meta.get('stage')=='render' else meta.get('analysis_percent',0)
            value=saved/100 if event.get('phase')=='loading' else max(saved/100,event.get('value',0))
            self.progress.setValue(int(value*1000))
        if kind=='book_state':
            self.paused=event.get('job_status')=='paused'
            self.pause_button.setEnabled(True);self.pause_button.setText(tr('Продолжить') if self.paused else tr('Пауза'))
            self.listen_ready.setEnabled(self.paused)
            if self.paused:
                meta=books.metadata(self.book_id)
                api_analysis=meta.get('stage')=='analysis' and meta.get('roles_model','').startswith('deepseek-')
                self.status.setText(tr('На паузе. Прогресс сохранён; новые запросы API не отправляются. Можно слушать готовую часть.') if api_analysis else tr('На паузе. Прогресс сохранён; модель остаётся в памяти. Можно слушать готовую часть.'))
            self.refresh_shelf()
            meta=books.metadata(self.book_id)
            self.progress.setValue(round(10*meta.get('render_percent' if meta.get('stage')=='render' else 'analysis_percent',0)))
        if kind in ('book_done','book_paused','book_stopped','models_unloaded','error','fatal'):
            if self.book_id and kind in ('error','fatal') and books.metadata(self.book_id).get('status')=='ready':state.snapshot(self.book_id,job_status='error')
            self.set_running(False); self.host.set_busy(False)
            self.refresh_library(self.book_id);self.status.setText(event.get('message',tr('Модели выгружены. Данные сохранены.')))
            self.finish_wait()
    def summary(self,meta):
        stages={'analysis':tr('Разметка'),'render':tr('Озвучка')}
        statuses={'running':tr('в работе'),'paused':tr('пауза'),'stopped':tr('остановлено'),'done':tr('готово'),'waiting_chapter':tr('завершаем главу'),'error':tr('ошибка')}
        return (f"{stages.get(meta.get('stage'), tr('Ожидает разметки'))}" + ' · ' + f"{statuses.get(meta.get('job_status'), tr('сохранено'))}" + tr('\nРазметка ') + f"{meta.get('analysis_percent', 100 if meta.get('analysis_complete') else 0):g}" + tr('% · Озвучка ') + f"{meta.get('render_percent', 0):g}" + '%')
    def refresh_shelf(self):
        if not hasattr(self,'shelf'):return
        self.shelf.blockSignals(True);self.shelf.clear()
        for meta in books.library():
            if meta.get('status')!='ready':continue
            item=QListWidgetItem(meta['title']+'\n'+self.summary(meta).replace(tr(' · Озвучка'),tr('\nОзвучка')));item.setData(Qt.ItemDataRole.UserRole,meta['id']);item.setSizeHint(QSize(205,108));self.shelf.addItem(item)
            if meta['id']==self.book_id:self.shelf.setCurrentItem(item)
        self.shelf.blockSignals(False)
    def shelf_select(self,current,previous=None):
        if current and not self.running:self.library.setCurrentIndex(self.library.findData(current.data(Qt.ItemDataRole.UserRole)))
    def preview_ready(self):
        from ready_player import ReadyPlayer
        paths=state.ready_audio(self.book_id)
        if not paths:paths=state.ready_audio(self.book_id,self.chapter_id)
        if not paths:self.status.setText(tr('Пока нет готовых фрагментов для прослушивания.'));return
        ReadyPlayer(self,paths,books.metadata(self.book_id).get('pause_ms',180)).exec()
    def play_chapter(self):
        if self.chapter_id:
            with books.connect(self.book_id) as db: row=db.execute('SELECT output FROM chapters WHERE id=?',(self.chapter_id,)).fetchone()
            if row and row['output'] and Path(row['output']).exists(): QDesktopServices.openUrl(QUrl.fromLocalFile(row['output']))
            else: self.status.setText(tr('Глава ещё не озвучена.'))
    def export(self,selected_chapter=False):
        if not self.book_id or self.running:return
        if selected_chapter:mode='chapter'
        else:
            options=[tr('Выбранная глава — MP3'),tr('Вся книга — один MP3'),tr('По главам — отдельные MP3 в ZIP')]
            choice,ok=QInputDialog.getItem(self,tr('Скачать аудиокнигу'),tr('Формат:'),options,0,False)
            if not ok:return
            mode=['chapter','full','chapters'][options.index(choice)]
        if mode=='chapter' and self.chapter_id is None:
            QMessageBox.information(self,tr('Экспорт главы'),tr('Выберите главу слева.'));return
        extension='.zip' if mode=='chapters' else '.mp3'
        from book_export import chapters,export
        try:rows=chapters(self.book_id,self.chapter_id) if mode=='chapter' else chapters(self.book_id)
        except ValueError as exc:QMessageBox.information(self,tr('Экспорт книги'),str(exc));return
        import re
        title=rows[0][1] if mode=='chapter' else books.metadata(self.book_id)['title']
        title=re.sub(r'[<>:"/\\|?*\x00-\x1f]',' ',title).strip(' .')[:120] or tr('Глава')
        target,_=QFileDialog.getSaveFileName(self,tr('Сохранить главу') if mode=='chapter' else tr('Сохранить аудиокнигу'),title+extension,'ZIP (*.zip)' if mode=='chapters' else 'MP3 (*.mp3)')
        if target:
            if not target.lower().endswith(extension):target+=extension
            try:
                export(self.book_id,target,mode,chapter_id=self.chapter_id if mode=='chapter' else None)
                self.status.setText(tr('Сохранено: ')+target)
            except (OSError,ValueError) as exc:QMessageBox.warning(self,tr('Не удалось сохранить'),str(exc))
    def done(self,result):
        if self.running and not self.allow_close:
            self.request_stop(close_dialog=True,confirm=False);return
        super().done(result)
