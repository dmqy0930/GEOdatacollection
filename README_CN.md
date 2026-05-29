# GEOdatacollection

一个全自动收集、整理、汇总 NCBI GEO（基因表达综合数据库）元数据及关联 SRA（序列读存档）运行信息的流水线。

## 概述

从 GEO 搜索查询或已有的结果文件开始，流水线将：

1. **搜索** GEO 并下载所有匹配条目
2. **提取** 不重复的 GSE 序列号
3. **抓取** 每个 GSE 的元数据（标题、摘要、状态、物种、实验设计、PMID、引用、样本详情、SuperSeries/SubSeries 关系）
4. **下载** 每个 BioProject 对应的 SRA Run Table（通过 NCBI E-utilities）
5. **生成** 一个完整的 15 列汇总 CSV

## 快速开始

### 环境要求

- Python 3.7+
- `requests` 库

```bash
pip install requests
```

### 使用

```bash
# 从 GEO 搜索查询开始
./run.sh --query '(((RNA-seq) AND (Homo sapiens[Organism]) AND ("2026/01/01"[Publication Date] : "2026/12/31"[Publication Date]))'

# 从已有 txt 文件开始
./run.sh /path/to/geo_results.txt

# 指定自定义输出目录
./run.sh --query '...' /path/to/custom_output
```

## 流水线

```
                   ┌────────────────────┐
                   │  GEO 搜索查询      │
                   └────────┬───────────┘
                            │
                   ┌────────▼───────────┐
                   │ 00_search_geo.py   │  E-utilities esearch + efetch
                   │ → 搜索结果文本     │
                   └────────┬───────────┘
                            │
                   ┌────────▼───────────┐
                   │ 01_extract_gse.py  │  正则提取 GSE 序列号
                   │ → gse_accessions   │
                   └────────┬───────────┘
                            │
                   ┌────────▼───────────┐
                   │ 02_fetch_gse_      │  解析 GEO SOFT 格式
                   │    details.py      │  → gse_metadata.csv × N
                   └────────┬───────────┘
                            │
                   ┌────────▼───────────┐
                   │ 03_download_sra.py │  SRA efetch (runinfo)
                   │ → sra_runinfo.csv  │
                   └────────┬───────────┘
                            │
                   ┌────────▼───────────┐
                   │ 04_generate_       │  合并 + PubMed 查询
                   │    summary.py      │  → summary.csv
                   └────────────────────┘
```

## 目录结构

```
GEOdatacollection/
├── run.sh                        # 总控脚本
├── scripts/
│   ├── 00_search_geo.py          # 搜索 GEO + 下载结果
│   ├── 01_extract_gse.py         # 提取 GSE 序列号
│   ├── 02_fetch_gse_details.py   # 按 GSE 抓取元数据（SOFT 格式）
│   ├── 03_download_sra.py        # 下载 SraRunTable
│   └── 04_generate_summary.py    # 生成 15 列汇总表
├── output/                       # 中间文件（gse_accessions.txt 等）
├── data/                         # 运行时输出目录
│   └── {YYYYMMDD}/
│       ├── GSE{编号}/
│       │   ├── gse_metadata.csv
│       │   └── sra_runinfo.csv
│       └── summary.csv
└── .gitignore
```

## 输出：汇总 CSV

最终的 `summary.csv` 包含 15 列，每个样本（GSM）一行：

| 列 | 说明 | 数据来源 |
|---|---|---|
| **GSE号码** | GEO Series 序列号 | GEO |
| **SRP号码** | SRA Study 序列号 | SRA |
| **SRR号码** | SRA Run 序列号 | SRA |
| **数据公布时间** | 数据公开年份（从 GEO Status 提取） | GEO |
| **收集时间** | 数据收集日期（`YYYY/MM/DD`） | SRA ReleaseDate |
| **测序类型** | `SE`（单端）或 `PE`（双端） | SRA LibraryLayout |
| **样本介绍** | 样本名称 | GEO |
| **GSM号码** | GEO Sample 序列号 | GEO |
| **来源** | 细胞系/组织来源 | GEO source_name / characteristics |
| **是否有其他干扰** | 干扰关键词（siRNA, sgRNA, CRISPR, DMSO 等） | GEO sample_title |
| **数据类型** | 数据类型（CLIP-seq, RNA-seq, ChIP-seq 等） | SRA LibraryStrategy + GEO |
| **相关的其他GSE数据** | 关联的 GSE（SuperSeries/SubSeries） | GEO |
| **PMID期刊名称** | 期刊名称 | PubMed |
| **发表年度** | 发表年份 | PubMed |
| **文献标题** | 文章标题 | PubMed |

## 单独使用各脚本

```bash
# 第 0 步：搜索 GEO
python scripts/00_search_geo.py '查询关键词' --output results.txt

# 第 1 步：提取 GSE 序列号
python scripts/01_extract_gse.py results.txt --output-dir ./output

# 第 2 步：抓取 GSE 元数据
python scripts/02_fetch_gse_details.py --date 20260512 --output-dir ./data/20260512

# 第 3 步：下载 SRA 元数据
python scripts/03_download_sra.py --date 20260512 --output-dir ./data/20260512

# 第 4 步：生成汇总表
python scripts/04_generate_summary.py --date 20260512 --output-dir ./data/20260512
```

## 依赖

| 库 | 使用位置 | 用途 |
|---|---|---|
| `requests` | 所有脚本 | HTTP 请求 NCBI E-utilities |
| 标准库（`csv`, `re`, `json`, `argparse` 等） | 所有脚本 | 数据处理 |

## API 访问频率限制

所有脚本均遵守 NCBI E-utilities 的访问频率限制（约每秒 3 次请求）。内置重试机制和指数退避策略处理临时性错误。

## 许可证

MIT
