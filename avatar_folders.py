"""Logical folders: avatar IDs, samples and book assignments stay unchanged."""
import uuid
import avatar_store as store

def load():return store.load_json(store.DATA/'avatar-folders.json',dict(folders=[],assignments={}))
def save(data):store.atomic_json(store.DATA/'avatar-folders.json',data)
def create(name,folder_id=None,parent_id=None):
    name=name.strip();data=load()
    if not name or len(name)>60:raise ValueError('Название папки — от 1 до 60 символов.')
    existing=next((f for f in data['folders'] if f['id']==folder_id),None)
    parent_id=(existing or {}).get('parent','') if parent_id is None else parent_id
    if parent_id and not any(f['id']==parent_id for f in data['folders']):raise ValueError('Родительская папка не найдена.')
    if any(f.get('parent','')==parent_id and f['name'].casefold()==name.casefold() and f['id']!=folder_id for f in data['folders']):raise ValueError('Такая папка уже есть.')
    if folder_id:
        folder=next((f for f in data['folders'] if f['id']==folder_id),None)
        if not folder:raise ValueError('Папка не найдена.')
        folder['name']=name
    else:
        folder_id=uuid.uuid4().hex;data['folders'].append(dict(id=folder_id,name=name,parent=parent_id))
    save(data);return folder_id
def move(avatar_ids,folder_id):
    data=load()
    if folder_id and not any(f['id']==folder_id for f in data['folders']):raise ValueError('Папка не найдена.')
    for aid in avatar_ids:
        store.get_avatar(aid)
        if folder_id:data['assignments'][aid]=folder_id
        else:data['assignments'].pop(aid,None)
    save(data)
def remove(folder_id):
    data=load();folder=next((f for f in data['folders'] if f['id']==folder_id),None)
    if not folder:raise ValueError('Папка не найдена.')
    parent=folder.get('parent','')
    for child in data['folders']:
        if child.get('parent','')==folder_id:
            child['parent']=parent
    data['folders']=[f for f in data['folders'] if f['id']!=folder_id]
    data['assignments']={a:(parent if f==folder_id else f) for a,f in data['assignments'].items() if f!=folder_id or parent}
    save(data)

def paths(data=None):
    data=data or load();groups={f['id']:f for f in data['folders']}
    result={}
    for fid in groups:
        names=[];seen=set();current=fid
        while current in groups and current not in seen:
            seen.add(current);group=groups[current];names.append(group['name']);current=group.get('parent','')
        result[fid]=' / '.join(reversed(names))
    return result

def labels():
    data=load();names=paths(data)
    return {a:names.get(f,'Без папки') for a,f in data['assignments'].items()}
