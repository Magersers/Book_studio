"""Conservative structural JSON repair; never rewrite string values."""
import json,re

def parse(text):
    try:return json.loads(text)
    except json.JSONDecodeError:pass
    stack=[];quoted=False;escape=False;out=[];removed=0
    for index,char in enumerate(text):
        if quoted:
            out.append(char)
            if escape:escape=False
            elif char=='\\':escape=True
            elif char=='"':quoted=False
            continue
        if char=='"':quoted=True
        elif char in '[{':stack.append(char)
        elif char in ']}':
            expected='[' if char==']' else '{'
            if stack and stack[-1]!=expected:
                # Stray array terminator before another object field, seen
                # after nested portrait objects. The owning object is open.
                if char==']' and stack[-1]=='{' and re.match(r'\s*,\s*"assignments"\s*:',text[index+1:]) and stack.count('[')==1:
                    # Missing character/portrait object terminators before the
                    # top-level assignments field. Do not touch string values.
                    while stack and stack[-1]=='{':out.append('}');stack.pop();removed+=1
                    if stack and stack[-1]=='[':stack.pop();out.append(char);continue
                    return json.loads(text)
                if char==']' and stack[-1]=='{' and re.match(r'\s*,\s*"(?:[^"\\]|\\.)*"\s*:',text[index+1:]):
                    removed+=1;continue
                return json.loads(text)
            if stack:stack.pop()
        out.append(char)
    if not removed:return json.loads(text)
    return json.loads(''.join(out))
