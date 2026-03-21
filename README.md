# locaIP - 自建离线 IP 定位系统

基于四层架构的 IP 地理定位数据库，**完全不依赖 MaxMind** 等商业库。

## 数据规模

| 指标 | 数值 |
|------|------|
| **总记录** | 1,199,870 |
| **L1 权威数据** | 726,435 |
| **L2+L3 ASN 映射** | 473,435 |
| **中国城市覆盖** | 473,358 (41.6% 有城市信息) |

## 四层架构

| 层级 | 数据源 | 记录数 | 精度 | 优先级 |
|------|--------|--------|------|--------|
| L1 | Geofeed + APNIC WHOIS | 726,435 | 城市级 | 最高 |
| L2 | CAIDA pfx2as | 1,081,375 | ASN 映射 | 中间 |
| L3 | PeeringDB | 34,190 | ASN 设施 | 中高 |
| L4 | Project Sonar PTR | 1,517,353 | 反向 DNS | 补充 |

## 核心文件

| 文件 | 功能 |
|------|------|
| `ip_locator_core.py` | 核心模块：IP 转换、区间树、数据库操作 |
| `full_merge.py` | **主查询脚本**：四层数据融合与查询 |
| `import_l1_geofeed.py` | L1 层：导入 Geofeed CSV |
| `import_apnic_cn.py` | L1 层：导入 APNIC 中国 IP 段 |
| `import_apnic_whois.py` | L1 层：从 APNIC WHOIS 提取城市信息 |
| `import_l2_asn.py` | L2 层：导入 CAIDA pfx2as |
| `import_l3_peeringdb.py` | L3 层：导入 PeeringDB ASN 信息 |
| `import_rdns_ptr.py` | L4 层：导入 Sonar PTR 数据 |

## 快速开始

### 查询 IP

```bash
# 查询单个 IP
python full_merge.py query 8.8.8.8

# 示例输出：
# 8.8.8.8:
#   来源: L3 (置信度: 3)
#   位置: FR, Paris
#   ASN: 15169
#   IP段: 8.8.8.0 - 8.8.8.255
```

### 导入数据（按需）

```bash
# L1: Geofeed
python import_l1_geofeed.py your_geofeed.csv

# L1: APNIC 中国 IP 段
python import_apnic_cn.py download

# L1: APNIC WHOIS 城市信息
python import_apnic_whois.py import apnic.db.inetnum.gz CN

# L2: CAIDA ASN
python import_l2_asn.py import routeviews-rv2-20260317-1200.pfx2as.gz

# L3: PeeringDB
python import_l3_peeringdb.py batch 100

# L4: PTR 数据
python import_rdns_ptr.py import 2026-03_rdns_ipv4.json.gz 0.01

# 重新融合
python full_merge.py
```

## 中国城市覆盖

| 城市 | 记录数 |
|------|--------|
| Jiangsu | 37,169 |
| Shanghai | 31,683 |
| Suzhou | 27,685 |
| Henan | 15,826 |
| Hangzhou | 12,776 |
| Beijing | 11,958 |
| Zhejiang | 10,738 |
| Guangdong | 5,119 |
| Nanjing | 4,349 |
| Fujian | 4,333 |

## 数据源下载

| 数据 | 来源 | 文件 |
|------|------|------|
| Geofeed | IPinfo / 运营商 | `geofeed.csv` |
| APNIC | https://ftp.apnic.net/stats/apnic/ | `delegated-apnic-latest` |
| APNIC WHOIS | https://ftp.apnic.net/apnic/whois/ | `apnic.db.inetnum.gz` |
| CAIDA pfx2as | https://publicdata.caida.org/datasets/routing/routeviews-prefix2as/ | `*.pfx2as.gz` |
| PeeringDB | https://www.peeringdb.com/ | API / dump |
| Sonar PTR | https://opendata.rapid7.com/sonar.rdns_v2/ | `*.json.gz` |

## 查询示例

```bash
# 国内 IP
$ python full_merge.py query 125.94.202.48
125.94.202.48:
  来源: L1 (置信度: 5)
  位置: CN, Beijing
  IP段: 125.88.0.0 - 125.95.255.255

# 国际 IP
$ python full_merge.py query 8.8.8.8
8.8.8.8:
  来源: L3 (置信度: 3)
  位置: FR, Paris
  ASN: 15169
  IP段: 8.8.8.0 - 8.8.8.255
```

## 技术特点

- ✅ **完全离线**：不依赖外部 API
- ✅ **四层融合**：L1 > L2+L3 > L4 优先级
- ✅ **区间树查询**：高效 IP 段匹配
- ✅ **城市级精度**：中国 19.7万条城市记录
- ✅ **ASN 映射**：100万+ IP→ASN 映射

## 当前状态

- ✅ L1 Geofeed + APNIC WHOIS (72万条)
- ✅ L2 CAIDA pfx2as (108万条)
- ✅ L3 PeeringDB (3.4万条)
- ✅ L4 PTR 数据 (151万条)
- ✅ 四层数据融合完成
- ✅ 查询功能正常