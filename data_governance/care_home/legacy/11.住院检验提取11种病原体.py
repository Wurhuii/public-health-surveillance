import pandas as pd
import re
import unicodedata
INPUT_FILE=r"D:\Users\YCJK\Desktop\20260527\20260527\20260920新数据结果\20260928\result\4.入住期间诊疗数据\住院检验常规报告_clean_in_facility.csv"
OUTPUT_ALL=r"D:\Users\YCJK\Desktop\20260527\20260527\20260920新数据结果\20260928\result\11.1ip_lab_11类病原体全部记录.csv"
OUTPUT_CANDIDATE=r"D:\Users\YCJK\Desktop\20260527\20260527\20260920新数据结果\20260928\result\11.2ip_lab_11类病原体候选记录.csv"
TEST_COL="jianyanmingcheng"
# =========================================================
# 1. 读取数据
# =========================================================
df = pd.read_csv(INPUT_FILE,
    dtype=str,
    low_memory=False
)

# 统一变量名
df.columns = df.columns.astype(str).str.strip().str.lower()

if TEST_COL not in df.columns:
    raise KeyError(
        "未找到 jianyanmingcheng，当前变量名为：\n"
        + TEST_COL
    )
print("原始检验数",len(df))

# =========================================================
# 2. 标准化检验名称
# =========================================================
def clean_text(x):
    if pd.isna(x):
        return ""

    # 全角转半角
    x = unicodedata.normalize("NFKC", str(x))

    # 转小写
    x = x.lower().strip()

    # 删除星号、空格、括号、横线等
    x = re.sub(
        r"[★☆▲△※*\"'“”‘’\r\n\t\s_\-—–·,，。:：;；/\\()（）\[\]{}<>《》]+",
        "",
        x
    )

    return x


df["jianyanmingcheng_raw"] = df[TEST_COL]

df["jianyanmingcheng_std"] = (
    df[TEST_COL]
    .apply(clean_text)
)
# =========================================================
# 3. 标记并排除抗体、IgG、IgM等
# 转小写后：
# IgG、Igg、IGG均变为igg
# IgM、Igm、IGM均变为igm
# =========================================================
ANTIBODY_PATTERN = (
    r"抗体|"
    r"igg|igm|iga|ige|"
    r"免疫球蛋白|"
    r"血清学|"
    r"血清抗体|"
    r"抗体滴度|"
    r"总抗体"
)

df["是否抗体项目"] = (
    df["jianyanmingcheng_std"]
    .str.contains(
        ANTIBODY_PATTERN,
        regex=True,
        na=False
    )
    .astype("int8")
)
COMBINATION_PATTERN=(
    r"呼吸道.*病原体.*核酸|"
r"呼吸道.*病原体.*抗原|"
r"呼吸道.*病原体.*联合|"
r"呼吸道.*多联"
r"呼吸道.*联检"
r"呼吸道.*多重"
r"呼吸道.*组合"
r"呼吸道.*\d+种"
r"呼吸道.*\d+项"
r"呼吸道.*\d+联"
    r"病原体核酸多联|"
    r"病原体多重核酸"
    r"病原体多联"
)
df["是否组合检测"]=(
    df["jianyanmingcheng_std"]
    .str.contains(
        COMBINATION_PATTERN,
        regex=True,
        na=False
    )
    &(df["是否抗体项目"]==0)
).astype("int8")
# =========================================================
# 4. 生成0/1变量的函数
# =========================================================
def make_flag(include_pattern, exclude_pattern=None):
    """
    满足纳入关键词、且不满足排除关键词、且不是抗体项目：
    赋值1，否则赋值0。
    """

    mask = df["jianyanmingcheng_std"].str.contains(
        include_pattern,
        regex=True,
        na=False
    )

    if exclude_pattern is not None:
        mask = mask & ~df["jianyanmingcheng_std"].str.contains(
            exclude_pattern,
            regex=True,
            na=False
        )

    # 排除抗体、IgG、IgM、血清学
    mask = mask & (df["是否抗体项目"] == 0)
    mask=mask&(df["是否抗体项目"]==0)

    return mask.astype("int8")


# =========================================================
# 5. 按图中的11类病原体生成0/1变量
# =========================================================
COMBINATION_PATTERN=(
    r"呼吸道.*病原体.*核酸|"
    r"呼吸道.*病原体.*抗原|"
    r"呼吸道.*病原体.*靶向测序|"
    r"呼吸道.*病原体.*测序|"
    r"呼吸道.*病原体.*多联|"
    r"呼吸道.*病原体.*联检|"
    r"呼吸道.*病原体.*多重|"
    r"呼吸道.*病原体.*组合|"
    r"呼吸道.*\d+种.*病原体|"
    r"呼吸道.*\d+项.*病原体|"
    r"呼吸道.*\d+联.*病原体|"
    r"病原体核酸\d+联|"
    r"病原体核酸多联|"
    r"病原体多重核酸|"
    r"呼吸道病毒核酸多联|"
    r"呼吸道病毒联检"

)

# 1. 新型冠状病毒
df["新型冠状病毒"] = make_flag(
    include_pattern=(
        r"新型冠状病毒|新冠病毒|新冠肺炎病毒|"
        r"新冠核酸|新冠抗原|"
        r"2019ncov|sarscov2|ncov|"
        r"orf1ab|开放阅读编码框1a|"
        r"核壳蛋白n基因|新冠n基因|新冠e基因|"
        r"ncovrna"
    )
)


