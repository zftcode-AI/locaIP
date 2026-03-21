#!/usr/bin/env python3
"""
导入 APNIC WHOIS 数据 (apnic.db.inetnum)
提取城市信息补充到 L1 层
"""

import gzip
import ipaddress
import re
import sqlite3
import sys
from collections import defaultdict


# 城市关键词映射
CITY_PATTERNS = {
    # 中国主要城市
    'Beijing': ('CN', 'BJ', 'Beijing'),
    'Bejing': ('CN', 'BJ', 'Beijing'),  # 拼写错误
    'Shanghai': ('CN', 'SH', 'Shanghai'),
    'Guangzhou': ('CN', 'GD', 'Guangzhou'),
    'Shenzhen': ('CN', 'GD', 'Shenzhen'),
    'Hangzhou': ('CN', 'ZJ', 'Hangzhou'),
    'Nanjing': ('CN', 'JS', 'Nanjing'),
    'Chengdu': ('CN', 'SC', 'Chengdu'),
    'Wuhan': ('CN', 'HB', 'Wuhan'),
    'Xi\'an': ('CN', 'SN', 'Xi\'an'),
    'Chongqing': ('CN', 'CQ', 'Chongqing'),
    'Tianjin': ('CN', 'TJ', 'Tianjin'),
    'Suzhou': ('CN', 'JS', 'Suzhou'),
    'Dalian': ('CN', 'LN', 'Dalian'),
    'Qingdao': ('CN', 'SD', 'Qingdao'),
    'Xiamen': ('CN', 'FJ', 'Xiamen'),
    'Fuzhou': ('CN', 'FJ', 'Fuzhou'),
    'Jinan': ('CN', 'SD', 'Jinan'),
    'Zhengzhou': ('CN', 'HEN', 'Zhengzhou'),
    'Changsha': ('CN', 'HN', 'Changsha'),
    'Kunming': ('CN', 'YN', 'Kunming'),
    'Harbin': ('CN', 'HL', 'Harbin'),
    'Shenyang': ('CN', 'LN', 'Shenyang'),
    'Changchun': ('CN', 'JL', 'Changchun'),
    'Guiyang': ('CN', 'GZ', 'Guiyang'),
    'Nanning': ('CN', 'GX', 'Nanning'),
    'Lanzhou': ('CN', 'GS', 'Lanzhou'),
    'Haikou': ('CN', 'HI', 'Haikou'),
    'Hefei': ('CN', 'AH', 'Hefei'),
    'Nanchang': ('CN', 'JX', 'Nanchang'),
    'Shijiazhuang': ('CN', 'HEB', 'Shijiazhuang'),
    'Taiyuan': ('CN', 'SX', 'Taiyuan'),
    'Urumqi': ('CN', 'XJ', 'Urumqi'),
    'Lhasa': ('CN', 'XZ', 'Lhasa'),
    'Yinchuan': ('CN', 'NX', 'Yinchuan'),
    'Xining': ('CN', 'QH', 'Xining'),
    'Hohhot': ('CN', 'NM', 'Hohhot'),
    
    # 省份关键词（用于推断）
    'Guangdong': ('CN', 'GD', ''),
    'Jiangsu': ('CN', 'JS', ''),
    'Shandong': ('CN', 'SD', ''),
    'Zhejiang': ('CN', 'ZJ', ''),
    'Henan': ('CN', 'HEN', ''),
    'Sichuan': ('CN', 'SC', ''),
    'Hubei': ('CN', 'HB', ''),
    'Hunan': ('CN', 'HN', ''),
    'Hebei': ('CN', 'HEB', ''),
    'Fujian': ('CN', 'FJ', ''),
    'Anhui': ('CN', 'AH', ''),
    'Liaoning': ('CN', 'LN', ''),
    'Shaanxi': ('CN', 'SN', ''),
    'Jiangxi': ('CN', 'JX', ''),
    'Heilongjiang': ('CN', 'HL', ''),
    'Shanxi': ('CN', 'SX', ''),
    'Guizhou': ('CN', 'GZ', ''),
    'Yunnan': ('CN', 'YN', ''),
    'Gansu': ('CN', 'GS', ''),
    'Guangxi': ('CN', 'GX', ''),
    'Xinjiang': ('CN', 'XJ', ''),
    'Inner Mongolia': ('CN', 'NM', ''),
    'Ningxia': ('CN', 'NX', ''),
    'Qinghai': ('CN', 'QH', ''),
    'Hainan': ('CN', 'HI', ''),
    'Tibet': ('CN', 'XZ', ''),
}


