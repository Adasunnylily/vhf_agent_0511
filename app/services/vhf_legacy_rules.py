from __future__ import annotations

import re


def legacy_repair_vhf_text(text: str) -> str:
    """Optional legacy regex fallback for demos without LLM correction."""
    resolved = text or ""
    replacements = [
        (r"什么中山交管", "宁波舟山交管"),
        (r"中山交管", "舟山交管"),
        (r"宁远[，, ]?眉山", "宁远梅山"),
        (r"宁远煤山", "宁远梅山"),
        (r"北龙二区", "北仑二期"),
        (r"北轮二期", "北仑二期"),
        (r"北仑两期", "北仑二期"),
        (r"通达七号泊位", "通达7号泊位"),
        (r"通达7号码头", "通达7号泊位"),
        (r"金唐南", "金塘南"),
        (r"黄牛角", "黄牛礁"),
        (r"马志锚地|马峙毛地", "马峙锚地"),
        (r"报个备", "报备"),
        (r"到了再说吧(?=，?你准备抛)", "到锚地再说吧"),
        (r"下一港大普", "下一港大浦"),
        (r"谢谢教官", "谢谢交管"),
        (r"现在\s*(?:159|幺五|一五|1五|15)", "湘远15"),
        (r"限\s*(?:幺五|一五|1五|15)", "湘远15"),
        (r"湘远\s*(?:幺五|一五|1五)", "湘远15"),
        (r"大榭集装箱码头一号泊位", "大榭集装箱码头1号泊位"),
        (r"散会", "再会"),
    ]
    for pattern, value in replacements:
        resolved = re.sub(pattern, value, resolved)

    resolved = re.sub(r"(?<=湘远15)靠左(?=，?大榭|大榭)", "靠妥", resolved)
    resolved = re.sub(r"宁波交管[，, ]?(湘远15)(?:[，, ]?请讲)?", r"宁波交管，\1叫。请讲", resolved)
    resolved = re.sub(r"(湘远15)靠妥[，, ]?(大榭)", r"\1靠妥\2", resolved)
    resolved = re.sub(r"([。！？])+", r"\1", resolved)
    return resolved.strip()
