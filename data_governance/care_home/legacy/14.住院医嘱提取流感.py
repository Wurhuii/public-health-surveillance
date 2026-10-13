import pandas as pd
INPUT_FILE=[r"D:\Users\YCJK\Desktop\20260527\20260527\20260920新数据结果\20260928\result\4.入住期间诊疗数据\住院医嘱202008-20221231_clean_in_facility.csv",
            r"D:\Users\YCJK\Desktop\20260527\20260527\20260920新数据结果\20260928\result\4.入住期间诊疗数据\住院医嘱2023-20260531_clean_in_facility.csv"]
OUTPUT_RAW=r"D:\Users\YCJK\Desktop\20260527\20260527\20260920新数据结果\20260928\result\14.1ip_drug_flu_raw.csv"
OUTPUT_DAILY=r"D:\Users\YCJK\Desktop\20260527\20260527\20260920新数据结果\20260928\result\14.2ip_drug_flu_daily.csv"
OUTPUT_7d=r"D:\Users\YCJK\Desktop\20260527\20260527\20260920新数据结果\20260928\result\14.3ip_drug_flu_7d.csv"
CHUNKSIZE=500000

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
result_list=[]
for file in INPUT_FILE:
    print("\n正在处理",file)
    for df in pd.read_csv(
        file,
        dtype=str,
        low_memory=False,
        chunksize=CHUNKSIZE
    ):
        df=df[
            df["yizhuxiangmuleibie"]
            .fillna("")
            .astype(str)
            =="药品类医嘱"
        ].copy()
        if len(df)==0:
            continue
        drug=(
            df["yizhuxiangmu"]
            .fillna("")
            .astype(str)
            .str.strip()
        )
        df["flu_drug_name"]=""
        for name,pattern in DRUG_RULES.items():
            mask=drug.str.contains(
               pattern,
               regex=True,
               case=False,
               na=False
           )

            df.loc[mask,"flu_drug_name"]=name

        df=df[df["flu_drug_name"]!=""].copy()
        if len(df)>0:
            result_list.append(df)

flu_raw=pd.concat(result_list,ignore_index=True)
flu_raw=flu_raw.drop_duplicates().copy()
flu_raw["event_date"]=pd.to_datetime(
    flu_raw["event_date"],
    errors="coerce"
).dt.normalize()

flu_raw=flu_raw.dropna(
    subset=["local_id","event_date"]
)
flu_raw["source"]="ip_drug"
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