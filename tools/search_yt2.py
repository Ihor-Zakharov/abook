import urllib.request
import re
import json
import urllib.parse
import sys

queries = [
    "Герман Гессе Демиан аудиокнига",
    "Стефан Цвейг Смятение чувств аудиокнига",
    "Станислав Лем Фиаско аудиокнига",
    "Станислав Лем Насморк аудиокнига",
    "Жюль Верн Михаил Строгов аудиокнига",
    "Джек Лондон Время не ждет аудиокнига"
]

results = []

def search_yt(query):
    url = f"https://www.youtube.com/results?search_query={urllib.parse.quote(query)}"
    req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
    try:
        html = urllib.request.urlopen(req).read().decode('utf-8')
        data_match = re.search(r'var ytInitialData = ({.*?});</script>', html)
        if data_match:
            data = json.loads(data_match.group(1))
            contents = data.get('contents', {}).get('twoColumnSearchResultsRenderer', {}).get('primaryContents', {}).get('sectionListRenderer', {}).get('contents', [])
            items_found = 0
            for c in contents:
                items = c.get('itemSectionRenderer', {}).get('contents', [])
                for item in items:
                    if items_found >= 5: break
                    video = item.get('videoRenderer')
                    if video:
                        title = video.get('title', {}).get('runs', [{}])[0].get('text', '')
                        vid_id = video.get('videoId')
                        duration = video.get('lengthText', {}).get('simpleText', '')
                        author = video.get('ownerText', {}).get('runs', [{}])[0].get('text', '')
                        if "аудиокнига" in title.lower() or "читает" in title.lower():
                            results.append({
                                'query': query,
                                'type': 'video',
                                'title': title,
                                'url': f"https://www.youtube.com/watch?v={vid_id}",
                                'duration': duration,
                                'author': author
                            })
                            items_found += 1
                    playlist = item.get('playlistRenderer')
                    if playlist:
                        title = playlist.get('title', {}).get('simpleText', '')
                        pid = playlist.get('playlistId')
                        count = playlist.get('videoCount', '')
                        author = playlist.get('shortBylineText', {}).get('runs', [{}])[0].get('text', '')
                        if "аудиокнига" in title.lower() or "часть" in title.lower() or "фиаско" in title.lower():
                            results.append({
                                'query': query,
                                'type': 'playlist',
                                'title': title,
                                'url': f"https://www.youtube.com/playlist?list={pid}",
                                'count': count,
                                'author': author
                            })
                            items_found += 1
    except Exception as e:
        pass

for q in queries:
    search_yt(q)

with open('yt_res.json', 'w', encoding='utf-8') as f:
    json.dump(results, f, ensure_ascii=False, indent=2)

