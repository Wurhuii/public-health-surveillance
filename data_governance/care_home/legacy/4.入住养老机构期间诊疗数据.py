import pandas as pd
import os
import gc

CHUNK_SIZE=500000
EXCLUDE_ID="3ea032bf79e8c116b05f4698d5a8e044"
ELDERLY_FILE=r"D:\Users\YCJK\Desktop\20260527\20260527\20260920新数据结果\20260928\result\1.elderly_clean.csv"
INPUT_DIR=r"D:\Users\YCJK\Desktop\20260527\20260527\20260920新数据结果\20260928\result\3.医疗大数据清洗结果"
OUTPUT_DIR=r"D:\Users\YCJK\Desktop\20260527\20260527\20260920新数据结果\20260928\result\4.入住期间诊疗数据"
FILES=[
"门诊病历_clean",
    "门诊处方明细_clean",
    "门诊检验常规报告_clean",
    "门诊细菌报告_clean",
    "门诊诊断_clean",
    "住院检验常规报告_clean",
    "住院细菌报告_clean",
    "住院医嘱2023-20260531_clean",
    "住院医嘱202008-20221231_clean",
    "住院诊断_clean"
]
os.makedirs(OUTPUT_DIR,exist_ok=True)
elderly=pd.read_csv(ELDERLY_FILE,dtype=str)
stay=elderly[["local_id","facility_code","facility_name","county","admit_date","end_date"]].copy()
stay["admit_date"]=pd.to_datetime(stay["admit_date"],errors="coerce").dt.normalize()
stay["end_date"]=pd.to_datetime(stay["end_date"],errors="coerce").dt.normalize()
stay=stay.dropna(subset=["local_id","facility_code","admit_date","end_date"]).drop_duplicates()
stay=stay.rename(columns={
    "facility_code":"r_facility_code",
    "facility_name":"r_facility_name",
    "county":"r_county",
    "admit_date":"r_admit_date",
    "end_date":"r_end_date"
})

for name in FILES:
    input_file=os.path.join(
        INPUT_DIR,
        name+".csv"
    )
    output_file=os.path.join(
        OUTPUT_DIR,
        name+"_in_facility.csv"
    )
    if os.path.exists(output_file):
        os.remove(output_file)
    print("\n===========")
    print(name)
    print("==========")

    n_raw=0
    n_missing_date=0
    n_match=0
    people=set()
    for i,df in enumerate(
        pd.read_csv(
            input_file,
            dtype=str,
            chunksize=CHUNK_SIZE,
            low_memory=True
        )
    ):
        n_raw+=len(df)
        df["event_date"]=pd.to_datetime(
            df["event_date"],
            errors="coerce"
        ).dt.normalize()

        n_missing_date+=df["event_date"].isna().sum()
        df=df[df["local_id"]!=EXCLUDE_ID]

        df=df.merge(
            stay,
            on="local_id",
            how="inner"
        )
        df=df[
            (df["event_date"]>=df["r_admit_date"])&
            (df["event_date"]<=df["r_end_date"])
        ]
        n_match +=len(df)
        people.update(df["local_id"].dropna().unique())

        df.to_csv(
            output_file,
            mode="w" if i==0 else"a",
            header=(i ==0),
            index=False,
            encoding="utf-8-sig",
            date_format="%Y-%m-%d"
        )
        del df
        gc.collect()

    print("原clean记录数",n_raw)
    print("event_date缺失",n_missing_date)
    print("入住期间记录数",n_match)
    print("涉及老人",len(people))
