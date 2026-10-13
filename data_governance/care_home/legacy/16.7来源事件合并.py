import pandas as pd
import os

from django.db.models.expressions import result
from multipledispatch.dispatcher import source

FILES={
    "门诊诊断":{"file":r"D:\Users\YCJK\Desktop\20260527\20260527\20260920新数据结果\20260928\result\5.2op_diagnosis_flu_daily.csv","source":"op_diagnosis","evidence_type":"op_ICD"},
    "住院诊断":{"file":r"D:\Users\YCJK\Desktop\20260527\20260527\20260920新数据结果\20260928\result\6.2ip_diagnosis_flu_daily.csv","source":"ip_diagnosis","evidence_type":"ip_ICD"},
    "ILI":{"file":r"D:\Users\YCJK\Desktop\20260527\20260527\20260920新数据结果\20260928\result\7.3ILI_daily.csv","source":"ili","evidence_type":"ILI"},
    "门诊检验":{"file":r"D:\Users\YCJK\Desktop\20260527\20260527\20260920新数据结果\20260928\result\10.2op_lab_flu_daily.csv","source":"op_lab","evidence_type":"op_LAB"},
    "住院检验":{"file":r"D:\Users\YCJK\Desktop\20260527\20260527\20260920新数据结果\20260928\result\12.2ip_lab_flu_daily.csv","source":"ip_lab","evidence_type":"ip_LAB"},
    "门诊药物":{"file":r"D:\Users\YCJK\Desktop\20260527\20260527\20260920新数据结果\20260928\result\13.2op_drug_flu_daily.csv","source":"op_drug","evidence_type":"op_DRUG"},
    "住院药物":{"file":r"D:\Users\YCJK\Desktop\20260527\20260527\20260920新数据结果\20260928\result\14.2ip_drug_flu_daily.csv","source":"ip_drug","evidence_type":"ip_DRUG"}
}

FILES_7d={
    "门诊诊断":{"file":r"D:\Users\YCJK\Desktop\20260527\20260527\20260920新数据结果\20260928\result\5.2op_diagnosis_flu_7d.csv","source":"op_diagnosis","evidence_type":"op_ICD"},
    "住院诊断":{"file":r"D:\Users\YCJK\Desktop\20260527\20260527\20260920新数据结果\20260928\result\6.2ip_diagnosis_flu_7d.csv","source":"ip_diagnosis","evidence_type":"ip_ICD"},
    "ILI":{"file":r"D:\Users\YCJK\Desktop\20260527\20260527\20260920新数据结果\20260928\result\7.3ILI_7d.csv","source":"ili","evidence_type":"ILI"},
    "门诊检验":{"file":r"D:\Users\YCJK\Desktop\20260527\20260527\20260920新数据结果\20260928\result\10.2op_lab_flu_7d.csv","source":"op_lab","evidence_type":"op_LAB"},
    "住院检验":{"file":r"D:\Users\YCJK\Desktop\20260527\20260527\20260920新数据结果\20260928\result\12.2ip_lab_flu_7d.csv","source":"ip_lab","evidence_type":"ip_LAB"},
    "门诊药物":{"file":r"D:\Users\YCJK\Desktop\20260527\20260527\20260920新数据结果\20260928\result\13.2op_drug_flu_7d.csv","source":"op_drug","evidence_type":"op_DRUG"},
    "住院药物":{"file":r"D:\Users\YCJK\Desktop\20260527\20260527\20260920新数据结果\20260928\result\14.2ip_drug_flu_7d.csv","source":"ip_drug","evidence_type":"ip_DRUG"}
}
DENOMINATOR_FILE=r"D:\Users\YCJK\Desktop\20260527\20260527\20260920新数据结果\20260928\result\2.2facility_daily_denominator.csv"
OUTPUT_DIR=r"D:\Users\YCJK\Desktop\20260527\20260527\20260920新数据结果\20260928\result"
START_DATE="2020-08-01"
END_DATE="2026-05-31"
os.makedirs(OUTPUT_DIR,exist_ok=True)
OUTPUT_LONG=os.path.join(
    OUTPUT_DIR,
    "16.1flu_7source_daily_long.csv"
)
OUTPUT_UNION_DAILY=os.path.join(
    OUTPUT_DIR,
    "16.2flu_union_daily.csv"
)
OUTPUT_UNION_7D=os.path.join(
    OUTPUT_DIR,
    "16.3flu_union_episode_7d.csv"
)
OUTPUT_PANEL=os.path.join(
    OUTPUT_DIR,
    "16.4flu_facility_day_panel.csv"
)

