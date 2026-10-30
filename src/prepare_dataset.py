import csv
import gzip
import json
import os
import sys
import time
from collections import Counter

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from src.preprocessor import normalize_cp1251_kz

TAXONOMY_PATH = "taxonomy.json"
TRAIN_DATA_PATH = "tickets_train.jsonl.gz"
OUTPUT_CSV_PATH = os.path.join("data", "train_labeled.csv")


def load_taxonomy(path: str = TAXONOMY_PATH) -> dict:
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def pseudo_label_ticket(item: dict, clean_text: str, tax_cats: set) -> tuple[str, str]:
    """
    Эвристическая разметка тикета на category и priority на основе
    полей kind, violation, punishment, rule_refs_raw, images_count и сообщений.
    """
    kind = item.get("kind", "complaint")
    violation = str(item.get("violation") or "").strip().lower()
    punishment = str(item.get("punishment") or "").strip().lower()
    verdict = str(item.get("verdict") or "").strip().lower()
    raw_refs = str(item.get("rule_refs_raw") or "").strip().lower()
    images_count = int(item.get("images_count") or 0)
    text_lower = clean_text.lower().replace("ё", "е")

    has_evidence = images_count > 0 or any(
        w in text_lower
        for w in [
            "скрин",
            "видео",
            "фрапс",
            "пруф",
            "дәлел",
            "skrin",
            "<url>",
            "доки",
            "доказательств",
        ]
    )

    category = None

    # ==========================================
    # 1. COMPLAINT LABELING
    # ==========================================
    if kind == "complaint":
        # 1.1 Check Admin complaints / appeals
        if (
            "3.4" in violation
            or "3.4" in raw_refs
            or "жалоба на администратор" in text_lower
            or "жалоба на админ" in text_lower
            or "мут без причины" in text_lower
            or "деморган без причины" in text_lower
            or "не согласен с решением" in text_lower
            or "не согласен с вердиктом" in text_lower
            or "не согласна с решением" in text_lower
        ):
            category = "complaint.admin"

        # 1.2 Check Cheats / стороннее ПО (Rule 5.2)
        elif (
            "5.2" in violation
            or "5.2" in raw_refs
            or any(
                w in violation
                for w in ["чит", "софт", "аим", "вх", "cheat", "soft", "aim", "рванка"]
            )
            or any(
                w in text_lower
                for w in [
                    "чит",
                    "читы",
                    "софт",
                    "аим",
                    "вх",
                    "рванка",
                    "бот",
                    "кликер",
                    "спидхак",
                    "cheat",
                    "soft",
                    "aimbot",
                ]
            )
        ):
            category = "complaint.cheat"

        # 1.3 Check Scam / мошенничество / махинации (Rules 4.1, 4.2)
        elif (
            "4.1" in violation
            or "4.2" in violation
            or "4.1" in raw_refs
            or "4.2" in raw_refs
            or any(
                w in violation
                for w in ["скам", "обман", "развод", "махинац", "мошенничеств"]
            )
            or any(
                w in text_lower
                for w in [
                    "скам",
                    "обман",
                    "развод",
                    "махинаци",
                    "кинул на деньги",
                    "перевел деньги",
                    "вымогает",
                ]
            )
        ):
            category = "complaint.scam"

        # 1.4 Check RMT / Реклама (Rules 2.3, 4.4)
        elif (
            "2.3" in violation
            or "4.4" in violation
            or "2.3" in raw_refs
            or "4.4" in raw_refs
            or any(
                w in violation
                for w in [
                    "реклам",
                    "пиар",
                    "продажа вирт",
                    "покупка вирт",
                    "вирты за реал",
                ]
            )
            or any(
                w in text_lower
                for w in [
                    "реклам",
                    "продам акк",
                    "продажа вирт",
                    "вирты",
                    "за реал",
                    "куплю вирт",
                    "продам вирт",
                ]
            )
        ):
            category = "complaint.rmt_ads"

        # 1.5 Check Insult / Токсичность / Оскорбления (Rules 2.1, 2.4, 2.6)
        elif (
            "2.1" in violation
            or "2.4" in violation
            or "2.6" in violation
            or "2.1" in raw_refs
            or "2.4" in raw_refs
            or "2.6" in raw_refs
            or any(
                w in violation
                for w in ["оск", "оскорб", "упом", "мат", "токсик", "розжиг", "расизм"]
            )
            or any(
                w in text_lower
                for w in [
                    "оск",
                    "оскорб",
                    "упом",
                    "родных",
                    "родни",
                    "мать",
                    "родител",
                    "неадекват",
                    "неадыкват",
                    "мат",
                    "матер",
                    "обзыва",
                    "haromi",
                    "harom",
                    "боқтау",
                    "боқтық",
                    "балағат",
                    "расизм",
                    "национальн",
                    "розжиг",
                    "межнац",
                    "транс",
                    "оскр",
                    "osk",
                ]
            )
            or any(
                w in punishment
                for w in ["мут", "mute", "блокировка чата", "блокировкой чата"]
            )
        ):
            category = "complaint.insult"

        # 1.6 Check DM / DB / SK / NonRP / Green Zone (Rules 5.3, 5.4, 1.1 GZ, 1.2 GZ)
        elif (
            "5.3" in violation
            or "5.4" in violation
            or "1.1" in violation
            or "1.2" in violation
            or "gz" in violation
            or "5.3" in raw_refs
            or "5.4" in raw_refs
            or "gz" in raw_refs
            or "зз" in raw_refs
            or any(
                w in violation
                for w in [
                    "dm",
                    "дм",
                    "дб",
                    "db",
                    "ск",
                    "sk",
                    "тк",
                    "tk",
                    "deathmatch",
                    "driveby",
                    "уход от рп",
                    "урп",
                    "нрп",
                ]
            )
            or any(
                w in text_lower
                for w in [
                    "дм",
                    "дб",
                    "ск",
                    "тк",
                    "dm",
                    "db",
                    "sk",
                    "tk",
                    "deathmatch",
                    "driveby",
                    "убил",
                    "урон",
                    "расстрел",
                    "нонрп",
                    "nonrp",
                    "уход от рп",
                    "урп",
                    "веревка",
                    "связал",
                    "зз",
                    "gz",
                    "зелен",
                ]
            )
            or any(
                w in punishment
                for w in ["деморган", "дмг", "jail", "джайл", "warn", "варн"]
            )
        ):
            category = "complaint.dm"

        # 1.7 Check Invalid complaints (no evidence or wrong format)
        elif (
            verdict in ["invalid_format", "need_evidence", "rejected"]
            and not has_evidence
        ):
            category = "complaint.invalid"

        # 1.8 Default complaint
        else:
            category = "complaint.other"

    # ==========================================
    # 2. REPORT LABELING
    # ==========================================
    else:
        # 2.1 Payments & Donate
        if any(
            w in text_lower
            for w in [
                "донат",
                "donate",
                "оплат",
                "плат",
                "гк",
                "деньги не пришли",
                "to'lov",
                "төлем",
                "pul tushmadi",
                "сатып алу",
                "чек",
                "пополнил",
            ]
        ):
            category = "report.payment"

        # 2.2 Account & Hacking / Lost access (Rule 1.4)
        elif any(
            w in text_lower
            for w in [
                "взлом",
                "аккаунт",
                "украли",
                "пароль",
                "пропал",
                "доступ",
                "потерял акк",
                "akkaunt",
                "hacked",
                "восстанов",
                "логин",
            ]
        ):
            category = "report.account"

        # 2.3 Help / Stuck / Teleport / Flip / Textures (Rule 3.1)
        elif any(
            w in text_lower
            for w in [
                "застрял",
                "вытащ",
                "переверн",
                "помог",
                "тп",
                "спавн",
                "текстур",
                "баг",
                "slap",
                "help",
                "qotib",
                "tushib",
                "пж вытащите",
                "застряла",
            ]
        ):
            category = "report.help"

        # 2.4 In-game complaint via report
        elif any(
            w in text_lower
            for w in [
                "дмит",
                "оскает",
                "чит",
                "наруша",
                "следите",
                "id ",
                "айди ",
                "помеха",
                "дм ",
                "оск ",
                "дб ",
                "таранит",
                "следите за",
            ]
        ):
            category = "report.complaint"

        # 2.5 Questions about mechanics
        elif any(
            w in text_lower
            for w in [
                "как ",
                "где ",
                "когда ",
                "сколько ",
                "почему ",
                "не могу ",
                "подскаж",
                "қалай",
                "қандай",
                "qanday",
                "how",
                "что делать если",
                "где находится",
                "как устроиться",
                "как получить",
            ]
        ):
            category = "report.question"

        # 2.6 Offtopic & Greetings
        else:
            category = "report.offtopic"

    # Double check category exists in taxonomy
    if category not in tax_cats:
        category = "complaint.other" if kind == "complaint" else "report.offtopic"

    # ==========================================
    # 3. PRIORITY LABELING (p0 .. p3)
    # ==========================================
    # p0: Critical (Payment, Account hack, Threat outside game)
    if (
        category == "report.payment"
        or (
            category == "report.account"
            and any(
                w in text_lower
                for w in ["взлом", "украли", "пароль", "hacked", "доступ"]
            )
        )
        or "2.6" in raw_refs
        or "2.6" in violation
    ):
        priority = "p0"

    # p1: High (Cheats, Scam, RMT Ads, or ban punishments)
    elif category in ["complaint.cheat", "complaint.scam", "complaint.rmt_ads"] or any(
        w in punishment
        for w in [
            "бан на 1",
            "бан на 3",
            "бан на 5",
            "бан на 7",
            "бан на 10",
            "бан на 15",
            "бан на 30",
            "пермбан",
            "блокировк",
        ]
    ):
        priority = "p1"

    # p3: Low (Questions, offtopic, help requests, complaints without evidence)
    elif category in [
        "report.question",
        "report.offtopic",
        "report.help",
        "complaint.invalid",
    ] or (kind == "complaint" and not has_evidence):
        priority = "p3"

    # p2: Normal (Insults, DM, violations with evidence)
    else:
        priority = "p2"

    return category, priority


