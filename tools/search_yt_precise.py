import urllib.request
import re
import json
import urllib.parse
import sys

queries = [
    "Стефан Цвейг Смятение чувств",
    "Станислав Лем Фиаско аудиокнига",
    "Станислав Лем Насморк аудиокнига",
    "Джек Лондон Время не ждет аудиокнига",
    "Джек Лондон День пламенеет аудиокнига"
]

def search_yt(query):
    url = f"https://www.youtube.com/results?search_query={urllib.parse.quote(query)}"
    req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
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
                        if "смятение" in title.lower() or "фиаско" in title.lower() or "насморк" in title.lower() or "день пламенеет" in title.lower() or "время не ждет" in title.lower() or "время-не-ждет" in title.lower():
                            print(json.dumps({
                                'query': query,
                                'type': 'video',
                                'title': title,
                                'url': f"https://www.youtube.com/watch?v={vid_id}",
                                'duration': duration,
                                'author': author
                            }, ensure_ascii=False))
                    playlist = item.get('playlistRenderer')
                    if playlist:
                        title = playlist.get('title', {}).get('simpleText', '')
                        pid = playlist.get('playlistId')
                        count = playlist.get('videoCount', '')
                        author = playlist.get('shortBylineText', {}).get('runs', [{}])[0].get('text', '')
                        if "фиаско" in title.lower() or "насморк" in title.lower() or "смятение" in title.lower():
                            print(json.dumps({
                                'query': query,
                                'type': 'playlist',
                                'title': title,
                                'url': f"https://www.youtube.com/playlist?list={pid}",
                                'count': count,
                                'author': author
                            }, ensure_ascii=False))
    except Exception as e:
        pass

for q in queries:
    search_yt(q)

