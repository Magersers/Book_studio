"""Audiobook studio presentation, separate from durable workflow controls."""
from ui_language import tr
from PySide6.QtCore import Qt
from pathlib import Path
from PySide6.QtWidgets import (QApplication,QFrame,QLabel,QPushButton,QComboBox,QListWidget,QTableWidget,QHeaderView,QSpinBox,QProgressBar,QHBoxLayout,QVBoxLayout,QTabWidget)
import avatar_store as store

class VoicePicker(QComboBox):
    def __init__(self,selected='',placeholder=tr('Голос автора')):
        super().__init__();self.placeholder=placeholder;self.reload(selected)
        self.setMinimumWidth(160);self.setMaxVisibleItems(10)
    def reload(self,selected=None):
        selected=self.currentData() if selected is None else selected
        self.blockSignals(True);self.clear();self.addItem(self.placeholder,'')
        from avatar_folders import labels
        folders=labels()
        for voice in store.avatars():self.addItem(voice['name']+' · '+folders.get(voice['id'],tr('Без папки')),voice['id'])
        if selected and self.findData(selected)<0:
            item=store.load_json(store.DATA/'avatars'/selected/'avatar.json',{})
            self.addItem(tr('Недоступен: ')+item.get('name',tr('скрытый аватар')),selected)
        self.setCurrentIndex(max(0,self.findData(selected)));self.blockSignals(False)
    def showPopup(self):
        self.reload()
        from voice_search import choose
        chosen=choose(self)
        if chosen is not None:self.setCurrentIndex(self.findData(chosen))

STYLE='''
QDialog#bookStudio {background:#101218;}
QDialog#bookStudio QWidget {font-size:13px;}
QFrame#bookCard {background:#191c25;border:1px solid #2c303d;border-radius:14px;}
QFrame#bookCard QLabel {background:transparent;border:0;}
QDialog#bookStudio QLabel#bookTitle {font-size:25px;font-weight:600;color:#f5f2ee;}
QDialog#bookStudio QLabel#sectionTitle {font-size:11px;font-weight:600;color:#9fa8bc;letter-spacing:1px;}
QDialog#bookStudio QLabel#bookMuted {color:#939caf;font-size:12px;}
QDialog#bookStudio QLabel#authorTitle {font-size:16px;font-weight:600;}
QDialog#bookStudio QPushButton {padding:9px 13px;border-radius:8px;background:#242936;border:1px solid #353c4b;font-size:12px;}
QDialog#bookStudio QPushButton:hover {background:#303748;border-color:#717d99;}
QDialog#bookStudio QPushButton#primary {background:#b4a0f5;color:#191429;border:1px solid #c8b9fc;font-weight:600;}
QDialog#bookStudio QPushButton#primary:hover {background:#ccbcff;}
QDialog#bookStudio QPushButton:disabled {background:#1b1f29;color:#626b7c;border-color:#292e3a;}
QDialog#bookStudio QPushButton#primary:disabled {background:#302a42;color:#81788f;border-color:#3b344c;}
QDialog#bookStudio QComboBox {background:#11151e;border:1px solid #363e50;border-radius:8px;padding:9px 28px 9px 12px;min-height:18px;}
QDialog#bookStudio QComboBox::drop-down {border:0;width:25px;}
QDialog#bookStudio QComboBox:focus {border-color:#b4a0f5;}
QDialog#bookStudio QTableWidget {background:#151922;alternate-background-color:#191e29;border:0;gridline-color:#272d39;selection-background-color:#34304b;}
QDialog#bookStudio QHeaderView::section {background:#1d222e;color:#9fa8bc;font-size:11px;padding:10px;border:0;}
QDialog#bookStudio QListWidget {background:transparent;border:0;padding:0;}
QDialog#bookStudio QListWidget::item {padding:9px;margin:3px 0;border-radius:9px;}
QDialog#bookStudio QListWidget::item:selected {background:#2e2942;border:1px solid #665589;}
QDialog#bookStudio QTabWidget::pane {border:1px solid #2c303d;border-radius:10px;background:#151922;top:-1px;}
QDialog#bookStudio QTabBar::tab {background:transparent;color:#929cb0;padding:11px 22px;border-bottom:2px solid transparent;}
QDialog#bookStudio QTabBar::tab:selected {color:#e4d9ff;border-bottom:2px solid #b4a0f5;}
QDialog#bookStudio QProgressBar {min-height:5px;max-height:5px;background:#272d39;border:0;border-radius:2px;}
QDialog#bookStudio QProgressBar::chunk {background:#b4a0f5;border-radius:2px;}
'''