def join_unique(x):
    x=x.dropna().astype(str).str.strip()
    x=x[(x!="")
    &(x.str.lower()!="nan")]
    return ";".join(pd.unique(x))

def join_tokens(x):
    result=[]
    for value in x.dropna():
        for item in str(value).split(";"):
            item=item.strip()
            if item !="" and item not in result:
                result.append(item)
    return ";".join(result)
long_list=[]
for name,info in FILES.items():
    print("读取",name)
    df=pd.read_csv(
        info["file"],
        dtype=str,
        low_memory=False
    )
    df["event_date"]=pd.to_datetime(
        df["event_date"],
        errors="coerce"
    ).dt.normalize()
    df["source"]=info["source"]
    df["evidence_type"]=info["evidence_type"]
    temp=df[
        [
            "local_id",
            "event_date",
            "r_facility_code",
            "r_facility_name",
            "source",
            "evidence_type"
        ]
    ].copy()
    temp=temp.dropna(
        subset=[
            "local_id",
            "event_date",
            "r_facility_code"
        ]
    )
    temp=temp[
        (temp["event_date"]>=START_DATE)
        &(temp["event_date"]<=END_DATE)
    ]
    long_list.append(temp)

flu_long=pd.concat(
    long_list,
    ignore_index=True
)
flu_long=flu_long.drop_duplicates()
flu_long=flu_long.sort_values(
    ["local_id",
      "event_date",
     "source"]
).reset_index(drop=True)
print("\n==========7来源长表==========")
print("总记录数",len(flu_long))
print("人数",flu_long["local_id"].nunique())
print("机构数",flu_long["r_facility_code"].nunique())
print("\n各来源：")
print(flu_long["source"].value_counts())
flu_long.to_csv(OUTPUT_LONG,
                index=False,
                encoding="utf-8-sig",
                date_format="%Y-%m-%d")

union_daily=(
    flu_long
    .groupby(
        [
       "local_id",
      "event_date",
     "r_facility_code"
        ],
        as_index=False,
        dropna=False
    )
    .agg({
        "r_facility_name":join_unique,
        "source":join_tokens,
        "evidence_type":join_tokens
    })
)
union_daily["source_n"]=(
    union_daily["source"]
    .apply(
        lambda x:
        len(x.split(";"))
        if x!=""
        else 0
    )
)
print("\n=======union daily====")
print("union daily事件数",len(union_daily))
print("人数",union_daily["local_id"].nunique())

print("\n来源支持数量")
print(
    union_daily["source_n"]
    .value_counts()
    .sort_index()
)
union_daily.to_csv(
    OUTPUT_UNION_DAILY,
    index=False,
    encoding="utf-8-sig",
    date_format="%Y-%m-%d"
)

union_daily=union_daily.sort_values(
    [
        "local_id",
        "event_date"
    ]
).reset_index(drop=True)
def make_episode(g):
    episode_no=1
    start_date=None
    episode =[]

    for d in g["event_date"]:
        if start_date is None:
            start_date=d
        elif (d-start_date).days>7:
            episode_no+=1
            start_date=d

        episode.append(episode_no)
    g["episode_no"]=episode
    return g
union_episode=(
    union_daily
    .groupby("local_id",group_keys=False)
    .apply(make_episode)
    .reset_index(drop=True)
)

