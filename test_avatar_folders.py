import os,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
from PySide6.QtWidgets import QApplication,QDialog,QLineEdit,QListWidget
from PySide6.QtCore import QTimer
import avatar_store as store
import avatar_folders as folders

class FoldersTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):cls.app=QApplication.instance() or QApplication([])
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name);self.p=patch.object(store,'DATA',self.root);self.p.start()
        self.ref=self.root/'ref.wav';self.ref.write_bytes(b'sample')
        self.voice=store.save_profile('Анна',self.ref,'Текст',3)
    def tearDown(self):self.p.stop();self.tmp.cleanup()
    def test_folder_persists_through_voice_edit_and_deletion(self):
        gid=folders.create('Дети');folders.move([self.voice['id']],gid)
        store.save_profile('Анна 2',self.ref,'Текст',3,avatar_id=self.voice['id'])
        self.assertEqual(folders.labels()[self.voice['id']],'Дети')
        folders.create('Детские',gid);self.assertEqual(folders.labels()[self.voice['id']],'Детские')
        folders.remove(gid);self.assertNotIn(self.voice['id'],folders.labels())
        self.assertEqual(store.get_avatar(self.voice['id'])['name'],'Анна 2')
    def test_invalid_moves_do_not_change_assignment(self):
        gid=folders.create('Дети')
        with self.assertRaises(ValueError):folders.create('дети')
        with self.assertRaises(ValueError):folders.move([self.voice['id']],'missing')
        self.assertEqual(folders.load()['assignments'],{})
    def test_nested_paths_rename_and_remove_preserve_avatars(self):
        root=folders.create('Дети');sub=folders.create('Девочки',parent_id=root)
        leaf=folders.create('Младшие',parent_id=sub)
        folders.move([self.voice['id']],leaf)
        self.assertEqual(folders.labels()[self.voice['id']],'Дети / Девочки / Младшие')
        folders.create('Детские',root)
        self.assertEqual(folders.labels()[self.voice['id']],'Детские / Девочки / Младшие')
        folders.remove(sub)
        self.assertEqual(folders.labels()[self.voice['id']],'Детские / Младшие')
        folders.remove(leaf)
        self.assertEqual(folders.labels()[self.voice['id']],'Детские')
        self.assertTrue(store.get_avatar(self.voice['id']))
        folders.create('Младшие',parent_id=root)
        folders.create('Младшие')
        with self.assertRaises(ValueError):folders.create('младшие',parent_id=root)
    def test_repeat_drop_folder_click_and_search(self):
        from avatar_tree import AvatarTree,ROLE
        from PySide6.QtGui import QPixmap
        from PySide6.QtCore import Qt,QPointF
        from PySide6.QtTest import QTest
        from types import SimpleNamespace
        first=folders.create('Дети');second=folders.create('Девочки',parent_id=first)
        host=SimpleNamespace(busy=False,current_avatar=self.voice)
        tree=AvatarTree(host);host.refresh_avatars=lambda selected:tree.reload(selected,lambda _:QPixmap())
        tree.resize(350,500);tree.show();host.refresh_avatars(self.voice['id']);self.app.processEvents()
        # Exercise the actual drop handler twice, including rebuilding its items.
        class Drop:
            def __init__(self,target):self.target=target;self.accepted=False
            def source(self):return tree
            def position(self):return QPointF(tree.visualItemRect(tree.parents[self.target]).center())
            def setDropAction(self,action):self.action=action
            def accept(self):self.accepted=True
            def ignore(self):self.accepted=False
        for target in (first,second):
            tree.currentItem().setSelected(True);drop=Drop(target);tree.dropEvent(drop);self.app.processEvents()
            self.assertTrue(drop.accepted);self.assertEqual(drop.action,Qt.DropAction.CopyAction)
            self.assertEqual(tree.parents[target].childCount(),2 if target==first else 1)
            item=tree.parents[target]
            QTest.mouseClick(tree.viewport(),Qt.MouseButton.LeftButton,pos=tree.visualItemRect(item).center())
            self.assertFalse(item.isExpanded())
            QTest.mouseClick(tree.viewport(),Qt.MouseButton.LeftButton,pos=tree.visualItemRect(item).center())
            self.assertTrue(item.isExpanded())
            tree.setCurrentItem(next(item.child(i) for i in range(item.childCount()) if item.child(i).data(0,ROLE)))
        tree.parents[first].setExpanded(False)
        tree.set_filter('анна');self.assertTrue(tree.parents[first].isExpanded());self.assertFalse(tree.currentItem().isHidden())
        tree.set_filter('несуществующее');self.assertTrue(tree.parents[first].isHidden())
        tree.set_filter('девочки');self.assertFalse(tree.parents[first].isHidden())
        tree.set_filter('');self.assertFalse(tree.parents[first].isExpanded())
        host.refresh_avatars(self.voice['id']);self.assertFalse(tree.parents[first].isExpanded())
        tree.close();tree.deleteLater();self.app.processEvents()
    def test_search_by_folder_keeps_avatar_id(self):
        gid=folders.create('Дети');folders.move([self.voice['id']],gid)
        from book_design import VoicePicker
        picker=VoicePicker();self.assertIn('Дети',picker.itemText(1))
        def select():
            dialog=QApplication.activeModalWidget();dialog.findChild(QLineEdit).setText('дети')
            items=dialog.findChild(QListWidget);self.assertEqual(items.count(),1);dialog.accept()
        QTimer.singleShot(0,select);picker.showPopup()
        self.assertEqual(picker.currentData(),self.voice['id'])
        QTimer.singleShot(0,lambda:QApplication.activeModalWidget().reject());picker.showPopup()
        self.assertEqual(picker.currentData(),self.voice['id'])
        picker.deleteLater();self.app.processEvents()
    def test_tree_moves_multiple_voices_to_folder(self):
        from avatar_tree import AvatarTree
        from PySide6.QtGui import QPixmap
        from types import SimpleNamespace
        other=store.save_profile('Борис',self.ref,'Текст',3);gid=folders.create('Дети')
        host=SimpleNamespace(busy=False,current_avatar=self.voice)
        tree=AvatarTree(host);host.refresh_avatars=lambda selected:tree.reload(selected,lambda _:QPixmap())
        host.refresh_avatars(self.voice['id'])
        root=tree.topLevelItem(0)
        root.child(0).setSelected(True);root.child(1).setSelected(True)
        tree.move_selected(gid)
        self.assertEqual(tree.topLevelItem(1).childCount(),2)
        self.assertEqual(folders.labels()[other['id']],'Дети')
        self.assertEqual(tree.topLevelItem(0).childCount(),0)
        tree.deleteLater();self.app.processEvents()

if __name__=='__main__':unittest.main()