# 2. 流感病毒
# 包括：流感检测、流感病毒检测、甲流、乙流等
# 排除：副流感病毒、流感嗜血杆菌
df["流感病毒"] = make_flag(
    include_pattern=(
        r"流感病毒|流感检测|流感筛查|流感|"
        r"甲型流感|乙型流感|甲流|乙流|"
        r"甲乙流|甲乙型流感|"
        r"influenza|flua|flub|h1n1|h3n2"
    ),
    exclude_pattern=(
        r"副流感|parainfluenza|"
        r"流感嗜血杆菌|haemophilusinfluenzae"
    )
)


# 3. 呼吸道合胞病毒
df["呼吸道合胞病毒"] = make_flag(
    include_pattern=(
        r"呼吸道合胞病毒|合胞病毒|"
        r"respiratorysyncytialvirus|rsv"
    )
)


# 4. 腺病毒
# “腺病毒”“人腺病毒”“呼吸道腺病毒”均纳入
df["腺病毒"] = make_flag(
    include_pattern=(
        r"腺病毒|人腺病毒|呼吸道腺病毒|"
        r"adenovirus|radv"
    )
)


# 5. 人偏肺病毒
df["人偏肺病毒"] = make_flag(
    include_pattern=(
        r"人偏肺病毒|偏肺病毒|"
        r"humanmetapneumovirus|hmpv"
    )
)


# 6. 副流感病毒
# 不再区分1、2、3、4型，全部归为副流感病毒
df["副流感病毒"] = make_flag(
    include_pattern=(
        r"副流感病毒|副流感|"
        r"parainfluenza|hpiv|piv"
    ),
    exclude_pattern=r"pivka"
)


# 7. 普通冠状病毒
# 229E、OC43、NL63、HKU1均合并为普通冠状病毒
# 必须排除新冠相关名称
df["普通冠状病毒"] = make_flag(
    include_pattern=(
        r"普通冠状病毒|人冠状病毒|"
        r"冠状病毒229e|冠状病毒oc43|"
        r"冠状病毒nl63|冠状病毒hku1|"
        r"hcov229e|hcovoc43|hcovnl63|hcovhku1"
    ),
    exclude_pattern=(
        r"新型冠状病毒|新冠|"
        r"2019ncov|sarscov2|ncov|orf1ab"
    )
)


# 8. 博卡病毒
df["博卡病毒"] = make_flag(
    include_pattern=(
        r"人博卡病毒|博卡病毒|"
        r"humanbocavirus|bocavirus|hbov"
    )
)


# 9. 鼻病毒
df["鼻病毒"] = make_flag(
    include_pattern=(
        r"人鼻病毒|鼻病毒|"
        r"humanrhinovirus|rhinovirus|hrv"
    )
)


# 10. 肠道病毒
df["肠道病毒"] = make_flag(
    include_pattern=(
        r"肠道病毒|enterovirus|evrna"
    )
)


# 11. 肺炎支原体
df["肺炎支原体"] = make_flag(
    include_pattern=(
        r"肺炎支原体|"
        r"mycoplasmapneumoniae|"
        r"mpdna|mprna"
    )
)


# =========================================================
# 6. 生成是否属于目标病原体的总变量
# =========================================================



PATHOGEN_COLUMNS = [
    "新型冠状病毒",
    "流感病毒",
    "呼吸道合胞病毒",
    "腺病毒",
    "人偏肺病毒",
    "副流感病毒",
    "普通冠状病毒",
    "博卡病毒",
    "鼻病毒",
    "肠道病毒",
    "肺炎支原体"
]

# 任意一个病原体变量为1，总变量就为1
df.loc[
    df["是否组合检测"]==1,
    PATHOGEN_COLUMNS
]=0

df["是否目标病原体"] = (
    df[PATHOGEN_COLUMNS]
    .max(axis=1)
    .astype("int8")
)

df["是否组合检测待判断"]=(
     df["是否组合检测"]==1
).astype("int8")

# =========================================================
# 7. 增加“识别病原体名称”变量
# 一个名称如果匹配多个病原体，用分号连接
# =========================================================
def get_pathogen_names(row):
    names = [
        col for col in PATHOGEN_COLUMNS
        if row[col] == 1
    ]

    return ";".join(names)


df["识别病原体名称"] = df.apply(
    get_pathogen_names,
    axis=1
)

df.loc[
    df["是否组合检测"]==1,
    "识别病原体名称"
]="组合检测"
# =========================================================
# 8. 筛选目标病原体检验记录
# =========================================================
result = df[
    (df["是否目标病原体"] == 1)|
    (df["是否组合检测"]==1)
].copy()
# =========================================================
# 9. 导出
# =========================================================

# 全部原始记录，并增加11个病原体0/1变量
df.to_csv(OUTPUT_ALL,
    index=False,
    encoding="utf-8-sig"
)

# 只保留识别到目标病原体的记录
result.to_csv(OUTPUT_CANDIDATE,
    index=False,
    encoding="utf-8-sig"
)


# =========================================================
# 10. 质控输出
# =========================================================
print("原始检验记录数：", len(df))
print("筛选出的病原体相关记录数：", len(result))
print("排除的抗体项目数：", df["是否抗体项目"].sum())
print("组合检测记录数：", df["是否组合检测"].sum())
print("组合检测待判断",df["是否组合检测待判断"].sum())

print("\n各病原体识别记录数：")
print(
    df[PATHOGEN_COLUMNS]
    .sum()
    .sort_values(ascending=False)
)

print("\n识别出的不同检验名称示例：")
print(
    result[
        [
            "jianyanmingcheng_raw",
            "识别病原体名称"
        ]
    ]
    .drop_duplicates()
    .head(50)
    .to_string(index=False)
)