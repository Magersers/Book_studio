from ui_language import tr
from pathlib import Path
from PySide6.QtWidgets import QWidget,QVBoxLayout,QLabel,QTableWidget,QTableWidgetItem,QHeaderView,QPushButton,QHBoxLayout,QComboBox,QFileDialog,QMessageBox
from PySide6.QtCore import QUrl
from PySide6.QtGui import QDesktopServices
import book_sounds as sounds
import book_engine as books

class SoundPanel(QWidget):
    def __init__(self,host):
        super().__init__(host);self.host=host
        layout=QVBoxLayout(self)
        layout.addWidget(QLabel(tr('Звуковые вставки из разметки. Файл заменяет текст в его исходном месте.\nБез файла: чтение автором или пропуск. Описание помогает выбрать подходящий звук.')))
        self.table=QTableWidget(0,4);self.table.setHorizontalHeaderLabels([tr('Звук / главы'),tr('Источник звука'),tr('Аудиофайл'),tr('Без файла')])
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.table.verticalHeader().setDefaultSectionSize(72);layout.addWidget(self.table)
    def refresh(self):
        self.table.setRowCount(0)
        bid=self.host.book_id
        if not bid:return
        meta=books.metadata(bid)
        for item in sounds.entries(bid):
            row=self.table.rowCount();self.table.insertRow(row)
            self.table.setItem(row,0,QTableWidgetItem(item['text']+(' · ' + f"{item['count']}" + tr(' раз\nГлавы: '))+', '.join(map(str,sorted(item['chapters'])))))
            self.table.setItem(row,1,QTableWidgetItem((item['description'] or tr('Источник не указан'))+(tr('\nРаньше назначены разные настройки — выберите общие.') if item.get('conflict') else '')))
            choice=dict(item['choice'])
            self.table.item(row,0).setToolTip(tr('Варианты: ')+', '.join(sorted(item['variants'])))
            box=QWidget();line=QHBoxLayout(box);line.setContentsMargins(0,0,0,0)
            pick=QPushButton(Path(choice['file']).name[:16] if choice.get('file') else tr('Загрузить…'));pick.setToolTip(choice.get('file',''))
            pick.clicked.connect(lambda checked=False,i=item['id'],c=choice:self.pick(i,c));line.addWidget(pick)
            play=QPushButton('▷');play.setEnabled(bool(choice.get('file')));play.clicked.connect(lambda checked=False,c=choice:QDesktopServices.openUrl(QUrl.fromLocalFile(c['file'])));line.addWidget(play)
            clear=QPushButton('×');clear.clicked.connect(lambda checked=False,i=item['id'],c=choice:self.change(i,dict(c,file='')));line.addWidget(clear)
            self.table.setCellWidget(row,2,box)
            fallback=QComboBox();fallback.addItem(tr('Читать автором'),'narrator');fallback.addItem(tr('Пропустить'),'skip');fallback.setCurrentIndex(max(0,fallback.findData(choice.get('fallback','narrator'))))
            fallback.currentIndexChanged.connect(lambda _,i=item['id'],c=choice,w=fallback:self.change(i,dict(c,fallback=w.currentData())))
            self.table.setCellWidget(row,3,fallback)
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
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
