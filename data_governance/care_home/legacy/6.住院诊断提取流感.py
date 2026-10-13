import re
import pandas as pd
from arviz import output_file

input_file=r"D:\Users\YCJK\Desktop\20260527\20260527\20260920新数据结果\20260928\result\4.入住期间诊疗数据\住院诊断_clean_in_facility.csv"
output_raw=r"D:\Users\YCJK\Desktop\20260527\20260527\20260920新数据结果\20260928\result\6.1ip_diagnosis_flu_raw.csv"
output_daily=r"D:\Users\YCJK\Desktop\20260527\20260527\20260920新数据结果\20260928\result\6.2ip_diagnosis_flu_daily.csv"
output_7d=r"D:\Users\YCJK\Desktop\20260527\20260527\20260920新数据结果\20260928\result\6.3ip_diagnosis_flu_7d.csv"
CODE_COL="jbzdbm"
CODE_NAME="jbzdmc"
df = pd.read_csv(input_file,dtype=str,low_memory=False)
print("入住期间门诊诊断记录数",len(df))
ICD10_RE = re.compile(
    r"(?<![A-Z0-9])([A-Z][0-9]{2}(?:\.?[0-9A-Z]+)?)(?![A-Z0-9])"
)
ICD9_RE = re.compile(
    r"(?<![A-Z0-9])(\d{3}(?:\.?\d{1,3})?)(?![A-Z0-9])"
)
def extract_codes(x):
    if pd.isna(x):
        return []
    s=str(x).upper().strip()
    icd10_codes=ICD10_RE.findall(s)
    icd9_codes=ICD9_RE.findall(s)
    codes=icd9_codes+icd10_codes
    codes = [
        c.replace(".","").replace(" ","").upper()
        for c in codes
        if c is not None and str(c).strip()!=""
    ]
    return list(dict.fromkeys(codes))

df["_source_row_id"]=range(len(df))
df["disease_code"]=df[CODE_COL].apply(extract_codes)

flu=(
    df
    .explode("disease_code")
    .dropna(subset=["disease_code"])
    .copy()
)

FLU_PREFIX=("J09","J10","J11")
flu=flu[
    flu["disease_code"].str.startswith(
        FLU_PREFIX,
        na=False
    )
].copy()
flu["disease"]="influenza"
flu["source"]="ip_diagnosis"
flu["evidence_type"]="ICD"
flu["disease_name"]=flu[CODE_NAME]

first_cols=[
    "local_id",
    "event_date",
    "r_facility_code",
    "r_facility_name",
    "disease",
    "source",
    "evidence_type",
    "disease_code",
    "disease_name"
]
other_cols=[x for x in flu.columns if x not in first_cols]
flu=flu[first_cols+other_cols]
print("\n=====流感原始识别结果======")
print("流感诊断记录数",len(flu))
print("涉及老人",flu["local_id"].nunique())
print("涉及养老机构",flu["r_facility_code"].nunique())

flu.to_csv(
    output_raw,
    index=False,
    encoding="utf-8-sig",
    date_format="%Y-%m-%d"
)

def join_unique(x):
    x=x.dropna().astype(str).str.strip()
    x=x[x!=""]
    return ";".join(pd.unique(x))
key_cols=[
    "local_id",
    "event_date",
    "r_facility_code",
    "r_facility_name"
]
other_cols=[
    x for x in flu.columns
    if x not in key_cols + ["_source_raw_id"]
]

agg_dict={
    x:join_unique for x in other_cols
}
agg_dict["_source_row_id"]="nunique"
flu_daily=(
    flu
    .groupby(
        key_cols,
        dropna=False,
        as_index=False
    )
    .agg(agg_dict)
    .rename(
        columns={"_source_row_id":"source_record_n"}
    )
)
flu_daily["disease"]="influenza"
flu_daily["source"]="ip_diagnosis"
flu_daily["evidence_type"]="ICD"
first_daily=flu_daily[[
    "local_id",
    "event_date",
    "r_facility_code",
    "r_facility_name",
    "disease",
    "source",
    "evidence_type",
    "disease_code",
    "disease_name",
    "source_record_n"
]]

print("\n===========同日去重后=========")
print("流感person-day事件数",len(flu_daily))
print("涉及老人数",flu_daily["local_id"].nunique())
print("涉及养老机构",flu_daily["r_facility_code"].nunique())
print("日期范围",flu_daily["event_date"].min(),"至",flu_daily["event_date"].max())

flu_daily.to_csv(
    output_daily,
    index=False,
    encoding="utf-8-sig",
    date_format="%Y-%m-%d"
)
flu_daily["event_date"]=pd.to_datetime(
    flu_daily["event_date"],
    errors="coerce"
).dt.normalize()
flu_daily=flu_daily.sort_values(
    ["local_id","event_date"]
).reset_index(drop=True)

def make_episode(g):
    episode=[]
    episode_no=1
    start_date=None

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
        ["local_id","source","disease"],
        group_keys=False
    )
    .apply(make_episode)
    .reset_index(drop=True)
)
def join_unique(x):
    x=x.dropna().astype(str).str.strip()
    x=x[x!=""]
    return ";".join(pd.unique(x))
key_cols=[
    "local_id",
    "source",
    "disease",
    "episode_no"
]
other_cols=[
    x for x in flu_7d.columns
    if x not in key_cols
]

agg_dict={
    x:join_unique for x in other_cols
}
agg_dict["event_date"]="min"
flu_7d=(
    flu_7d
    .groupby(
        key_cols,
        dropna=False,
        as_index=False
    )
    .agg(agg_dict)
)

print("\n===========7日去重后=========")
print("7日流感事件数",len(flu_7d))
print("涉及老人数",flu_daily["local_id"].nunique())
print("涉及养老机构",flu_7d["r_facility_code"].nunique())

flu_7d.to_csv(
    output_7d,
    index=False,
    encoding="utf-8-sig",
    date_format="%Y-%m-%d"
)
