"""Play ready WAV fragments in order without loading a model or joining a huge buffer."""
from PySide6.QtCore import QUrl,QTimer,Qt
from PySide6.QtWidgets import QDialog,QVBoxLayout,QHBoxLayout,QLabel,QPushButton,QSlider
from PySide6.QtMultimedia import QMediaPlayer,QAudioOutput
class ReadyPlayer(QDialog):
    def __init__(self,parent,paths,pause_ms=180):
        super().__init__(parent);self.paths=paths;self.index=0;self.pause_ms=pause_ms;self.playing=False
        self.setWindowTitle('Готовая часть книги');self.resize(620,210)
        layout=QVBoxLayout(self);self.title=QLabel();layout.addWidget(self.title)
        self.slider=QSlider(Qt.Orientation.Horizontal);layout.addWidget(self.slider)
        row=QHBoxLayout();previous=QPushButton('← Фрагмент');previous.clicked.connect(lambda:self.move(-1));row.addWidget(previous)
        self.toggle_button=QPushButton('▶ Слушать');self.toggle_button.clicked.connect(self.toggle);row.addWidget(self.toggle_button)
        following=QPushButton('Фрагмент →');following.clicked.connect(lambda:self.move(1));row.addWidget(following);layout.addLayout(row)
        self.player=QMediaPlayer(self);self.audio=QAudioOutput(self);self.player.setAudioOutput(self.audio)
        self.player.durationChanged.connect(lambda n:self.slider.setMaximum(n));self.player.positionChanged.connect(self.position);self.slider.sliderMoved.connect(self.player.setPosition)
        self.player.mediaStatusChanged.connect(self.status);self.gap=QTimer(self);self.gap.setSingleShot(True);self.gap.timeout.connect(lambda:self.move(1))
        self.player.errorOccurred.connect(lambda e,message:self.title.setText('Не удалось воспроизвести: '+message))
        self.load()
    def load(self):
        self.player.setSource(QUrl.fromLocalFile(self.paths[self.index]));self.title.setText(f'Готовый фрагмент {self.index+1} из {len(self.paths)}')
        if self.playing:self.player.play()
    def position(self,n):
        if not self.slider.isSliderDown():self.slider.setValue(n)
    def toggle(self):
        self.playing=not self.playing;self.toggle_button.setText('Ⅱ Пауза' if self.playing else '▶ Слушать')
        if self.playing:self.player.play()
        else:self.player.pause();self.gap.stop()
    def move(self,delta):
        self.gap.stop();self.index=max(0,min(len(self.paths)-1,self.index+delta));self.load()
    def status(self,status):
        if status==QMediaPlayer.MediaStatus.EndOfMedia and self.playing:
            if self.index+1<len(self.paths):self.gap.start(self.pause_ms)
            else:self.playing=False;self.toggle_button.setText('▶ Слушать')
    def done(self,result):self.gap.stop();self.player.stop();super().done(result)
