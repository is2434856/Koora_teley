"""اختبارات بسيطة للفلاتر. لا تتصل بTelegram."""

from dataclasses import dataclass

from filters import count_words, contains_forbidden_term, normalize_arabic


def main() -> None:
    assert normalize_arabic("تَفَاعُلآ") == "تفاعلا"
    assert contains_forbidden_term("ننشره في قناة المصدر الآن") == "قناة المصدر"
    assert contains_forbidden_term("شارك معنا") == "شارك"
    assert contains_forbidden_term("مباراة قوية") is None
    assert count_words("هذه رسالة تحتوي على ثماني كلمات كاملة هنا") == 8
    print("All filter tests passed.")


if __name__ == "__main__":
    main()
