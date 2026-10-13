import pandas as pd
import os
import gc
from openpyxl.styles.builtins import output

CHUNK_SIZE=500000
ELDERLY_FILE=r"D:\Users\YCJK\Desktop\20260527\20260527\20260920新数据结果\20260928\result\1.elderly_clean.csv"
INPUT_FILES={
    "门诊病历":r"D:\Users\YCJK\Desktop\20260527\20260527\20260920新数据结果\20260928\门诊病历.csv",
    "门诊处方明细":r"D:\Users\YCJK\Desktop\20260527\20260527\20260920新数据结果\20260928\门诊处方明细.csv",
    "门诊挂号":r"D:\Users\YCJK\Desktop\20260527\20260527\20260920新数据结果\20260928\门诊挂号.csv",
    "门诊检验常规报告":r"D:\Users\YCJK\Desktop\20260527\20260527\20260920新数据结果\20260928\门诊检验常规报告.csv",
    "门诊细菌报告":r"D:\Users\YCJK\Desktop\20260527\20260527\20260920新数据结果\20260928\门诊细菌报告.csv",
    "门诊诊断":r"D:\Users\YCJK\Desktop\20260527\20260527\20260920新数据结果\20260928\门诊诊断.csv",
    "住院检验常规报告":r"D:\Users\YCJK\Desktop\20260527\20260527\20260920新数据结果\20260928\住院检验常规报告.csv",
    "住院细菌报告":r"D:\Users\YCJK\Desktop\20260527\20260527\20260920新数据结果\20260928\住院细菌报告.csv",
    "住院医嘱2023-20260531":r"D:\Users\YCJK\Desktop\20260527\20260527\20260920新数据结果\20260928\住院医嘱2023-20260531.csv",
    "住院医嘱202008-20221231":r"D:\Users\YCJK\Desktop\20260527\20260527\20260920新数据结果\20260928\住院医嘱202008-20221231.csv",
    "住院诊断":r"D:\Users\YCJK\Desktop\20260527\20260527\20260920新数据结果\20260928\住院诊断.csv"
}
BIG_FILES={
    "住院检验常规报告",
"住院细菌报告",
"住院医嘱2023-20260531",
"住院医嘱202008-20221231",
"住院诊断"
}
OUTPUT_DIR=r"D:\Users\YCJK\Desktop\20260527\20260527\20260920新数据结果\20260928\result\3.医疗大数据清洗结果"
OUTPUT_FILE={
    name:os.path.join(OUTPUT_DIR,name+"_clean.csv")
    for name in INPUT_FILES
}

DATE_COLS={
    "门诊病历":"jiuzhenriqi",
    "门诊处方明细":"chufangkailiriqi",
    "门诊挂号":None,
    "门诊检验常规报告":"baogaoriqi",
    "门诊细菌报告":"baogaoriqi",
    "门诊诊断":"zhenduanriqi",
    "住院检验常规报告":"baogaoriqi",
    "住院细菌报告":"baogaoriqi",
    "住院医嘱2023-20260531":"yizhukailiriqi",
    "住院医嘱202008-20221231":"yizhukailiriqi",
    "住院诊断":"zhenduanriqi"
}
ID_COL="md5(`t`.`LOCAL_ID`)"

elderly=pd.read_csv(ELDERLY_FILE,dtype=str,usecols=["local_id"])
white_ids=set(
    elderly["local_id"]
    .dropna()
    .str.strip()
    .str.lower()
)

for name,file in INPUT_FILES.items():
    print("\n===========")
    print(name)
    print("=========")
    if name in BIG_FILES:
        output_file=OUTPUT_FILE[name]
        if os.path.exists(output_file):
            os.remove(output_file)
        for i,df in enumerate(
            pd.read_csv(
                file,
                dtype=str,
                chunksize=CHUNK_SIZE,
                low_memory=True
            )
        ):
            print("正在处理第",i+1,"块，记录数",len(df))
            df["local_id"] = (
                df[ID_COL]
                .str.strip()
                .str.lower()
            )
            date_col = DATE_COLS[name]
            if date_col is not None:
                df["event_date"] = pd.to_datetime(
                    df[date_col]
                    .str.strip()
                    .str.split()
                    .str[0],
                    errors="coerce"
                )
                print("event_date缺失/解析失败:", df["event_date"].isna().sum())
                print("日期范围：", df["event_date"].min(), "至", df["event_date"].max())
                n_before=len(df)
                df = df.loc[
                    df["local_id"].isin(white_ids)
                ]
                print("白名单匹配记录", len(df))
                print("白名单未匹配记录", n_before - len(df))
                print("涉及老人", df["local_id"].nunique())
                n_dup = df.duplicated().sum()
                print("完全重复记录", n_dup)
                df = df.drop_duplicates()
                print("最终记录", len(df))
                df.to_csv(output_file,
                          mode="w" if i==0 else "a",
                          header=(i==0),
                          index=False,
                          encoding="utf-8-sig",
                          date_format="%Y-%m-%d")
                del df
                gc.collect()
        continue
    df=pd.read_csv(file,dtype=str,low_memory=True)
    n_raw=len(df)

    df["local_id"]=(
        df[ID_COL]
        .str.strip()
        .str.lower()
    )
    print("原始记录数",n_raw)
    print("local缺失数",df["local_id"].isna().sum())
    bad_id=df[
        df["local_id"].notna()&
        ~df["local_id"].str.match(r"^[0-9a-f]{32}$")
    ]
    print("MD5格式异常",len(bad_id))
    if len(bad_id)>0:
        print("异常id示例",
              bad_id["local_id"].drop_duplicates().head(5).tolist())

    date_col=DATE_COLS[name]
    if date_col is not None:
        df["event_date"]=pd.to_datetime(
            df[date_col]
            .str.strip()
            .str.split()
            .str[0],
            errors="coerce"
        )
        print("event_date缺失/解析失败:",df["event_date"].isna().sum())
        print("日期范围：",df["event_date"].min(),"至",df["event_date"].max())
    else:
        print("尚未设置主要日期字段")

    n_before=len(df)
    df=df[
        df["local_id"].isin(white_ids)
    ]
    print("白名单匹配记录",len(df))
    print("白名单未匹配记录",n_before-len(df))
    print("涉及老人",df["local_id"].nunique())

    n_dup=df.duplicated().sum()
    print("完全重复记录",n_dup)
    df=df.drop_duplicates()
    print("最终记录",len(df))
    df.to_csv(OUTPUT_FILE[name],
              index=False,
              encoding="utf-8-sig",
              date_format="%Y-%m-%d")
    del df
    del bad_id
    gc.collect()