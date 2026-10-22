from ui_language import tr
from pathlib import Path
from PySide6.QtWidgets import QWidget,QVBoxLayout,QLabel,QTableWidget,QTableWidgetItem,QHeaderView,QPushButton,QHBoxLayout,QComboBox,QFileDialog,QMessageBox,QCheckBox
from PySide6.QtCore import QUrl
from PySide6.QtGui import QDesktopServices
import book_sounds as sounds
import book_engine as books

class SoundPanel(QWidget):
    def __init__(self,host):
        super().__init__(host);self.host=host;self.loading=False
        layout=QVBoxLayout(self)
        description=QLabel(tr('Звуковые вставки из разметки сохраняют своё место в книге. ИИ создаёт эффект по контексту; ручной файл, чтение автором или пропуск имеют приоритет.'))
        description.setWordWrap(True);layout.addWidget(description)
        self.generation_checkbox=QCheckBox(tr('Генерировать звуковые эффекты'))
        self.generation_checkbox.setToolTip(tr('Stable Audio 3 Medium на SSH-сервере. Использует те же веса, что и музыка; фон и эффекты включаются независимо.'))
        self.generation_checkbox.toggled.connect(self.save_generation)
        layout.addWidget(self.generation_checkbox)
        self.table=QTableWidget(0,4);self.table.setHorizontalHeaderLabels([tr('Звук / главы'),tr('Источник звука'),tr('Аудиофайл'),tr('Без файла')])
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.table.verticalHeader().setDefaultSectionSize(72);layout.addWidget(self.table)
    def refresh(self):
        self.table.setRowCount(0)
        bid=self.host.book_id
        self.loading=True
        self.generation_checkbox.setChecked(bool(bid and books.metadata(bid).get('sound_generation_enabled',False)))
        self.loading=False
        self.update_generation_controls()
        if not bid:return
        meta=books.metadata(bid)
        for item in sounds.entries(bid):
            row=self.table.rowCount();self.table.insertRow(row)
            self.table.setItem(row,0,QTableWidgetItem(item['text']+(' · ' + f"{item['count']}" + tr(' раз\nГлавы: '))+', '.join(map(str,sorted(item['chapters'])))))
            self.table.setItem(row,1,QTableWidgetItem((item['description'] or tr('Источник не указан'))+(tr('\nРаньше назначены разные настройки — выберите общие.') if item.get('conflict') else '')))
            choice=dict(item['choice'])
            generated=item.get('generated_file','')
            preview=choice.get('file') or generated
            self.table.item(row,0).setToolTip(tr('Варианты: ')+', '.join(sorted(item['variants'])))
            box=QWidget();audio=QVBoxLayout(box);audio.setContentsMargins(0,0,0,0);audio.setSpacing(2)
            line=QHBoxLayout();audio.addLayout(line)
            pick=QPushButton(Path(choice['file']).name[:16] if choice.get('file') else tr('Загрузить…'));pick.setToolTip(choice.get('file',''))
            pick.clicked.connect(lambda checked=False,i=item['id'],c=choice:self.pick(i,c));line.addWidget(pick)
            play=QPushButton('▷');play.setEnabled(bool(preview));play.clicked.connect(lambda checked=False,path=preview:QDesktopServices.openUrl(QUrl.fromLocalFile(path)));line.addWidget(play)
            clear=QPushButton('×');clear.setEnabled(bool(choice.get('file')));clear.setToolTip(tr('Убрать ручной файл; звук ИИ остаётся в кэше.'));clear.clicked.connect(lambda checked=False,i=item['id'],c=choice:self.change(i,dict(c,file='')));line.addWidget(clear)
            if generated:
                ready=QLabel(tr('Звук ИИ готов'));ready.setToolTip(str(generated));audio.addWidget(ready)
            self.table.setCellWidget(row,2,box)
            fallback=QComboBox();fallback.addItem(tr('Автоматически (ИИ / автор)'),'auto');fallback.addItem(tr('Читать автором'),'narrator');fallback.addItem(tr('Пропустить'),'skip');fallback.setCurrentIndex(max(0,fallback.findData(choice.get('fallback','auto'))))
            fallback.setToolTip(tr('ИИ при включённой генерации; иначе читает автор. Ручной файл всегда имеет приоритет.'))
            fallback.currentIndexChanged.connect(lambda _,i=item['id'],c=choice,w=fallback:self.change(i,dict(c,fallback=w.currentData())))
            self.table.setCellWidget(row,3,fallback)
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
    def update_generation_controls(self):
        import tts_settings
        remote=tts_settings.settings()['mode']=='remote'
        self.generation_checkbox.setEnabled(bool(self.host.book_id) and not self.host.running and
                                            (remote or self.generation_checkbox.isChecked()))
        if not remote and self.generation_checkbox.isChecked():
            self.generation_checkbox.setToolTip(tr('Для локальной озвучки снимите галочку. Генерация эффектов доступна на SSH-сервере.'))
        else:
            self.generation_checkbox.setToolTip(tr('Stable Audio 3 Medium на SSH-сервере. Использует те же веса, что и музыка; фон и эффекты включаются независимо.'))
    def save_generation(self,enabled):
        if self.loading or self.host.running or not self.host.book_id:return
        import book_state as state
        meta=books.metadata(self.host.book_id)
        if bool(meta.get('sound_generation_enabled',False))!=enabled:
            meta['sound_generation_enabled']=enabled;meta.update(output='',render_complete=False)
            books.save_meta(self.host.book_id,meta)
            with books.connect(self.host.book_id) as db:db.execute("UPDATE chapters SET output=''")
            state.snapshot(self.host.book_id)
        self.refresh();self.host.set_running(False);self.host.refresh_shelf()
    def change(self,ident,choice):
        if self.host.running:return
        try:sounds.save(self.host.book_id,ident,choice);self.refresh()
        except Exception as exc:QMessageBox.warning(self,tr('Звуки'),str(exc))
    def pick(self,ident,choice):
        if self.host.running:return
        path,_=QFileDialog.getOpenFileName(self,tr('Выберите звук'),'',tr('Аудио (*.wav *.mp3 *.flac *.ogg *.m4a);;Все файлы (*)'))
        if not path:return
        try:self.change(ident,dict(choice,file=sounds.import_audio(self.host.book_id,path)))
        except Exception as exc:QMessageBox.warning(self,tr('Звуки'),str(exc))
