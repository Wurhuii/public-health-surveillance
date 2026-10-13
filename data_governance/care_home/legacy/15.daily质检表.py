import pandas as pd
from django.db.models.expressions import result

FILES={
    "门诊诊断":r"D:\Users\YCJK\Desktop\20260527\20260527\20260920新数据结果\20260928\result\5.2op_diagnosis_flu_daily.csv",
    "住院诊断":r"D:\Users\YCJK\Desktop\20260527\20260527\20260920新数据结果\20260928\result\6.2ip_diagnosis_flu_daily.csv",
    "ILI":r"D:\Users\YCJK\Desktop\20260527\20260527\20260920新数据结果\20260928\result\7.3ILI_daily.csv",
    "门诊检验":r"D:\Users\YCJK\Desktop\20260527\20260527\20260920新数据结果\20260928\result\10.2op_lab_flu_daily.csv",
    "住院检验":r"D:\Users\YCJK\Desktop\20260527\20260527\20260920新数据结果\20260928\result\12.2ip_lab_flu_daily.csv",
    "门诊药物":r"D:\Users\YCJK\Desktop\20260527\20260527\20260920新数据结果\20260928\result\13.2op_drug_flu_daily.csv",
    "住院药物":r"D:\Users\YCJK\Desktop\20260527\20260527\20260920新数据结果\20260928\result\14.2ip_drug_flu_daily.csv"
}
OUTPUT_FILE=r"D:\Users\YCJK\Desktop\20260527\20260527\20260920新数据结果\20260928\result\15flu_daily质检表.xlsx"
result=[]
for source,file in FILES.items():
    print("正在检查",source)
    df=pd.read_csv(
        file,
        dtype=str,
        low_memory=False
    )
    df["event_date"]=pd.to_datetime(
        df["event_date"],
        errors="coerce"
    )
    dup_person_day=df.duplicated(
        subset=["local_id","event_date"],
        keep=False
    ).sum()
    dup_person_facility_day=df.duplicated(
        subset=[
            "local_id",
            "r_facility_code",
            "event_date"
        ],
        keep=False
    ).sum()

    result.append({
        "来源":source,
        "daily记录数":len(df),
        "涉及人数":df["local_id"].nunique(),
        "涉及机构数":df["r_facility_code"].nunique(),
        "最早日期":df["event_date"].min(),
        "最晚日期":df["event_date"].max(),
        "机构编码缺失数":df["r_facility_code"].isna().sum(),
        "同人同日重复记录数":dup_person_day,
        "同人同机构同日重复数":dup_person_facility_day
    })
    qc=pd.DataFrame(result)
    print("\n==========质检结果===========")
    print(qc)
    qc.to_excel(OUTPUT_FILE,index=False)