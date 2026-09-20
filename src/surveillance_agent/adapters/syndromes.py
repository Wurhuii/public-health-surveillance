from __future__ import annotations

from typing import Dict, List

SYNDROME_KEYWORDS: Dict[str, List[str]] = {
    "respiratory": [
        "流感", "感冒", "支气管", "肺炎", "上呼吸道", "下呼吸道",
        "慢阻肺", "慢性阻塞性肺", "哮喘", "呼吸道", "咽炎", "鼻炎",
        "咳嗽", "呼吸道合胞病毒", "流感样",
    ],
    "digestive": [
        "胃炎", "肠炎", "腹泻", "消化道", "胃溃疡", "痢疾", "诺如",
    ],
    "fever": [
        "发热", "发烧", "高热", "不明原因发热",
    ],
    "neuro": [
        "阿尔茨海默", "帕金森", "脑血管", "脑梗", "老年痴呆", "脑卒中", "脑炎",
    ],
    "cardio": [
        "冠心病", "心力衰竭", "高血压", "心肌", "心梗", "心绞痛",
    ],
}

SYNDROME_LABELS: Dict[str, str] = {
    "respiratory": "呼吸道",
    "digestive": "消化道",
    "fever": "发热",
    "neuro": "神经系统",
    "cardio": "心血管",
    "other": "其他",
}

# 互斥映射的优先级：一个事件同时命中多个症候群时，只归入第一个命中的。
# 呼吸道/消化道两大急性暴发症候群优先于泛化的"发热"桶；
# 发热作为急性信号又优先于本数据集中以慢病为主的神经/心血管桶。
# 保证同一病例只进入一条序列，避免重复计数。
SYNDROME_PRIORITY = ["respiratory", "digestive", "fever", "neuro", "cardio"]


def map_syndromes(diagnosis: str, symptoms: str = "") -> List[str]:
    text = f"{diagnosis} {symptoms}"
    for syndrome in SYNDROME_PRIORITY:
        if any(kw in text for kw in SYNDROME_KEYWORDS[syndrome]):
            return [syndrome]
    return ["other"]


def syndrome_label(code: str) -> str:
    return SYNDROME_LABELS.get(code, code)
