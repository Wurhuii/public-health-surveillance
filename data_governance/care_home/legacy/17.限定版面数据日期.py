import pandas as pd
INPUT_FILE=r"D:\Users\YCJK\Desktop\20260527\20260527\20260920新数据结果\20260928\result\16.4flu_facility_day_panel.csv"
OUTPUT_FILE=r"D:\Users\YCJK\Desktop\20260527\20260527\20260920新数据结果\20260928\result\17flu_facility_day_panel(20200801_20260531).csv"
START_DATE="2020-08-01"
END_DATE="2026-05-31"
df=pd.read_csv(INPUT_FILE,dtype={"facility_code":str},low_memory=False)
df["date"]=pd.to_datetime(df["date"],errors="coerce")
df=df[
    (df["date"]>=START_DATE)
    &(df["date"]<=END_DATE)
].copy()
df.to_csv(OUTPUT_FILE,
          index=False,
          encoding="utf-8-sig",
          date_format="%Y-%m-%d"
          )
