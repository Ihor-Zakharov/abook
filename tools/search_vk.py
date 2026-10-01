import urllib.request
import urllib.parse
import re

def search(query):
    print(f"\nSearching VK for: {query}")
    url = f"https://vk.com/video?q={urllib.parse.quote(query)}"
    req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
    try:
        html = urllib.request.urlopen(req).read().decode('utf-8')
        matches = re.findall(r'<a href="(/video-?[0-9]+_[0-9]+)"[^>]*aria-label="([^"]+)"', html)
        for m in matches[:5]:
            print(f"URL: https://vk.com{m[0]} | TITLE: {m[1]}")
    except Exception as e:
        print("ERROR", e)

search("Лем Фиаско аудиокнига")
search("Лем Насморк аудиокнига")
search("Цвейг Смятение чувств аудиокнига")
