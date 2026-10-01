import re,json,sys,urllib.parse,subprocess
base=sys.argv[1]  # e.g. https://www.youtube.com/@gtrfradio  or 'global'
for q in sys.argv[2:]:
    if base=='global':
        url="https://www.youtube.com/results?search_query="+urllib.parse.quote(q)
    else:
        url=base+"/search?query="+urllib.parse.quote(q)
    t=subprocess.run(["curl","-s","-m","25","-A","Mozilla/5.0","-H","Accept-Language: ru",url],capture_output=True).stdout.decode('utf-8','ignore')
    m=re.search(r'var ytInitialData = (\{.*?\});</script>',t)
    print("=== ",q)
    if not m: print("no data"); continue
    d=json.loads(m.group(1)); seen=set()
    def walk(o):
        if isinstance(o,dict):
            if 'videoRenderer' in o:
                v=o['videoRenderer']
                if v['videoId'] in seen: return
                seen.add(v['videoId'])
                ch=v.get('ownerText',{}).get('runs',[{}])[0].get('text','')
                print(v['videoId'], v.get('lengthText',{}).get('simpleText'), '|', v['title']['runs'][0]['text'], '|', ch)
            for x in o.values(): walk(x)
        elif isinstance(o,list):
            for x in o: walk(x)
    walk(d)
