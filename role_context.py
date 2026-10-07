"""Bounded original chapter context, including both sides of the target block."""
import hashlib,json

SCENE_CHARS=28000

class ChapterContext:
    def __init__(self,rows,title=''):
        self.title=title
        self.lines=[f'[{r["id"]}] {r["text"]}' for r in rows]
        self.lengths=[len(line)+1 for line in self.lines]
        self.size=sum(self.lengths)
        self.full='\n'.join(self.lines)
        # Later text can explain an earlier speaker: it is a cache dependency too.
        self.digest=hashlib.sha256(json.dumps([(r['id'],r['text'],r.get('speaker') if r.get('manual') else None) for r in rows],ensure_ascii=False).encode()).hexdigest()

    def window(self,start,count,limit=SCENE_CHARS):
        if limit<=0:return None
        end=min(len(self.lines),start+count)
        left,right=start,end
        size=sum(self.lengths[left:right])
        if size>limit:return None
        if self.size<=limit:
            left,right=0,len(self.lines)
        else:
            # Keep complete source fragments and expand on both sides.
            before=after=0
            while left>0 or right<len(self.lines):
                options=[]
                if left>0 and size+self.lengths[left-1]<=limit:options.append((before,0))
                if right<len(self.lines) and size+self.lengths[right]<=limit:options.append((after,1))
                if not options:break
                _,side=min(options)
                if side==0:left-=1;size+=self.lengths[left];before+=self.lengths[left]
                else:size+=self.lengths[right];after+=self.lengths[right];right+=1
        return dict(chapter=self.title,scope='whole_chapter' if left==0 and right==len(self.lines) else 'chapter_window',
                    text=self.full if left==0 and right==len(self.lines) else '\n'.join(self.lines[left:right]))