union_7d=(
    union_episode
    .groupby([
        "local_id",
        "episode_no"
    ],
        as_index=False
)
    .agg(
        episode_start=("event_date","min"),
        episode_end=("event_date","max"),
        r_facility_code=(
            "r_facility_code",
            join_unique),
        r_facility_name=(
            "r_facility_name",
            join_unique),
        source=(
            "source",
            join_tokens
        ),
        evidence_type=(
            "evidence_type",
            join_tokens
        ),
        event_day_n=(
            "event_date",
            "nunique"
        )
        )
    )
union_7d["source"]=(
    union_7d["source"]
    .apply(
        lambda x:
        len(x.split(";"))
        if x !=""
        else 0
    )
)
print("7天独立事件数",len(union_7d))
print("涉及人数",union_7d["local_id"].nunique())

union_7d.to_csv(
    OUTPUT_UNION_7D,
    index=False,
    encoding="utf-8-sig",
    date_format="%Y-%m-%d"
)
source_7d_list = []

for name, info in FILES_7D.items():

    df = pd.read_csv(
        info["file"],
        dtype=str,
        low_memory=False
    )

    df["event_date"] = pd.to_datetime(
        df["event_date"],
        errors="coerce"
    ).dt.normalize()

    df["source"] = info["source"]

    temp = df[
        [
            "local_id",
            "event_date",
            "r_facility_code",
            "source"
        ]
    ].copy()

    temp = temp.dropna(
        subset=[
            "local_id",
            "event_date",
            "r_facility_code"
        ]
    )

    temp = temp[
        (temp["event_date"] >= START_DATE)
        & (temp["event_date"] <= END_DATE)
    ]

    source_7d_list.append(temp)

source_7d = pd.concat(
    source_7d_list,
    ignore_index=True
)
source_count = (
    source_7d
    .groupby(
        [
            "r_facility_code",
            "event_date",
            "source"
        ]
    )["local_id"]
    .nunique()
    .unstack(fill_value=0)
    .reset_index()
)
source_count.columns.name=None
source_count=source_count.rename(columns={
    "r_facility_code":"facility_code",
    "event_date":"date",
    "op_diagnosis":"op_icd_1d",
    "ip_diagnosis":"ip_icd_1d",
    "ili":"ili_1d",
    "op_lab":"op_lab_1d",
    "ip_lab":"ip_lab_1d",
    "op_drug":"op_drug_1d",
    "ip_drug":"ip_drug_1d"
})

union_count=(
    union_7d
    .groupby(["r_facility_code","episode_start"])["local_id"]
    .nunique()
    .reset_index(name="union_1d")
    .rename(columns={
        "r_facility_code":"facility_code",
        "episode_start":"date"
    })
)
count=source_count.merge(
    union_count,
    on=["facility_code","date"],
    how="outer"
)
den=pd.read_csv(
    DENOMINATOR_FILE,
    dtype={"facility_code":str},
    low_memory=False
)
den["date"]=pd.to_datetime(
    den["date"],
    errors="coerce"
).dt.normalize()

panel=den.merge(
    count,
    on=["facility_code","date"],
    how="left"
)
cols=[
    "op_icd_1d",
    "ip_icd_1d",
    "ili_1d",
    "op_lab_1d",
    "ip_lab_1d",
    "op_drug_1d",
    "ip_drug_1d",
    "union_1d"
]
for col in cols:
    if col not in panel.columns:
        panel[col]=0
panel[cols]=panel[cols].fillna(0).astype(int)
panel=panel.sort_values(
    ["facility_code","date"]
).reset_index(drop=True)
panel.to_csv(
    OUTPUT_PANEL,
    index=False,
    encoding="utf-8-sig",
    date_format="%Y-%m-%d"
)
print("facility_day数",len(panel))
print("机构数",panel["facility_code"].nunique())
print("union_1d",panel["union_1d"].sum())