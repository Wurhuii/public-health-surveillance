import pandas as pd
INPUT_FILE=r"D:\Users\YCJK\Desktop\20260527\20260527\20260920新数据结果\20260928\result\7.1ILI_all.csv"
OUTPUT_RAW=r"D:\Users\YCJK\Desktop\20260527\20260527\20260920新数据结果\20260928\result\7.2ILI_raw.csv"
OUTPUT_DAILY=r"D:\Users\YCJK\Desktop\20260527\20260527\20260920新数据结果\20260928\result\7.3ILI_daily.csv"
OUTPUT_7d=r"D:\Users\YCJK\Desktop\20260527\20260527\20260920新数据结果\20260928\result\7.4ILI_7d.csv"

df=pd.read_csv(INPUT_FILE,dtype=str,low_memory=False)
df["event_date"]=pd.to_datetime(df["event_date"],errors="coerce").dt.normalize()
ili=df[pd.to_numeric(df["ili_positive"],errors="coerce")==1].copy()
ili["source"]="op_record"
ili["evidence_type"]="ILI"
ili["syndrome"]="ILI"
ili.to_csv(OUTPUT_RAW,index=False,encoding="utf-8-sig",date_format="%Y-%m-%d")

def join_unique(x):
    x=x.dropna().astype(str).str.strip()
    x=x[x!=""]
    return ";".join(pd.unique(x))
key=[
    "local_id",
    "event_date",
    "r_facility_code",
    "r_facility_name"
]
agg={
    c:join_unique
    for c in ili.columns
    if c not in key
}
ili_daily=(
    ili
    .groupby(key,dropna=False,as_index=False)
    .agg(agg)
)
print("ili daily事件",len(ili_daily))

ili_daily.to_csv(OUTPUT_DAILY,
                 index=False,
                 encoding="utf-8-sig",
                 date_format="%Y-%m-%d"
                 )

ili_daily=ili_daily.sort_values(
    ["local_id","event_date"]
).reset_index(drop=True)

def make_episode(g):
    no=1
    start=None
    out=[]

    for d in g["event_date"]:
        if start is None:
            start=d
        elif (d-start).days>7:
            no+=1
            start=d

        out.append(no)
    g["episode_no"]=out
    return g
ili_7d=(
    ili_daily
    .groupby("local_id",group_keys=False)
    .apply(make_episode)
    .reset_index(drop=True)
)
key7=["local_id","episode_no"]
agg7={
    c:join_unique
    for c in ili_7d.columns
    if c not in key7+["event_date"]
}
agg7["event_date"]="min"
ili_7d=(
    ili_7d
    .groupby(key7,dropna=False,as_index=False)
    .agg(agg7)
)
print("ili7天独立事件",len(ili_7d))
ili_7d.to_csv(
    OUTPUT_7d,
    index=False,
    encoding="utf-8-sig",
    date_format="%Y-%m-%d"
)