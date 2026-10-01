import urllib.request
import urllib.parse
import re

def search(query):
    url = f"https://html.duckduckgo.com/html/?q={urllib.parse.quote(query)}"
    req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
    try:
        html = urllib.request.urlopen(req).read().decode('utf-8')
        matches = re.findall(r'href="([^"]+)"[^>]*>(.*?)</a>', html)
        for m in matches:
            if 'vk.com/video' in m[0] or 'youtube.com' in m[0] or 'archive.org' in m[0]:
                print(m[0])
    except Exception as e:
        print("ERROR", e)

search("Михаил Строгов аудиокнига Жюль Верн site:vk.com")
