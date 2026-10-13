import pandas as pd
INPUT_FILE=r"D:\Users\YCJK\Desktop\20260527\20260527\20260920新数据结果\20260928\result\1.elderly_clean.csv"
OUTPUT_PERSON_DAY=r"D:\Users\YCJK\Desktop\20260527\20260527\20260920新数据结果\20260928\result\2.1resident_person_day.csv"
OUTPUT_DENOMINATOR=r"D:\Users\YCJK\Desktop\20260527\20260527\20260920新数据结果\20260928\result\2.2facility_daily_denominator.csv"

elderly=pd.read_csv(INPUT_FILE,dtype={"local_id":str,"facility_code":str},parse_dates=["admit_date","end_date"])
stay=elderly[["local_id","facility_code","facility_name","county","admit_date","end_date"]].dropna(subset=["local_id","facility_code","admit_date","end_date"])
stay=stay[stay["admit_date"]<=stay["end_date"]].drop_duplicates()

person_day=stay.copy()
person_day["date"]=person_day.apply(
    lambda x:pd.date_range(x["admit_date"],x["end_date"],freq="D"),
    axis=1
)
person_day=person_day.explode("date")
person_day=person_day[["local_id","facility_code","facility_name","county","date"]].drop_duplicates()

denominator=person_day.groupby(["facility_code","facility_name","date"],as_index=False)["local_id"].nunique()
denominator=denominator.rename(columns={"local_id":"resident_count"})
person_day.to_csv(OUTPUT_PERSON_DAY,index=False,encoding="utf-8-sig",date_format="%Y-%m-%d")
denominator.to_csv(OUTPUT_DENOMINATOR,index=False,encoding="utf-8-sig",date_format="%Y-%m-%d")

print("入住区间记录数",len(stay))
print("在院老人数",len(person_day))
print("涉及老人数",person_day["local_id"].nunique())
print("涉及机构数",person_day["facility_code"].nunique())
print("每日分母表行数",len(denominator))
print("日期范围",person_day["date"].min(),"至",person_day["date"].max())