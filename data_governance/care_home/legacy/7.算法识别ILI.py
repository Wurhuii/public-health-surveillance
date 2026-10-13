import pandas as pd
import requests
INPUT_FILE=r"D:\Users\YCJK\Desktop\20260527\20260527\20260920新数据结果\20260928\result\4.入住期间诊疗数据\门诊病历_clean_in_facility.csv"
OUTPUT_ALL=r"D:\Users\YCJK\Desktop\20260527\20260527\20260920新数据结果\20260928\result\7.1ILI_all.csv"
OUTPUT_ILI=r"D:\Users\YCJK\Desktop\20260527\20260527\20260920新数据结果\20260928\result\7.2ILI_raw.csv"
url="http://127.0.0.1:8000/ili-identify/"

raw_df=pd.read_csv(INPUT_FILE,encoding="utf-8-sig",dtype=str,low_memory=False)
raw_df.columns=raw_df.columns.astype(str).str.strip()
print("门诊记录数",len(raw_df))

df=raw_df[["local_id","xingming","zhusu","xianbingshi","event_date"]].copy()
df.columns=[
    "id_card",
    "patient_name",
    "chief_complaint",
    "present_illness_his",
    "date"
]
df["date"]=pd.to_datetime(df["date"],errors="coerce").dt.strftime("%Y-%m-%d")
df=df.fillna("")

all_results=[]
ili_results=[]
for i in range(len(df)):
    one=df.iloc[[i]].copy()
    if(i+1)%1000==0 or i ==0:
       print("正在处理第",i+1,"/",len(df))
    response=requests.post(
        url,
        json=one.to_dict("records"),
        timeout=600
    )
    if response.status_code!=200:
        print("这一条失败",i+1)
        print(response.text)
        break
    result = response.json()
    result_df=pd.DataFrame(result.get("data",[]))

    if len(result_df) != 1:
        print("返回结果数量不是1，停止")
        print("第",i+1,"条")
        print(result)
        break

    for c in ["id_card","patient_name","chief_complaint", "present_illness_his","date"]:
        if c in result_df.columns:
            result_df=result_df.drop(columns=[c])
    raw_one=raw_df.iloc[[i]].reset_index(drop=True)
    alg_one=result_df.reset_index(drop=True)

    out = pd.concat(
        [raw_one,alg_one],
        axis=1
    )
    all_results.append(out)
    if "ili_positive" in result_df.columns:
        if str(result_df["ili_positive"].iloc[0]).strip()=="1":

            ili_one=out.copy()

            ili_one["source"]="op_record"
            ili_one["evidence_type"]="ILI"
            ili_one["syndrome"]="ILI"

            ili_results.append(ili_one)


if all_results:
    final_df=pd.concat(all_results,ignore_index=True)
    final_df.to_csv(OUTPUT_ALL,index=False,encoding="utf-8-sig")
    print("全部算法识别",len(final_df))
    print("ILI阳性数量：",len(ili_results))
    if ili_results:
        ili_df=pd.concat(ili_results,ignore_index=True)
        ili_df.to_csv(OUTPUT_ILI,index=False,encoding="utf-8-sig")
        print("ILI阳性结果已导出：",OUTPUT_ILI)
else:
    print("没有成功结果")

