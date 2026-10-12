"""Deterministically complete the four one-week simulated CSV inputs.

The added fields are interface examples only. All people, institutions and
values remain synthetic and must not be treated as production definitions.
"""
from __future__ import annotations

import csv
from datetime import datetime
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "sample_data"


def read_csv(name: str):
    path = DATA / name
    with path.open("r", encoding="utf-8-sig", newline="") as fh:
        return path, list(csv.DictReader(fh))


def write_csv(path: Path, rows, added_fields):
    if not rows:
        return
    fields = list(rows[0])
    for field in added_fields:
        if field not in fields:
            fields.append(field)
    with path.open("w", encoding="utf-8-sig", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=fields, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def normalized_date(value: str) -> str:
    for fmt in ("%Y/%m/%d", "%Y-%m-%d", "%Y-%m-%d %H:%M"):
        try:
            return datetime.strptime(value, fmt).strftime("%Y-%m-%d")
        except ValueError:
            continue
    return value


def pathogen(diagnosis: str):
    mapping = (
        ("流感", "FLU-A", "甲型流感病毒"),
        ("新冠", "SARS-COV-2", "新型冠状病毒"),
        ("合胞", "RSV", "呼吸道合胞病毒"),
        ("支原体", "MP", "肺炎支原体"),
    )
    for keyword, code, name in mapping:
        if keyword in diagnosis:
            return code, name, "阳性"
    return "NOT-TESTED", "未检测", "未检测"


def enrich_hospital():
    path, rows = read_csv("simulated_medical_longitudinal_20261003_20261009.csv")
    for row in rows:
        day = normalized_date(row["就诊日期"])
        code, name, result = pathogen(row.get("西医诊断名称", ""))
        row.update({
            "人员脱敏键": row.get("身份证号", ""),
            "医疗机构名称": row.get("机构", ""),
            "病区编码": row.get("科室代码", ""),
            "病区名称": row.get("科室名称", ""),
            "就诊类型": "住院",
            "住院状态": "在院",
            "入院时间": f"{day} 08:00:00",
            "数据更新时间": f"{day} 18:00:00",
            "病原体编码": code,
            "病原体名称": name,
            "病原检测结果": result,
            "在院人数": "180",
        })
    write_csv(path, rows, ["人员脱敏键", "医疗机构名称", "病区编码", "病区名称", "就诊类型", "住院状态", "入院时间", "数据更新时间", "病原体编码", "病原体名称", "病原检测结果", "在院人数"])


def enrich_care_home():
    path, rows = read_csv("simulated_care_home_longitudinal_20261003_20261009.csv")
    for row in rows:
        day = normalized_date(row["入院时间"])
        code, name, result = pathogen(row.get("诊断名称", "") or row.get("入院诊断", ""))
        beds = int(float(row.get("养老床位数") or 100))
        row.update({
            "人员脱敏键": row.get("身份证号", ""),
            "数据更新时间": f"{day} 18:30:00",
            "在住人数": str(round(beds * 0.8)),
            "事件类型": "诊断事件",
            "病原体编码": code,
            "病原体名称": name,
            "病原检测结果": result,
            "入住开始日期": day,
            "入住结束日期": "",
        })
    write_csv(path, rows, ["人员脱敏键", "数据更新时间", "在住人数", "事件类型", "病原体编码", "病原体名称", "病原检测结果", "入住开始日期", "入住结束日期"])


def enrich_school():
    path, rows = read_csv("simulated_school_longitudinal_20261003_20261009.csv")
    class_codes = {}
    for row in rows:
        key = (row.get("学校编码", ""), row.get("班级", ""))
        class_codes.setdefault(key, f"{key[0]}-C{len(class_codes) + 1:02d}")
        day = normalized_date(row["日期"])
        holiday = row.get("是否休假日") == "是"
        row.update({
            "班级编码": class_codes[key],
            "在册人数": "40",
            "监测人数": "40",
            "缺勤人数": "1",
            "症状人数": "1",
            "数据更新时间": f"{day} 16:30:00",
            "教学日类型": "休假日" if holiday else "正常教学日",
            "是否补录": "否",
        })
    write_csv(path, rows, ["班级编码", "在册人数", "监测人数", "缺勤人数", "症状人数", "数据更新时间", "教学日类型", "是否补录"])


def enrich_market():
    path, rows = read_csv("simulated_market_longitudinal_20261003_20261009.csv")
    for row in rows:
        day = normalized_date(row["统计日期"])
        weekday = datetime.strptime(day, "%Y-%m-%d").weekday() < 5
        code, name, result = pathogen(row.get("诊断名称", ""))
        row.update({
            "报告单元类型": "日汇总",
            "从业人员脱敏键": "不适用-日汇总",
            "从业人员总数": "120",
            "重症标记": "否",
            "病原体编码": code,
            "病原体名称": name,
            "病原检测结果": result,
            "固定上报时间": "17:00",
            "是否工作日": "是" if weekday else "否",
            "更新状态": "按时",
        })
    write_csv(path, rows, ["报告单元类型", "从业人员脱敏键", "从业人员总数", "重症标记", "病原体编码", "病原体名称", "病原检测结果", "固定上报时间", "是否工作日", "更新状态"])


if __name__ == "__main__":
    enrich_hospital()
    enrich_care_home()
    enrich_school()
    enrich_market()
    print("completed simulated CSV fields")
