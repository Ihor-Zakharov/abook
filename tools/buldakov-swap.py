import json,subprocess,time
N='/home/ihor/.nvm/versions/node/v24.21.0/bin/node'; Y='/home/ihor/.local/share/uv/tools/vydra/bin/yt-dlp'
full=json.load(open('/home/ihor/abook/manifests/F-buldakov.json',encoding='utf-8'))
top=json.load(open('/home/ihor/abook/F-buldakov-top.json',encoding='utf-8'))
have={i['id'] for i in top['items']}; need=61.0; got=0; added=[]
cands=sorted([i for i in full['items'] if i['id'] not in have and not i['id'].startswith('tayny')], key=lambda i:(i.get('rank',9),-i.get('duration_h',0)))
for c in cands:
    if got>=need: break
    ok=True
    for u in {c['urls'][0],c['urls'][-1]}:
        r=subprocess.run([Y,'--cookies','/home/ihor/.config/vydra/cookies.txt','--js-runtimes','node:'+N,'--simulate','--no-warnings','--socket-timeout','30',u],capture_output=True,text=True,timeout=150)
        time.sleep(3)
        if r.returncode!=0: ok=False; print('- skip',c['id'],(r.stderr.strip().splitlines() or ['?'])[-1][:100],flush=True); break
    if ok: added.append(c); got+=c['duration_h']; print('+',c['id'],c['title'],c['duration_h'],'rank',c.get('rank'),flush=True)
top['items']+=added; top['top_ids']=[i['id'] for i in top['items']]
json.dump(top,open('/home/ihor/abook/F-buldakov-top.json','w',encoding='utf-8'),ensure_ascii=False,indent=1)
print('итого Булдаков:',round(sum(i['duration_h'] for i in top['items']),1),flush=True)