def prepare_dataset():
    t0 = time.time()
    print("=" * 72)
    print("🚀 PREPARING PSEUDO-LABELED DATASET FROM TICKETS_TRAIN")
    print("=" * 72)

    os.makedirs(os.path.dirname(OUTPUT_CSV_PATH), exist_ok=True)
    taxonomy = load_taxonomy()
    tax_cats = {c["code"] for c in taxonomy.get("categories", [])}
    print(f"Loaded taxonomy with {len(tax_cats)} categories.")

    if not os.path.exists(TRAIN_DATA_PATH):
        raise FileNotFoundError(f"Source train dataset not found: {TRAIN_DATA_PATH}")

    cat_counter = Counter()
    prio_counter = Counter()
    total_written = 0

    with (
        gzip.open(TRAIN_DATA_PATH, "rt", encoding="utf-8") as f_in,
        open(OUTPUT_CSV_PATH, "w", newline="", encoding="utf-8") as f_out,
    ):
        writer = csv.writer(f_out)
        # Header
        writer.writerow(
            ["ticket_id", "kind", "text", "images_count", "category", "priority"]
        )

        # 1. Add seed taxonomy examples for strong supervision
        seed_count = 0
        for c in taxonomy.get("categories", []):
            code = c["code"]
            k = c.get("kind", "complaint")
            prio = (
                "p1"
                if code in ["complaint.cheat", "complaint.scam", "complaint.rmt_ads"]
                else ("p0" if code in ["report.payment", "report.account"] else "p2")
            )
            for ex in c.get("examples", []):
                for _ in range(5):  # repeat slightly for anchor weight
                    seed_count += 1
                    writer.writerow(
                        [
                            f"seed_{seed_count}",
                            k,
                            ex,
                            1 if k == "complaint" else 0,
                            code,
                            prio,
                        ]
                    )
                    cat_counter[code] += 1
                    prio_counter[prio] += 1
                    total_written += 1

        print(f"Added {seed_count} seed taxonomy anchor records.")

        # 2. Iterate through tickets_train.jsonl.gz
        for line in f_in:
            t = json.loads(line)
            t_id = t.get("ticket_id", f"tid_{total_written}")
            kind = t.get("kind", "complaint")

            player_msgs = [
                m.get("text", "")
                for m in t.get("messages", [])
                if m.get("role") == "player" or m.get("author") == "player"
            ]
            raw_text = " ".join(player_msgs).strip()
            clean_text = normalize_cp1251_kz(raw_text)

            raw_refs = str(t.get("rule_refs_raw") or "").strip()
            combined_text = f"{raw_refs} {clean_text}".strip()
            images_count = int(t.get("images_count") or 0)

            # Generate pseudo-labels
            cat, prio = pseudo_label_ticket(t, clean_text, tax_cats)

            writer.writerow([t_id, kind, combined_text, images_count, cat, prio])
            cat_counter[cat] += 1
            prio_counter[prio] += 1
            total_written += 1

    elapsed = time.time() - t0
    print(f"\n✅ Successfully prepared labeled dataset in {elapsed:.2f}s!")
    print(
        f"📁 Output file: {OUTPUT_CSV_PATH} ({os.path.getsize(OUTPUT_CSV_PATH) / (1024 * 1024):.2f} MB)"
    )
    print(f"📊 Total labeled samples: {total_written}")

    print("\n📈 Category Distribution:")
    for cat, cnt in cat_counter.most_common():
        pct = (cnt / total_written) * 100
        print(f"  • {cat:22s}: {cnt:6d} ({pct:5.2f}%)")

    print("\n🎯 Priority Distribution:")
    for prio, cnt in prio_counter.most_common():
        pct = (cnt / total_written) * 100
        print(f"  • {prio:5s}: {cnt:6d} ({pct:5.2f}%)")
    print("=" * 72)


if __name__ == "__main__":
    prepare_dataset()
