import urllib.request
import re
import json
import urllib.parse

queries = [
    "Герман Гессе Демиан аудиокнига полная",
    "Стефан Цвейг Смятение чувств аудиокнига полная",
    "Станислав Лем Фиаско аудиокнига плейлист",
    "Станислав Лем Насморк аудиокнига полная",
    "Жюль Верн Михаил Строгов аудиокнига полная",
    "Джек Лондон Время не ждет аудиокнига Бордуков"
]

def search_yt(query):
    url = f"https://www.youtube.com/results?search_query={urllib.parse.quote(query)}"
    req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'})
    try:
        html = urllib.request.urlopen(req).read().decode('utf-8')
        data_match = re.search(r'var ytInitialData = ({.*?});</script>', html)
        if data_match:
            data = json.loads(data_match.group(1))
            contents = data.get('contents', {}).get('twoColumnSearchResultsRenderer', {}).get('primaryContents', {}).get('sectionListRenderer', {}).get('contents', [])
            for c in contents:
                items = c.get('itemSectionRenderer', {}).get('contents', [])
                for item in items:
                    video = item.get('videoRenderer')
                    if video:
                        title = video.get('title', {}).get('runs', [{}])[0].get('text', '')
                        vid_id = video.get('videoId')
                        duration = video.get('lengthText', {}).get('simpleText', '')
                        author = video.get('ownerText', {}).get('runs', [{}])[0].get('text', '')
                        print(f"QUERY: {query} | TITLE: {title} | URL: https://www.youtube.com/watch?v={vid_id} | DURATION: {duration} | AUTHOR: {author}")
                    playlist = item.get('playlistRenderer')
                    if playlist:
                        title = playlist.get('title', {}).get('simpleText', '')
                        pid = playlist.get('playlistId')
                        count = playlist.get('videoCount', '')
                        author = playlist.get('shortBylineText', {}).get('runs', [{}])[0].get('text', '')
                        print(f"QUERY: {query} | PLAYLIST: {title} | URL: https://www.youtube.com/playlist?list={pid} | COUNT: {count} | AUTHOR: {author}")
    except Exception as e:
        print("ERROR:", e)

for q in queries:
    search_yt(q)
