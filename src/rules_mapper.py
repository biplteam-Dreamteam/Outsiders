from typing import Any


def label_ticket(item: dict[str, Any], text: str) -> tuple[str, str]:
    kind = item.get("kind", "complaint")
    text_lower = text.lower()
    img_cnt = item.get("images_count", 0) or 0
    raw_refs = str(item.get("rule_refs_raw", "")).lower()
    violation = str(item.get("violation", "")).lower()
    verdict = str(item.get("verdict", "")).lower()

    has_evidence = img_cnt > 0 or any(
        w in text_lower
        for w in ["скрин", "видео", "фрапс", "пруф", "дәлел", "skrin", "<url>", "доки"]
    )

    if kind == "complaint":
        if (
            "3.4" in raw_refs
            or "3.4" in violation
            or "appeal" in verdict
            or "не согласен с наказанием" in text_lower
            or "жалоба на админ" in text_lower
            or "мут без причины" in text_lower
            or "администратор" in text_lower
            or "админ" in text_lower
            or "әкімші" in text_lower
            or "administrator" in text_lower
        ):
            cat = "complaint.admin"
        elif (
            "5.2" in raw_refs
            or "5.2" in violation
            or any(
                w in text_lower
                for w in [
                    "чит",
                    "софт",
                    "аим",
                    "вх",
                    "рванка",
                    "бот",
                    "кликер",
                    "cheat",
                    "soft",
                    "aimbot",
                ]
            )
        ):
            cat = "complaint.cheat"
        elif (
            "2.3" in raw_refs
            or "4.4" in raw_refs
            or "2.3" in violation
            or "4.4" in violation
            or any(
                w in text_lower
                for w in [
                    "реклам",
                    "продам акк",
                    "продажа вирт",
                    "вирты",
                    "за реал",
                    "куплю вирт",
                ]
            )
        ):
            cat = "complaint.rmt_ads"
        elif (
            "4.1" in raw_refs
            or "4.2" in raw_refs
            or "4.1" in violation
            or "4.2" in violation
            or any(
                w in text_lower
                for w in [
                    "обман",
                    "скам",
                    "развод",
                    "вымогат",
                    "украл машину",
                    "не вернул",
                    "обманул",
                ]
            )
        ):
            cat = "complaint.scam"
        elif (
            "5.3" in raw_refs
            or "5.4" in raw_refs
            or "gz" in raw_refs
            or "зз" in raw_refs
            or "5.3" in violation
            or "5.4" in violation
            or "gz" in violation
            or any(
                w in text_lower
                for w in [
                    "дм",
                    "дб",
                    "ск",
                    "тк",
                    "убил",
                    "урон",
                    "нонрп",
                    "nonrp",
                    "зелен",
                    "zz",
                ]
            )
        ):
            cat = "complaint.dm"
        elif (
            "2.1" in raw_refs
            or "2.4" in raw_refs
            or "2.6" in raw_refs
            or "2.1" in violation
            or "2.4" in violation
            or "2.6" in violation
            or any(
                w in text_lower
                for w in ["оск", "родн", "мат", "упом", "токсик", "мама", "шешен"]
            )
        ):
            cat = "complaint.insult"
        elif verdict in ["invalid_format", "need_evidence"] and not has_evidence:
            cat = "complaint.invalid"
        else:
            cat = "complaint.other"
    else:
        # report
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
            ]
        ):
            cat = "report.payment"
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
            ]
        ):
            cat = "report.account"
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
            ]
        ):
            cat = "report.help"
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
            ]
        ):
            cat = "report.complaint"
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
            ]
        ):
            cat = "report.question"
        else:
            cat = "report.offtopic"

    # Priority mapping
    # p0: Взлом или потеря доступа к аккаунту, платежи, массовый баг, угрозы вне игры
    if (
        cat == "report.payment"
        or (
            cat == "report.account"
            and any(w in text_lower for w in ["взлом", "украли", "пароль", "hacked"])
        )
        or "2.6" in raw_refs
    ):
        priority = "p0"
    # p1: Читы, мошенничество с крупным имуществом, реклама RMT, жалобы с доказательствами
    elif cat in ["complaint.cheat", "complaint.scam", "complaint.rmt_ads"]:
        priority = "p1"
    elif kind == "complaint" and not has_evidence:
        # complaints without evidence are p3 according to taxonomy.json
        priority = "p3"
    elif kind == "complaint" and cat in [
        "complaint.insult",
        "complaint.dm",
        "complaint.admin",
        "complaint.other",
    ]:
        # Standard complaints with evidence
        priority = "p2"
    elif cat == "report.complaint":
        priority = "p2"
    else:
        # report.question, report.help, report.offtopic, complaint.invalid
        priority = "p3"

    return cat, priority
