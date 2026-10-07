from ui_language import tr
from PySide6.QtCore import Qt,QSize,QMimeData
from PySide6.QtGui import QIcon,QDrag
from PySide6.QtWidgets import QTreeWidget,QTreeWidgetItem,QAbstractItemView,QInputDialog,QMessageBox
import avatar_store as store
import avatar_folders as folders
ROLE=Qt.ItemDataRole.UserRole

class AvatarTree(QTreeWidget):
    def __init__(self,host):
        super().__init__();self.host=host;self.query='';self.expanded={};self.parents={}
        self.setHeaderHidden(True);self.setIndentation(20);self.setExpandsOnDoubleClick(False)
        self.setStyleSheet('QTreeWidget {background:transparent;border:0;} QTreeWidget::item {padding:5px;border-radius:8px;} QTreeWidget::item:selected {background:#353049;color:#efedf9;} QTreeWidget::item:hover {background:#252636;}')
        self.setDragEnabled(True);self.setAcceptDrops(True);self.setDropIndicatorShown(True)
        self.setDragDropMode(QAbstractItemView.DragDropMode.DragDrop)
        self.setDefaultDropAction(Qt.DropAction.CopyAction)
        self.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.itemExpanded.connect(lambda item:self.remember(item,True))
        self.itemCollapsed.connect(lambda item:self.remember(item,False))
    def remember(self,item,value):
        if not self.query and not item.data(0,ROLE):self.expanded[item.data(0,ROLE+1)]=value
    def mousePressEvent(self,event):
        item=self.itemAt(event.position().toPoint())
        toggle=bool(item and not item.data(0,ROLE) and event.button()==Qt.MouseButton.LeftButton and self.visualItemRect(item).contains(event.position().toPoint()))
        was=item.isExpanded() if item else False
        super().mousePressEvent(event)
        if toggle:item.setExpanded(not was)
    def reload(self,selected,icon):
        self.blockSignals(True);self.clear();data=folders.load();self.parents={};chosen=None;first=None
        groups=[dict(id='',name=tr('Без папки')),*data['folders']];lookup={g['id']:g for g in groups}
        for group in groups:
            item=QTreeWidgetItem([group['name']]);item.setData(0,ROLE+1,group['id']);item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsDragEnabled)
            self.parents[group['id']]=item
        for group in groups:
            item=self.parents[group['id']];parent=group.get('parent','');seen={group['id']};current=parent;valid=True
            while current:
                if current in seen:valid=False;break
                seen.add(current);current=lookup.get(current,{}).get('parent','')
            if parent and parent in self.parents and valid:self.parents[parent].addChild(item)
            else:self.addTopLevelItem(item)
        labels=folders.paths(data)
        for avatar in store.avatars():
            group=data['assignments'].get(avatar['id'],'');parent=self.parents.get(group,self.parents[''])
            item=QTreeWidgetItem([(f"{avatar['name']}" + tr('\nОбразец · ') + f"{avatar['duration']:.0f}" + tr(' сек'))]);item.setIcon(0,QIcon(icon(avatar)))
            item.setToolTip(0,labels.get(group,tr('Без папки')));item.setData(0,ROLE,avatar);item.setSizeHint(0,QSize(180,65));item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsDropEnabled);parent.addChild(item)
            first=first or item
            if avatar['id']==selected:chosen=item
        for fid,parent in self.parents.items():
            parent.setText(0,parent.text(0)+f' ({self.avatar_count(parent)})');parent.setExpanded(self.expanded.get(fid,True))
        self.setCurrentItem(chosen or first);self.blockSignals(False);self.apply_filter()
    def avatar_count(self,item):
        return sum(1 if item.child(i).data(0,ROLE) else self.avatar_count(item.child(i)) for i in range(item.childCount()))
    def set_filter(self,text):
        self.query=text.strip().casefold();self.apply_filter()
    def apply_filter(self):
        self.blockSignals(True)
        def visit(item):
            avatar=item.data(0,ROLE)
            if avatar:visible=not self.query or self.query in (avatar['name']+' '+item.toolTip(0)).casefold()
            else:
                matches=[visit(item.child(i)) for i in range(item.childCount())]
                visible=not self.query or any(matches) or self.query in item.text(0).casefold()
                item.setExpanded(True if self.query and visible else self.expanded.get(item.data(0,ROLE+1),True))
            item.setHidden(not visible);return visible
        for i in range(self.topLevelItemCount()):visit(self.topLevelItem(i))
        self.blockSignals(False)
    def new_folder(self,folder_id=None,parent_id=''):
        if self.host.busy:return
        old=next((f['name'] for f in folders.load()['folders'] if f['id']==folder_id),'')
        name,ok=QInputDialog.getText(self,tr('Папка аватаров'),tr('Название:'),text=old)
        if ok:
            try:
                fid=folders.create(name,folder_id,parent_id=None if folder_id else parent_id);self.expanded[fid]=True
                if parent_id:self.expanded[parent_id]=True
                self.refresh()
            except ValueError as exc:QMessageBox.warning(self,tr('Папка'),str(exc))
    def refresh(self):
        selected=(self.host.current_avatar or {}).get('id');self.host.refresh_avatars(selected)
    def move_selected(self,folder_id):
        if self.host.busy:return
        ids=[item.data(0,ROLE)['id'] for item in self.selectedItems() if item.data(0,ROLE)]
        if not ids:return
        folders.move(ids,folder_id)
        lookup={f['id']:f for f in folders.load()['folders']};current=folder_id;seen=set()
        while current not in seen:
            seen.add(current);self.expanded[current]=True
            if not current:break
            current=lookup.get(current,{}).get('parent','')
        self.refresh()
    def startDrag(self,supportedActions):
        if self.host.busy or not any(i.data(0,ROLE) for i in self.selectedItems()):return
        drag=QDrag(self);mime=QMimeData();mime.setData('application/x-vox-avatars',b'1');drag.setMimeData(mime)
        # Persist movement ourselves; Qt must not remove rows rebuilt on drop.
        drag.exec(Qt.DropAction.CopyAction)
    def dragEnterEvent(self,event):
        if event.source() is self and not self.host.busy:event.acceptProposedAction()
        else:event.ignore()
    def dragMoveEvent(self,event):self.dragEnterEvent(event)
    def dropEvent(self,event):
        if self.host.busy or event.source() is not self:event.ignore();return
        item=self.itemAt(event.position().toPoint())
        if item and item.data(0,ROLE):item=item.parent()
        folder_id=item.data(0,ROLE+1) if item else ''
        self.move_selected(folder_id);event.setDropAction(Qt.DropAction.CopyAction);event.accept()
    def folder_menu(self,menu,item):
        menu.addAction(tr('Создать папку'),lambda:self.new_folder()).setEnabled(not self.host.busy)
        folder_id=item.data(0,ROLE+1) if item else ''
        if folder_id:
            menu.addAction(tr('Создать подпапку'),lambda:self.new_folder(parent_id=folder_id)).setEnabled(not self.host.busy)
            menu.addAction(tr('Переименовать папку'),lambda:self.new_folder(folder_id)).setEnabled(not self.host.busy)
            def remove():
                if QMessageBox.question(self,tr('Удалить папку?'),tr('Аватары и подпапки останутся в библиотеке и перейдут на уровень выше.'))==QMessageBox.StandardButton.Yes:folders.remove(folder_id);self.refresh()
            menu.addAction(tr('Удалить папку'),remove).setEnabled(not self.host.busy)
