import pandas as pd
INPUT_FILE=r"D:\Users\YCJK\Desktop\20260527\20260527\20260920新数据结果\20260928\result\4.入住期间诊疗数据\门诊处方明细_clean_in_facility.csv"
OUTPUT_RAW=r"D:\Users\YCJK\Desktop\20260527\20260527\20260920新数据结果\20260928\result\13.1op_drug_flu_raw.csv"
OUTPUT_DAILY=r"D:\Users\YCJK\Desktop\20260527\20260527\20260920新数据结果\20260928\result\13.2op_drug_flu_daily.csv"
OUTPUT_7d=r"D:\Users\YCJK\Desktop\20260527\20260527\20260920新数据结果\20260928\result\13.3op_drug_flu_7d.csv"
DRUG_COL="yaowumingcheng"
df=pd.read_csv(INPUT_FILE,dtype=str,low_memory=False)
print("门诊处方记录数",len(df))
df["event_date"]=pd.to_datetime(df["event_date"],
                                errors="coerce").dt.normalize()
drug=(
    df[DRUG_COL]
    .fillna("")
    .astype(str)
    .str.strip()
)

DRUG_RULES={
    "奥司他韦":
    r"奥司他韦|达菲(?!林大)|可威|奥尔菲|"
    r"oseltamivir|tamiflu",

    "帕拉米韦":
    r"帕拉米韦|力纬|"
    r"peramivir",

    "扎那米韦":
    r"扎那米韦|依乐韦|瑞乐沙|"
    r"zanamivir|relenza",

    "玛巴洛沙韦":
    r"玛巴洛沙韦|速福达|"
    r"baloxavir|xofluza",

    "法维拉韦":
    r"法维拉韦|海正力特|"
    r"favipiravir|avigan",

    "阿比多尔":
    r"阿比多尔|恩威力克舒|"
    r"arbidol"
}

df["flu_drug_name"]=""
for name,pattern in DRUG_RULES.items():
    mask=drug.str.contains(
        pattern,
        regex=True,
        case=False,
        na=False
    )

    df.loc[mask,"flu_drug_name"]=name

df["flu_drug"]=(
    df["flu_drug_name"]!=""
).astype("int8")

flu_raw=df[
    df["flu_drug"]==1
].copy()
flu_raw=flu_raw.dropna(
    subset=["local_id","event_date"]
)
flu_raw["source"]="op_drug"
flu_raw["evidence_type"]="DRUG"
flu_raw["disease"]="influenza"
print("\n流感处方raw记录数",len(flu_raw))
print("涉及老人",flu_raw["local_id"].nunique())
print("\n各类流感药物记录数")
print(flu_raw["flu_drug_name"].value_counts())
flu_raw.to_csv(OUTPUT_RAW,
               index=False,
               encoding="utf-8-sig",
               date_format="%Y-%m-%d")

def join_unique(x):
    x=x.dropna().astype(str).str.strip()
    x=x[
        (x!="")
        &(x.str.lower()!="nan")
    ]
    return ";".join(pd.unique(x))
key=[
    "local_id",
    "event_date",
    "r_facility_code",
    "r_facility_name"
]
agg={
    c:join_unique
    for c in flu_raw.columns
    if c not in key
}
flu_daily=(
    flu_raw
    .groupby(key,dropna=False,as_index=False)
    .agg(agg)
)
print("flu daily事件",len(flu_daily))

flu_daily.to_csv(OUTPUT_DAILY,
                 index=False,
                 encoding="utf-8-sig",
                 date_format="%Y-%m-%d"
                 )
if len(flu_daily)==0:
    print("没有流感药物事件")
    raise SystemExit

flu_daily=flu_daily.sort_values(
    ["local_id","event_date"]
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
flu_7d=(
    flu_daily
    .groupby("local_id",group_keys=False)
    .apply(make_episode)
    .reset_index(drop=True)
)
episode_key=["local_id","episode_no"]
episode_agg={
    c:join_unique
    for c in flu_7d.columns
    if c not in episode_key+["event_date"]
}
episode_agg["event_date"]="min"
flu_7d=(
    flu_7d
    .groupby(episode_key,dropna=False,as_index=False)
    .agg(episode_agg)
)
print("flu7天独立事件",len(flu_7d))
print("\n7天去重后各药品")
print(flu_7d["flu_drug_name"].value_counts())
flu_7d.to_csv(
    OUTPUT_7d,
    index=False,
    encoding="utf-8-sig",
    date_format="%Y-%m-%d"
)