"""
TEST DIVERSE PLAYER SLANG AND REALISTIC TICKETS
Decentrathon 6.0 — Grand Mobile Support Copilot

Тестирует систему на разнообразный реальный сленг игроков Grand Mobile:
1. Застревание в текстурах (слап, спавн, автобазар)
2. Читы и софт (рванка, аимбот, ВЧ)
3. ДМ и ДБ ковшом (фрапс, провокация)
4. НонРП госники и взятки
5. НонРП развод и скам на автомобили
6. Финансы и донат (БП, чеки)
7. Взлом аккаунта и смена почты
8. Жалоба на админа и деморган
9. Литературный казахский язык
10. Казахский cp1251 кракозябры
11. Узбекский язык
12. Английский язык
"""

import sys
import os
import orjson

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

sys.path.insert(0, os.path.abspath("."))
from src.pipeline import SupportCopilotPipeline

def run_diverse_slang_test():
    pipeline = SupportCopilotPipeline()

    diverse_tickets = [
        {
            "name": "Застревание в текстурах (RP сленг)",
            "ticket": {
                "ticket_id": "slang_01",
                "kind": "report",
                "messages": [{"role": "player", "text": "Помогите застрял в текстурах около автобазара, слапните плиз или на спавн киньте"}],
                "images_count": 0
            }
        },
        {
            "name": "Рванка и читы на Воинской Части",
            "ticket": {
                "ticket_id": "slang_02",
                "kind": "complaint",
                "messages": [{"role": "player", "text": "Игрок Roma_Cheater юзает рванку и аимбот на складе ВЧ, всех разносит софтом, 5.2 ОП"}],
                "images_count": 1,
                "reported_nick": "Roma_Cheater"
            }
        },
        {
            "name": "ДБ ковшом и фрапс",
            "ticket": {
                "ticket_id": "slang_03",
                "kind": "complaint",
                "messages": [{"role": "player", "text": "ДБ ковшом на спавне Арзамаса игрок Danil_Voron, фрапс с /time прикрепил, накажите его"}],
                "images_count": 2,
                "reported_nick": "Danil_Voron"
            }
        },
        {
            "name": "НонРП коп и взятка",
            "ticket": {
                "ticket_id": "slang_04",
                "kind": "complaint",
                "messages": [{"role": "player", "text": "НонРП коп повесил 6 звезд без причины и вымогает взятку 50к, уход от рп"}],
                "images_count": 1
            }
        },
        {
            "name": "Обман на авторынке (Скам)",
            "ticket": {
                "ticket_id": "slang_05",
                "kind": "complaint",
                "messages": [{"role": "player", "text": "Меня кинули на авторынке, подкинули обмен БМВ М5 на копейку вместо гелика, верните машину"}],
                "images_count": 1
            }
        },
        {
            "name": "Донат на Боевой Пропуск (P0)",
            "ticket": {
                "ticket_id": "slang_06",
                "kind": "report",
                "messages": [{"role": "player", "text": "Купил донат на боевой пропуск 1500 рублей, деньги с Тинькофф списались а ГК не начислили, чек есть"}],
                "images_count": 1
            }
        },
        {
            "name": "Взлом аккаунта (P0)",
            "ticket": {
                "ticket_id": "slang_07",
                "kind": "report",
                "messages": [{"role": "player", "text": "Взломали мой аккаунт Azamat_Kz, сменили пароль и привязку почты, помогите восстановить доступ"}],
                "images_count": 0
            }
        },
        {
            "name": "Жалоба на администратора",
            "ticket": {
                "ticket_id": "slang_08",
                "kind": "complaint",
                "messages": [{"role": "player", "text": "Администратор посадил меня в деморган на 60 минут за ДМ, хотя там была провокация, пересмотрите вердикт"}],
                "images_count": 0
            }
        },
        {
            "name": "Казахский язык: көлік сатып алу",
            "ticket": {
                "ticket_id": "slang_09",
                "kind": "report",
                "messages": [{"role": "player", "text": "Сәлеметсіз бе! Автосалонда көлік сатып ала алмай жатырмын, ақшам бар бірақ қате шығады, көмектесіңізші"}],
                "server_lang": "kk"
            }
        },
        {
            "name": "Казахский язык: кракозябры cp1251",
            "ticket": {
                "ticket_id": "slang_10",
                "kind": "report",
                "messages": [{"role": "player", "text": "‘јлеметсіз бе! Кљмек керек, ќалай жҧмысќа орналасуѓа болады?"}],
                "region": "kz"
            }
        },
        {
            "name": "Узбекский язык: firibgarlik",
            "ticket": {
                "ticket_id": "slang_11",
                "kind": "complaint",
                "messages": [{"role": "player", "text": "Salom aka, o'yinda meni aldab ketishdi, moshinamni tortib oldi, skrin bor, jazolang"}],
                "server_lang": "uz",
                "images_count": 1
            }
        },
        {
            "name": "Английский язык: speedhack in green zone",
            "ticket": {
                "ticket_id": "slang_12",
                "kind": "complaint",
                "messages": [{"role": "player", "text": "Player BadGuy is speedhacking and trolling players inside the hospital green zone, proof attached"}],
                "images_count": 1,
                "reported_nick": "BadGuy"
            }
        }
    ]

    print("=" * 90)
    print("🎮 ТЕСТИРОВАНИЕ СИСТЕМЫ НА РЕАЛЬНЫЙ ИГРОВОЙ СЛЕНГ GRAND MOBILE (12 СЦЕНАРИЕВ)")
    print("=" * 90)

    for item in diverse_tickets:
        name = item["name"]
        ticket = item["ticket"]
        resp = pipeline.triage_ticket_sync(ticket)
        print(f"\n🔹 [{name}]")
        print(f"  Вход:    \"{ticket['messages'][0]['text'][:70]}...\"")
        print(f"  Триаж:   Язык: {resp['lang'].upper()} | Категория: {resp['category']} | Приоритет: {resp['priority']} | Human: {resp['needs_human']}")
        print(f"  Причины: {resp['reasons']}")
        print(f"  Цитаты:  {resp['draft_reply']['cited']}")
        print(f"  Черновик: \"{resp['draft_reply']['text'][:120]}...\"")

    print("\n" + "=" * 90)
    print("🏆 ВСЕ 12 СЦЕНАРИЕВ СЛЕНГА ИГРОКОВ УСПЕШНО РАЗОБРАНЫ БЕЗ СБОЕВ!")
    print("=" * 90)

if __name__ == "__main__":
    run_diverse_slang_test()
