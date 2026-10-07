from pathlib import Path
import hashlib
from PySide6.QtCore import Qt, QRectF
from PySide6.QtGui import QColor, QFont, QIcon, QImage, QLinearGradient, QPainter, QPainterPath, QPixmap

ROOT = Path(__file__).resolve().parent
ASSETS = ROOT / 'assets'


def logo(size=128):
    image = QImage(size, size, QImage.Format.Format_ARGB32)
    image.fill(Qt.GlobalColor.transparent)
    painter = QPainter(image)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    gradient = QLinearGradient(0, 0, size, size)
    gradient.setColorAt(0, QColor('#a18bff'))
    gradient.setColorAt(.55, QColor('#7552ee'))
    gradient.setColorAt(1, QColor('#473184'))
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(gradient)
    painter.drawRoundedRect(QRectF(size*.035, size*.035, size*.93, size*.93), size*.24, size*.24)
    painter.setBrush(QColor('#f8f5ff'))
    for i, height in enumerate([.20, .40, .64, .40, .20]):
        painter.drawRoundedRect(QRectF(size*(.225+i*.115), size*(.5-height/2), size*.066, size*height), size*.033, size*.033)
    painter.end()
    return QPixmap.fromImage(image)


def profile_icon(name, picture='', size=64):
    canvas = QPixmap(size, size)
    canvas.fill(Qt.GlobalColor.transparent)
    painter = QPainter(canvas)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    clip = QPainterPath()
    clip.addRoundedRect(QRectF(0, 0, size, size), size*.28, size*.28)
    painter.setClipPath(clip)
    photo = QPixmap(str(picture)) if picture and Path(picture).is_file() else QPixmap()
    if not photo.isNull():
        photo = photo.scaled(size, size, Qt.AspectRatioMode.KeepAspectRatioByExpanding, Qt.TransformationMode.SmoothTransformation)
        painter.drawPixmap((size-photo.width())//2, (size-photo.height())//2, photo)
    else:
        palette = [('#bd93ff', '#51408a'), ('#62d9c7', '#245e65'), ('#f1b27d', '#7d4552'), ('#92baff', '#3a528d')]
        a, b = palette[int(hashlib.sha256(name.encode()).hexdigest()[:2], 16) % len(palette)]
        gradient = QLinearGradient(0, 0, size, size)
        gradient.setColorAt(0, QColor(a))
        gradient.setColorAt(1, QColor(b))
        painter.fillRect(0, 0, size, size, gradient)
        painter.setFont(QFont('Segoe UI', int(size*.32), QFont.Weight.DemiBold))
        painter.setPen(QColor('#ffffff'))
        initials = ''.join(x[0] for x in name.split()[:2]).upper() or 'V'
        painter.drawText(canvas.rect(), Qt.AlignmentFlag.AlignCenter, initials)
    painter.end()
    return canvas


def ensure_assets():
    ASSETS.mkdir(exist_ok=True)
    png = ASSETS / 'vox-studio.png'
    ico = ASSETS / 'vox-studio.ico'
    if not png.exists() or not ico.exists():
        logo(512).save(str(png))
        from PIL import Image
        with Image.open(png) as image:
            image.save(ico, sizes=[(16,16), (24,24), (32,32), (48,48), (64,64), (128,128), (256,256)])
    return QIcon(str(ico))
