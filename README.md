# locaIP - 自建离线 IP 定位系统

基于四层架构的 IP 地理定位数据库，不依赖 MaxMind 等商业库。

## 架构

| 层级 | 数据源 | 精度 | 优先级 |
|------|--------|------|--------|
| L1 | Geofeed / 云厂商官方 IP 段 | 城市/数据中心级 | 最高 |
| L2 | CAIDA pfx2as / BGP | ASN 映射 | 中间层 |
| L3 | PeeringDB / IXP | ASN 设施位置 | 中高 |
| L4 | Project Sonar PTR | 反向 DNS 推断 | 补充 |

## 文件说明

| 文件 | 功能 |
|------|------|
| `ip_locator_core.py` | 核心模块：IP 转换、区间树、数据库操作 |
| `import_geofeed.py` | L1 层：导入 Geofeed CSV |
| `import_l2_asn.py` | L2 层：导入 CAIDA pfx2as |
| `quick_merge.py` | 数据融合工具 |
| `check_db.py` | 数据库检查 |
| `test_query.py` | 查询测试 |

## 快速开始

### 1. 导入 L1 数据（Geofeed）

```bash
python import_geofeed.py your_geofeed.csv
```

### 2. 融合数据

```bash
python quick_merge.py
```

### 3. 查询 IP

```bash
# 快速查询
python quick_merge.py query 8.8.8.8

# 交互模式
python test_query.py -i
```

## 导入 L2 数据（可选）

1. 从 https://publicdata.caida.org/datasets/routing/routeviews-prefix2as/ 下载 pfx2as 文件
2. 导入：

```bash
python import_l2_asn.py import routeviews-rv2-20240301-1200.pfx2as.gz
```

## 数据流程

```
Geofeed CSV → raw_l1_authoritative → merged_ip_locations → 查询
     ↑
CAIDA pfx2as → raw_l2_asn_mapping → ASN 查询
```

## 当前状态

- ✅ L1 Geofeed 导入完成
- ✅ 数据融合完成
- ✅ 查询功能正常
- ⬜ L2 ASN 数据（待导入）
- ⬜ L3 PeeringDB（待实现）
- ⬜ L4 PTR 数据（待实现）
