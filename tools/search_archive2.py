import urllib.request
import json
import urllib.parse

def search(query):
    url = f"https://archive.org/advancedsearch.php?q={urllib.parse.quote(query)}&fl[]=identifier,title,creator,mediatype&sort[]=&sort[]=&sort[]=&rows=10&page=1&output=json"
    req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
    try:
        data = json.loads(urllib.request.urlopen(req).read().decode('utf-8'))
        for doc in data['response']['docs']:
            print(f"URL: https://archive.org/details/{doc.get('identifier')} | TITLE: {doc.get('title')}")
    except Exception as e:
        print("ERROR", e)

search("Жюль Верн Михаил Строгов")
search("Верн Михаил Строгов")
