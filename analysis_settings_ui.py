"""Provider switch and API setup. Authentication runs outside the UI thread."""
from ui_language import tr
import threading
from PySide6.QtCore import QObject,Signal,Slot,Qt
from PySide6.QtWidgets import QDialog,QVBoxLayout,QHBoxLayout,QFormLayout,QLabel,QComboBox,QLineEdit,QPushButton,QFrame
import analysis_settings as preferences

_checks=set()  # Keep pending read-only checks alive even if their dialog is closed.

class ConnectionCheck(QObject):
    result=Signal(bool,object)
    finished=Signal()
    def __init__(self,url,key,model):
        super().__init__();self.url=url;self.key=key;self.model=model
    def run(self):
        try:
            from deepseek_model import probe,list_models
            message=list_models(self.url,self.key) if self.model is None else probe(self.url,self.key,self.model);self.result.emit(True,message)
        except Exception as exc:self.result.emit(False,str(exc))
        finally:self.key='';self.finished.emit()
    def start(self):threading.Thread(target=self.run,daemon=True).start()

class AnalysisSettingsDialog(QDialog):
    def __init__(self,parent=None):
        super().__init__(parent);self.setWindowTitle(tr('Разметка · модель и API'));self.setMinimumWidth(600)
        self.testing=False;self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose,False)
        outer=QVBoxLayout(self);outer.setContentsMargins(24,22,24,22);outer.setSpacing(16)
        title=QLabel(tr('Как обрабатывать текст'));title.setObjectName('subtitle');outer.addWidget(title)
        self.provider=QComboBox();self.provider.addItem(tr('DeepSeek API · облачная разметка'),'deepseek');self.provider.addItem('OpenRouter','openrouter');self.provider.addItem(tr('Другой API · совместимый с OpenAI'),'compatible');self.provider.addItem(tr('Локальная модель · на видеокарте'),'local')
        outer.addWidget(self.provider)
        self.panel=QFrame();form=QFormLayout(self.panel);form.setContentsMargins(0,0,0,0);form.setSpacing(12)
        config=preferences.settings()
        self.url=QLineEdit(config['base_url']);self.url.setPlaceholderText(preferences.DEFAULT_URL);form.addRow(tr('Адрес API'),self.url)
        self.model=QComboBox();self.model.setEditable(True);self.model.addItem('deepseek-flash');self.model.addItem('deepseek-v4-pro');self.model.setCurrentText(config['model']);form.addRow(tr('Модель'),self.model)
        keys=QHBoxLayout();self.key=QLineEdit();self.key.setEchoMode(QLineEdit.EchoMode.Password)
        self.key.setPlaceholderText(tr('Ключ сохранён · оставьте пустым, чтобы сохранить его') if config['has_key'] else tr('Вставьте API-ключ выбранного сервера'))
        self.key.setClearButtonEnabled(True);keys.addWidget(self.key,1)
        self.show_key=QPushButton(tr('Показать'));self.show_key.setCheckable(True);self.show_key.toggled.connect(lambda checked:self.key.setEchoMode(QLineEdit.EchoMode.Normal if checked else QLineEdit.EchoMode.Password));keys.addWidget(self.show_key);form.addRow(tr('API-ключ'),keys)
        self.link=QLabel('<a href="https://platform.deepseek.com/api_keys" style="color:#b4a0f5">Открыть страницу API-ключей DeepSeek ↗</a>');self.link.setOpenExternalLinks(True);form.addRow('',self.link)
        self.test=QPushButton(tr('Проверить подключение'));self.test.clicked.connect(self.check_connection);form.addRow('',self.test)
        self.fetch_models=QPushButton(tr('Загрузить список моделей'));self.fetch_models.clicked.connect(lambda:self.check_connection(models=True));form.addRow('',self.fetch_models)
        outer.addWidget(self.panel)
        self.description=QLabel();self.description.setWordWrap(True);self.description.setObjectName('muted');outer.addWidget(self.description)
        self.status=QLabel('');self.status.setWordWrap(True);outer.addWidget(self.status)
        row=QHBoxLayout();row.addStretch();cancel=QPushButton(tr('Отмена'));cancel.clicked.connect(self.reject);row.addWidget(cancel)
        self.save_button=QPushButton(tr('Сохранить'));self.save_button.setObjectName('primary');self.save_button.clicked.connect(self.save);row.addWidget(self.save_button);outer.addLayout(row)
        self.previous_provider=config['provider']
        self.provider.currentIndexChanged.connect(self.refresh);self.provider.setCurrentIndex(self.provider.findData(config['provider']));self.refresh()
    def refresh(self):
        provider=self.provider.currentData();remote=preferences.is_remote(provider);self.panel.setVisible(remote)
        if remote and provider!=self.previous_provider:
            preset=preferences.PROVIDERS[provider];self.url.setText(preset['url']);self.model.clear();self.model.addItems(preset['models']);self.key.clear()
        if remote:
            preset=preferences.PROVIDERS[provider];self.link.setText('<a href="'+preset['keys']+'">API keys ↗</a>' if preset['keys'] else '')
        self.previous_provider=provider
        self.description.setText(tr('Текст книг и текст с числами из студии будет отправляться на указанный сервер. API оплачивается по использованию. Голосовые образцы и озвучка остаются на компьютере.\nКлюч хранится зашифрованным для вашей учётной записи Windows. Смена модели применяется при следующем запуске разметки.') if remote else tr('Разметка и подготовка чисел выполняются локальной моделью на GPU. Настройки и ключ API сохраняются для следующего переключения.'))
    def values(self):
        return preferences.normalize_url(self.url.text()),preferences.validate_model(self.model.currentText())
    def check_connection(self,checked=False,models=False):
        try:
            url=preferences.normalize_url(self.url.text());model=None if models else preferences.validate_model(self.model.currentText());key=preferences.validate_key(self.key.text()) if self.key.text().strip() else preferences.api_key(url)
        except Exception as exc:self.status.setText(str(exc));return
        self.testing=True;self.test.setEnabled(False);self.save_button.setEnabled(False);self.panel.setEnabled(False);self.provider.setEnabled(False)
        self.status.setText(tr('Проверяем ключ и доступность модели… Текст книги не отправляется.'))
        worker=ConnectionCheck(url,key,model);_checks.add(worker)
        worker.result.connect(self.checked)
        worker.finished.connect(lambda w=worker:(_checks.discard(w),w.deleteLater()))
        worker.start()
    @Slot(bool,object)
    def checked(self,success,message):
        self.testing=False;self.test.setEnabled(True);self.save_button.setEnabled(True);self.panel.setEnabled(True);self.provider.setEnabled(True)
        if success and isinstance(message,list):
            selected=self.model.currentText();self.model.clear();self.model.addItems(message)
            if selected:self.model.setCurrentText(selected)
            message=tr('Список моделей загружен.')
        self.status.setText(message);self.status.setStyleSheet('color:#8ce1ce;' if success else 'color:#f0b6a5;')
    def save(self):
        if self.testing:return
        try:
            if self.provider.currentData()=='local':preferences.save('local')
            else:
                url,model=self.values();preferences.save(self.provider.currentData(),url,model,self.key.text())
        except Exception as exc:self.status.setText(str(exc));return
        self.key.clear();self.accept()