def parse_inetnum_block(block: str) -> dict:
    """解析一个 inetnum 块"""
    result = {}
    
    # 提取 inetnum
    inetnum_match = re.search(r'inetnum:\s+([\d.]+)\s+-\s+([\d.]+)', block)
    if inetnum_match:
        result['ip_start'] = inetnum_match.group(1)
        result['ip_end'] = inetnum_match.group(2)
    
    # 提取 netname
    netname_match = re.search(r'netname:\s+(\S+)', block)
    if netname_match:
        result['netname'] = netname_match.group(1)
    
    # 提取 descr (可能有多个)
    descr_matches = re.findall(r'descr:\s+(.+)', block)
    result['descr'] = ' '.join(descr_matches)
    
    # 提取 country
    country_match = re.search(r'country:\s+(\w+)', block)
    if country_match:
        result['country'] = country_match.group(1)
    
    # 提取 address (可能有多个)
    address_matches = re.findall(r'address:\s+(.+)', block)
    result['address'] = ' '.join(address_matches)
    
    # 提取 org (组织名)
    org_match = re.search(r'org:\s+(\S+)', block)
    if org_match:
        result['org'] = org_match.group(1)
    
    # 提取 remarks (可能包含位置信息)
    remarks_matches = re.findall(r'remarks:\s+(.+)', block)
    result['remarks'] = ' '.join(remarks_matches)
    
    return result


def extract_city(descr: str, address: str, remarks: str = '') -> tuple:
    """从描述和地址中提取城市信息"""
    full_text = f"{descr} {address} {remarks}"
    
    # 优先匹配完整城市名
    for city_name, (country, region, city) in CITY_PATTERNS.items():
        if city_name in full_text:
            return country, region, city if city else city_name
    
    return None, None, None