def label(text,name='bookMuted'):
    w=QLabel(text);w.setObjectName(name);w.setWordWrap(name=='bookMuted');return w
def card(parent_layout):
    frame=QFrame();frame.setObjectName('bookCard');box=QVBoxLayout(frame);box.setContentsMargins(16,14,16,14);box.setSpacing(10);parent_layout.addWidget(frame);return box
def button(text,callback,primary=False):
    w=QPushButton(text);w.setCursor(Qt.CursorShape.PointingHandCursor);w.clicked.connect(callback)
    if primary:w.setObjectName('primary')
    return w

def build(w):
    arrow=(Path(__file__).resolve().parent/'assets/chevron-down.svg').as_posix()
    w.setObjectName('bookStudio');w.setStyleSheet(STYLE+'QComboBox::down-arrow {image:url("'+arrow+'");width:10px;height:6px;}')
    screen=QApplication.primaryScreen().availableGeometry();w.resize(min(1180,screen.width()-40),min(800,screen.height()-45))
    outer=QVBoxLayout(w);outer.setContentsMargins(24,20,24,20);outer.setSpacing(18)
    header=QHBoxLayout();titles=QVBoxLayout();titles.setSpacing(5);titles.addWidget(label('VOX  /  BOOK STUDIO','sectionTitle'));titles.addWidget(label(tr('Аудиокниги'),'bookTitle'));header.addLayout(titles,1);header.addStretch()
    w.analysis_settings_button=button(tr('Модель / API'),w.configure_analysis);header.addWidget(w.analysis_settings_button)
    w.import_button=button(tr('+  Добавить книгу'),w.import_file,True);header.addWidget(w.import_button);outer.addLayout(header)
    w.append_button=button(tr('+  Дополнить книгу'),w.append_book);header.insertWidget(header.count()-1,w.append_button)
    center=QHBoxLayout();center.setSpacing(20);outer.addLayout(center,1)
    sidebar=QFrame();sidebar.setFixedWidth(225);left=QVBoxLayout(sidebar);left.setContentsMargins(0,0,0,0);left.setSpacing(10);center.addWidget(sidebar)
    left.addWidget(label(tr('БИБЛИОТЕКА'),'sectionTitle'));w.shelf=QListWidget();w.shelf.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff);w.shelf.currentItemChanged.connect(w.shelf_select);left.addWidget(w.shelf,3)
    left.addWidget(label(tr('ГЛАВЫ'),'sectionTitle'));w.chapters=QListWidget();w.chapters.currentRowChanged.connect(w.select_chapter);left.addWidget(w.chapters,2)
    w.chapter_voice=w.voice_combo();w.chapter_voice.placeholder=tr('Автор книги');w.chapter_voice.reload('');w.chapter_voice.currentIndexChanged.connect(w.save_chapter);left.addWidget(w.chapter_voice)
    w.mode=QComboBox();w.mode.addItem(tr('Глава по ролям'),'roles');w.mode.addItem(tr('Глава одним голосом'),'single');w.mode.currentIndexChanged.connect(w.save_chapter);left.addWidget(w.mode)
    w.chapter_play=button(tr('▷  Слушать главу'),w.play_chapter);left.addWidget(w.chapter_play)
    content=QVBoxLayout();content.setSpacing(12);center.addLayout(content,1)
    w.library=QComboBox();w.library.currentIndexChanged.connect(w.select_book);w.library.hide()
    w.note=label(tr('Загрузите книгу, назначьте голоса и создайте аудиоверсию.'));content.addWidget(w.note)
    author=card(content);row=QHBoxLayout();info=QVBoxLayout();info.setSpacing(3);info.addWidget(label(tr('01  /  ПОСТОЯННАЯ РОЛЬ'),'sectionTitle'));info.addWidget(label(tr('Автор / рассказчик'),'authorTitle'));info.addWidget(label(tr('Главы, описания и слова автора между репликами.')));row.addLayout(info,1)
    w.default_voice=w.voice_combo();w.default_voice.placeholder=tr('Выберите голос автора');w.default_voice.reload('');w.default_voice.setMinimumWidth(225);w.default_voice.currentIndexChanged.connect(w.save_defaults);row.addWidget(w.default_voice,1);author.addLayout(row)
    options=QHBoxLayout();w.book_mode=QComboBox();w.book_mode.addItem(tr('Несколько голосов'),'roles');w.book_mode.addItem(tr('Вся книга одним голосом'),'single');w.book_mode.currentIndexChanged.connect(w.save_defaults);options.addWidget(w.book_mode,1)
    options.addWidget(label(tr('Пауза')));w.pause=QSpinBox();w.pause.setRange(0,2000);w.pause.setSuffix(tr(' мс'));w.pause.setValue(180);w.pause.valueChanged.connect(w.save_defaults);options.addWidget(w.pause);author.addLayout(options)
    author.addWidget(label(tr('Автор · выразительная подача по тексту, без фиксированной эмоции и принудительного ускорения вставок.')))
    w.tabs=QTabWidget();content.addWidget(w.tabs,1)
    roles=QFrame();roles_layout=QVBoxLayout(roles);roles_layout.setContentsMargins(14,14,14,14)
    rolehead=QHBoxLayout();rolehead.addWidget(label(tr('02  /  ПЕРСОНАЖИ'),'sectionTitle'));rolehead.addStretch();w.add_character=button(tr('+ Персонаж'),w.new_character);rolehead.addWidget(w.add_character);roles_layout.addLayout(rolehead)
    w.cast=QTableWidget(0,3);w.cast.setHorizontalHeaderLabels([tr('Персонаж / категория'),tr('Голосовой аватар'),tr('Категория')]);w.cast.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch);w.cast.verticalHeader().hide();w.cast.verticalHeader().setDefaultSectionSize(48);w.cast.setShowGrid(False);w.cast.setAlternatingRowColors(True);roles_layout.addWidget(w.cast,1)
    w.cast.cellDoubleClicked.connect(w.show_portrait)
    w.portrait_button=button(tr('Портрет и заметки'),w.show_portrait);rolehead.insertWidget(rolehead.count()-1,w.portrait_button)
    roles_layout.addWidget(label(tr('Общая библиотека голосов. Автор присутствует в каждой книге; персонажи появляются после разметки.')));w.tabs.addTab(roles,tr('Голоса'))
    text=QFrame();text_layout=QVBoxLayout(text);text_layout.setContentsMargins(10,10,10,10)
    w.segments=QTableWidget(0,3);w.segments.setHorizontalHeaderLabels([tr('Текст'),tr('Голоса'),tr('Проверка')]);w.segments.horizontalHeader().setSectionResizeMode(0,QHeaderView.ResizeMode.Stretch);w.segments.setColumnWidth(1,145);w.segments.setColumnWidth(2,80);w.segments.verticalHeader().hide();w.segments.verticalHeader().setDefaultSectionSize(40);w.segments.setShowGrid(False);w.segments.setAlternatingRowColors(True);w.segments.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows);w.segments.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers);w.segments.cellDoubleClicked.connect(w.edit_text);text_layout.addWidget(w.segments,1)
    paging=QHBoxLayout();w.prev=button('←',lambda:w.page(-1));w.next=button('→',lambda:w.page(1));w.page_label=label('');paging.addWidget(w.prev);paging.addWidget(w.page_label);paging.addWidget(w.next);paging.addStretch();w.speaker=QComboBox();paging.addWidget(w.speaker,1);w.assign=button(tr('Назначить'),w.assign_speaker);paging.addWidget(w.assign);text_layout.addLayout(paging);w.tabs.addTab(text,tr('Текст и разметка'))
    from sound_ui import SoundPanel
    w.sounds=SoundPanel(w);w.tabs.addTab(w.sounds,tr('Звуки'))
    bottom=QHBoxLayout();w.analyze_button=button(tr('Разметить книгу'),w.analyze);bottom.addWidget(w.analyze_button);bottom.addStretch()
    w.provider_label=label('');bottom.addWidget(w.provider_label);content.addLayout(bottom)
    status=QHBoxLayout();w.status=label(tr('Выберите книгу'));status.addWidget(w.status,1);outer.addLayout(status)
    w.progress=QProgressBar();w.progress.setRange(0,1000);w.progress.setTextVisible(False);outer.addWidget(w.progress)
    footer=QHBoxLayout();w.render_all=button(tr('▶  Озвучить книгу'),lambda:w.render(False),True);footer.addWidget(w.render_all)
    w.render_chapter=button(tr('Озвучить главу'),lambda:w.render(True));footer.addWidget(w.render_chapter)
    w.restart_button=button(tr('Заново…'),w.restart_render);footer.addWidget(w.restart_button)
    w.pause_button=button(tr('Пауза'),w.toggle_pause);footer.addWidget(w.pause_button);w.stop_button=button(tr('Стоп'),lambda:w.request_stop());footer.addWidget(w.stop_button);footer.addStretch()
    w.listen_ready=button(tr('▷  Готовая часть'),w.preview_ready);footer.addWidget(w.listen_ready);w.export_button=button(tr('Скачать · MP3 / ZIP'),w.export);footer.addWidget(w.export_button);outer.addLayout(footer)
