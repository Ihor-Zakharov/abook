"""API helper for tests against an isolated `abook review --db` server."""
import json
import sys
import urllib.request

BASE = "http://127.0.0.1:8795"


def call(path, body=None, profile=None, method=None):
    h = {"Content-Type": "application/json"}
    if profile:
        h["X-Abook-Profile"] = str(profile)
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(BASE + path, data=data, headers=h, method=method or ("POST" if data else "GET"))
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return json.loads(r.read().decode())
    except urllib.error.HTTPError as e:
        return {"_status": e.code, **json.loads(e.read().decode() or "{}")}


# realistic sample answers for a second listener
SAMPLE = {
    "books_liked": [
        {"id": None, "author": "Эрих Мария Ремарк", "title": "Три товарища", "why": ["герои", "атмосфера", "эмоции"],
         "rating": 10, "comment": "плакала в конце, дружба и обречённость"},
        {"id": None, "author": "Габриэль Гарсиа Маркес", "title": "Сто лет одиночества", "why": ["мир/сеттинг", "язык/стиль", "реализм/абсурд"],
         "rating": 9, "comment": ""},
        {"id": None, "author": "Агата Кристи", "title": "Десять негритят", "why": ["сюжет", "напряжение", "концовка"],
         "rating": 8, "comment": "не угадала убийцу"},
        {"id": None, "author": "Михаил Булгаков", "title": "Мастер и Маргарита", "why": ["юмор", "мир/сеттинг", "философия"],
         "rating": 10, "comment": ""},
        {"id": None, "author": "Рэй Брэдбери", "title": "Вино из одуванчиков", "why": ["атмосфера", "язык/стиль"],
         "rating": 9, "comment": "лето детства"},
    ],
    "books_disliked": [
        {"id": None, "author": "Джеймс Джойс", "title": "Улисс", "why": ["слишком сложно", "скучно"], "rating": 3, "comment": "бросила на 100-й странице"},
        {"id": None, "author": "Пауло Коэльо", "title": "Алхимик", "why": ["банально", "морализаторство"], "rating": 4, "comment": ""},
    ],
    "prefs": {"genres": ["классика", "детектив", "магический реализм", "психологическая проза", "юмор/сатира"],
              "genres_text": "магический реализм", "length": ["среднее (2–10 ч)"], "format": ["аудиокнига", "радиоспектакль"],
              "lang": ["ru", "uk"], "listen": ["дорога", "домашние дела", "перед сном"], "narrators": "Клюквин, Ерисанова"},
    "films": [{"title": "Амели", "why": ["атмосфера", "музыка", "визуал"], "rating": 10, "comment": ""},
              {"title": "Отель «Гранд Будапешт»", "why": ["визуал", "юмор"], "rating": 9, "comment": ""},
              {"title": "Достать ножи", "why": ["сюжет", "твист"], "rating": 8, "comment": ""}],
    "film_genres": ["комедия", "детектив", "драма"],
    "series": [{"title": "Шерлок (BBC)", "why": ["персонажи", "диалоги", "твист"], "rating": 9, "comment": ""},
               {"title": "Чернобыль", "why": ["атмосфера", "идея"], "rating": 10, "comment": "тяжело, но гениально"}],
    "series_genres": ["детектив", "мини-сериал"],
    "travel": {"been": ["Италия", "Португалия", "Грузия", "Львов"], "want": ["Япония", "Исландия"],
               "types": ["архитектура", "еда", "история", "тихие места"], "pace": "спокойно", "text": "люблю маленькие города у моря"},
    "music": {"chips": ["джаз", "инди", "саундтреки"], "text": "Ян Тирсен, Norah Jones"},
    "interests": {"chips": ["психология", "искусство", "история"], "text": "керамика, итальянский язык"},
    "about": {"name": "Марина", "age": "34", "education": ["высшее"], "education_text": "филология",
              "profession": "UX-дизайнер", "location": "Киев, Украина", "family": ["в браке", "есть дети"], "family_text": "сын 6 лет"},
    "worldview": {"faith": {"v": "ищу, сомневаюсь", "text": ""}, "outlook": {"v": "скорее оптимист", "text": ""},
                  "idea_story": {"v": "история", "text": "но чтобы оставалось послевкусие"},
                  "dark": {"v": "в меру", "text": "не люблю жестокость ради жестокости"}},
}

if __name__ == "__main__":
    print(json.dumps(call(sys.argv[1], json.loads(sys.argv[2]) if len(sys.argv) > 2 else None), ensure_ascii=False, indent=1)[:3000])