def import_apnic_whois(gz_path: str, db_path: str = "ip_locations.db", 
                       target_country: str = "CN"):
    """
    导入 APNIC WHOIS 数据
    :param gz_path: apnic.db.inetnum.gz 路径
    :param target_country: 目标国家 (CN=中国)
    """
    print(f"导入 APNIC WHOIS: {gz_path}")
    print(f"目标国家: {target_country}")
    
    conn = sqlite3.connect(db_path, timeout=60)
    cursor = conn.cursor()
    
    # 优化性能
    cursor.execute('PRAGMA journal_mode=WAL')
    cursor.execute('PRAGMA synchronous=NORMAL')
    
    processed = 0
    matched = 0
    updated = 0
    batch = []
    
    # 统计
    city_stats = defaultdict(int)
    
    with gzip.open(gz_path, 'rt', encoding='utf-8', errors='ignore') as f:
        content = f.read()
    
    # 分割成块
    blocks = content.split('\n\n')
    print(f"总块数: {len(blocks)}")
    
    for block in blocks:
        if not block.strip() or 'inetnum:' not in block:
            continue
        
        # 只处理目标国家 (APNIC格式: country:        CN)
        if f'country:        {target_country}' not in block:
            continue
        
        data = parse_inetnum_block(block)
        
        if not data.get('ip_start') or not data.get('ip_end'):
            continue
        
        # 提取城市
        country, region, city = extract_city(
            data.get('descr', ''), 
            data.get('address', ''),
            data.get('remarks', '')
        )
        
        if city or region:
            try:
                ip_start = int(ipaddress.ip_address(data['ip_start']))
                ip_end = int(ipaddress.ip_address(data['ip_end']))
                
                # 检查是否已有 L1 数据
                cursor.execute('''
                    SELECT id, city FROM raw_l1_authoritative
                    WHERE ip_start = ? AND ip_end = ?
                ''', (ip_start, ip_end))
                
                row = cursor.fetchone()
                
                if row:
                    # 更新现有记录（如果城市为空）
                    if not row[1] and city:
                        cursor.execute('''
                            UPDATE raw_l1_authoritative
                            SET city = ?, region = ?, source = 'apnic-whois'
                            WHERE id = ?
                        ''', (city, region, row[0]))
                        updated += 1
                        city_stats[city or region] += 1
                else:
                    # 插入新记录
                    batch.append((
                        ip_start, ip_end,
                        'apnic-whois',
                        target_country,
                        city,
                        region,
                        None, None,
                        str(data)
                    ))
                    matched += 1
                    city_stats[city or region] += 1
                
                # 批量插入
                if len(batch) >= 1000:
                    cursor.executemany('''
                        INSERT INTO raw_l1_authoritative 
                        (ip_start, ip_end, source, country, city, region, latitude, longitude, raw_data)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ''', batch)
                    batch = []
                    
                    if matched % 5000 == 0:
                        conn.commit()
                        print(f"  处理 {processed}, 新增 {matched}, 更新 {updated}...")
                
            except Exception as e:
                pass
        
        processed += 1
    
    # 插入剩余
    if batch:
        cursor.executemany('''
            INSERT INTO raw_l1_authoritative 
            (ip_start, ip_end, source, country, city, region, latitude, longitude, raw_data)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        ''', batch)
    
    conn.commit()
    conn.close()
    
    print(f"\n导入完成:")
    print(f"  处理: {processed}")
    print(f"  新增: {matched}")
    print(f"  更新: {updated}")
    print(f"\n城市分布 (前10):")
    for city, count in sorted(city_stats.items(), key=lambda x: -x[1])[:10]:
        print(f"  {city}: {count}")
    
    return matched + updated


def query_city_coverage(db_path: str = "ip_locations.db"):
    """查询城市覆盖情况"""
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    
    # 中国有城市的记录
    cursor.execute('''
        SELECT COUNT(*) FROM raw_l1_authoritative
        WHERE country = 'CN' AND city != '' AND city IS NOT NULL
    ''')
    with_city = cursor.fetchone()[0]
    
    # 中国总记录
    cursor.execute('''
        SELECT COUNT(*) FROM raw_l1_authoritative
        WHERE country = 'CN'
    ''')
    total = cursor.fetchone()[0]
    
    # 城市分布
    cursor.execute('''
        SELECT city, COUNT(*) FROM raw_l1_authoritative
        WHERE country = 'CN' AND city != ''
        GROUP BY city
        ORDER BY COUNT(*) DESC
        LIMIT 10
    ''')
    cities = cursor.fetchall()
    
    conn.close()
    
    print(f"\n中国城市覆盖:")
    print(f"  有城市: {with_city}")
    print(f"  总计: {total}")
    print(f"  覆盖率: {with_city/total*100:.1f}%")
    print(f"\nTop 10 城市:")
    for city, count in cities:
        print(f"  {city}: {count}")


if __name__ == '__main__':
    if len(sys.argv) < 2:
        print("用法:")
        print(f"  {sys.argv[0]} import <gz文件> [国家代码]")
        print(f"  {sys.argv[0]} stats")
        print(f"\n示例:")
        print(f"  python {sys.argv[0]} import apnic.db.inetnum.gz CN")
        sys.exit(1)
    
    command = sys.argv[1]
    
    if command == 'import':
        if len(sys.argv) < 3:
            print("请指定文件路径")
            sys.exit(1)
        gz_file = sys.argv[2]
        country = sys.argv[3] if len(sys.argv) > 3 else 'CN'
        import_apnic_whois(gz_file, target_country=country)
    
    elif command == 'stats':
        query_city_coverage()
    
    else:
        print("未知命令")
        sys.exit(1)
