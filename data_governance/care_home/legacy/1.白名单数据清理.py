import pandas as pd
import os
END_DATE=pd.Timestamp("2026-08-17")
OUTPUT_DIR=r"D:\Users\YCJK\Desktop\20260527\20260527\20260920新数据结果\20260928\result"
OUTPUT_FILE=os.path.join(OUTPUT_DIR,"1.elderly_clean.csv")
elderly_path=r'D:\Users\YCJK\Desktop\20260527\20260527\20260920新数据结果\20260928\医养结合老人住院信息20260817.xlsx'
grid_path=r'D:\Users\YCJK\Desktop\20260527\20260527\20260920新数据结果\20260928\医养结合网格地址.csv'
elderly=pd.read_excel(elderly_path,dtype=str)
grid=pd.read_csv(grid_path,dtype=str,encoding="gb18030")
elderly=elderly.rename(columns={
    "身份证号":"local_id",
    "出生日期":"birth_date",
    "入院时间":"admit_date",
    "离开时间":"discharge_date",
    "机构编码":"facility_code",
    "机构名称":"facility_name",
    "机构地址":"facility_address",
    "机构级别":"facility_level",
    "机构类型":"facility_type",
    "机构所属县市区":"county"
})
grid=grid.rename(columns={
    "`t`.`local_id`":"local_id",
    "县市区":"grid_county",
    "街道":"grid_street",
    "社区":"grid_community"
})

elderly["local_id"]=elderly["local_id"].str.strip().str.lower()
grid["local_id"]=grid["local_id"].str.strip().str.lower()

for x in ["facility_code","facility_name","facility_address","facility_level","facility_type","county"]:
    elderly[x]=elderly[x].str.strip()
for x in ["birth_date","admit_date","discharge_date"]:
    elderly[x]=pd.to_datetime(elderly[x].str.strip().str.split().str[0],errors="coerce")


elderly=elderly.dropna(subset=["admit_date"])
mask=(elderly["discharge_date"].notna()&(elderly["admit_date"]>elderly["discharge_date"]))
print("需要交换",mask.sum())
elderly.loc[mask,["admit_date","discharge_date"]]=\
    elderly.loc[mask,["discharge_date","admit_date"]].to_numpy()
elderly["end_date"]=elderly["discharge_date"].fillna(END_DATE)
elderly["age"]=(
      (END_DATE-elderly["birth_date"]).dt.days//365.25
).astype("Int64")

elderly=elderly.merge(
    grid[
        ["local_id","grid_county","grid_street","grid_community"]
    ].drop_duplicates(),
    on="local_id",
    how="left"
)
n_before_dup=len(elderly)
elderly=elderly.drop_duplicates()
n_dup=n_before_dup-len(elderly)
elderly.to_csv(OUTPUT_FILE,index=False,encoding="utf-8-sig",date_format="%Y-%m-%d")

#删除情况核查
raw=pd.read_excel(elderly_path,dtype=str)
raw["admit_date"]=pd.to_datetime(raw["入院时间"].str.strip().str.split().str[0],errors="coerce")

print("原始记录",len(raw))
print("无有效入住日期数",raw["admit_date"].isna().sum())
print("完全重复删除记录数",n_dup)
print("最终记录数",len(elderly))
