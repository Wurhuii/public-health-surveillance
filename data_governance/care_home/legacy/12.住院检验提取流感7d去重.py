import pandas as pd
import re
import unicodedata
INPUT_FILE=r"D:\Users\YCJK\Desktop\20260527\20260527\20260920新数据结果\20260928\result\11.2ip_lab_11类病原体候选记录.csv"
OUTPUT_RAW=r"D:\Users\YCJK\Desktop\20260527\20260527\20260920新数据结果\20260928\result\12.1ip_lab_flu_raw.csv"
OUTPUT_DAILY=r"D:\Users\YCJK\Desktop\20260527\20260527\20260920新数据结果\20260928\result\12.2ip_lab_flu_daily.csv"
OUTPUT_7d=r"D:\Users\YCJK\Desktop\20260527\20260527\20260920新数据结果\20260928\result\12.3ip_lab_flu_7d.csv"
VALUE_COL="jianyanjieguoshuzhi"
DESC_COL="jianyanjieguomiaoshu"
CODE_COL="jianyanjieguodaima"
PATHOGEN_COL="识别病原体名称"
df=pd.read_csv(INPUT_FILE,dtype=str,low_memory=False)
df.columns=df.columns.str.strip().str.lower()

df["event_date"]=pd.to_datetime(
        df["event_date"],
    errors="coerce"
    ).dt.normalize()
#======提取流感================
df=df[pd.to_numeric(df["流感病毒"],errors="coerce")==1].copy()
print("流感相关记录",len(df))

value=(df["jianyanjieguoshuzhi"].fillna("").astype(str).str.strip())
desc=(df["jianyanjieguomiaoshu"].fillna("").astype(str).str.strip())
code=(df["jianyanjieguodaima"].fillna("").astype(str).str.strip())

value_yang=value.str.contains("阳",regex=False)
value_yin=value.str.contains(r"阴|未检出|未发现|neg|negative",regex=False)

desc_yang=desc.str.contains("阳",regex=False)
desc_yin=desc.str.contains(r"阴|未检出|未发现|neg|negative",regex=False)

code_2=code.isin(["2","2.0"])
positive_mask=(
    value_yang
    |(
    ~value_yang
    &~value_yin
    &desc_yang
    )
    |(~value_yang
    &~value_yin
    &~desc_yang
    &code_2
    )
)


#===========提取流感阳性raw===========
flu_raw=df[positive_mask].copy()
flu_raw=flu_raw.dropna(
    subset=["local_id","event_date"]
)
flu_raw["是否阳性"]=1
flu_raw["source"]="ip_lab"
flu_raw["evidence_type"]="LAB"
flu_raw["disease"]="influenza"
flu_raw["pathogen"]="influenza"
print("\n流感阳性raw记录数",len(flu_raw))
print("涉及老人",flu_raw["local_id"].nunique())
flu_raw.to_csv(OUTPUT_RAW,index=False,encoding="utf-8-sig",date_format="%Y-%m-%d")
def join_unique(x):
    x=x.dropna().astype(str).str.strip()
    x=x[(x!="")&(x.str.lower()!="nan")]
    return ";".join(pd.unique(x))
key=[
    "local_id",
    "event_date"
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
flu_daily.to_csv(OUTPUT_DAILY,index=False,encoding="utf-8-sig",date_format="%Y-%m-%d")
if len(flu_daily)==0:
    print("没有流感阳性daily事件，停止7d去重")
    raise SystemExit


flu_daily=flu_daily.sort_values(
    ["local_id","event_date"]
).reset_index(drop=True)

def make_episode(g):
    episode_no=1
    start_date=None
    episode=[]

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
    .groupby(
        ["local_id"],
        group_keys=False
    )
    .apply(make_episode)
    .reset_index(drop=True)
)

episode_key=[
    "local_id",
    "episode_no"
]
episode_agg={
    c:join_unique
    for c in flu_7d.columns
    if c not in episode_key+["event_date"]
}
episode_agg["event_date"]="min"


flu_7d=(
    flu_7d
    .groupby(
        episode_key,
        dropna=False,
        as_index=False
    )
    .agg(episode_agg)
)

print("\n===========7日去重后=========")
print("7日流感事件数",len(flu_7d))
print("涉及老人数",flu_daily["local_id"].nunique())
flu_7d.to_csv(
    OUTPUT_7d,
    index=False,
    encoding="utf-8-sig",
    date_format="%Y-%m-%d"
)





