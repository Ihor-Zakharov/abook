import urllib.request
import re
import json
import urllib.parse

query = "Михаил Строгов аудиокнига Жюль Верн"
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
                    print(f"TITLE: {title} | DUR: {duration} | URL: https://www.youtube.com/watch?v={vid_id}")
                playlist = item.get('playlistRenderer')
                if playlist:
                    title = playlist.get('title', {}).get('simpleText', '')
                    pid = playlist.get('playlistId')
                    count = playlist.get('videoCount', '')
                    print(f"PLAYLIST: {title} | COUNT: {count} | URL: https://www.youtube.com/playlist?list={pid}")
except Exception as e:
    pass

