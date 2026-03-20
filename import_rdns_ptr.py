#!/usr/bin/env python3
"""
导入 RDNS PTR 数据到 L4 层（优化版）
处理 2026-03_rdns_ipv4.json.gz 等大文件
"""

import gzip
import ipaddress
import json
import re
import sqlite3
import sys
from pathlib import Path
from collections import defaultdict


# 预编译正则表达式，大幅提升性能
PTR_PATTERNS_RAW = [
    # 中国电信
    (r'.*\.gd\.ctm\.net', 'CN', 'GD', 'Guangzhou', 'China Telecom'),
    (r'.*\.gddtelecom\.cn', 'CN', 'GD', 'Guangzhou', 'China Telecom'),
    (r'.*\.sztelecom\.cn', 'CN', 'GD', 'Shenzhen', 'China Telecom'),
    (r'.*\.sz\.ctm\.net', 'CN', 'GD', 'Shenzhen', 'China Telecom'),
    (r'.*\.dgtelecom\.cn', 'CN', 'GD', 'Dongguan', 'China Telecom'),
    (r'.*\.bj\.ctm\.net', 'CN', 'BJ', 'Beijing', 'China Telecom'),
    (r'.*\.bjtelecom\.cn', 'CN', 'BJ', 'Beijing', 'China Telecom'),
    (r'.*\.sh\.ctm\.net', 'CN', 'SH', 'Shanghai', 'China Telecom'),
    (r'.*\.shtelecom\.cn', 'CN', 'SH', 'Shanghai', 'China Telecom'),
    (r'.*\.js\.ctm\.net', 'CN', 'JS', 'Nanjing', 'China Telecom'),
    (r'.*\.zj\.ctm\.net', 'CN', 'ZJ', 'Hangzhou', 'China Telecom'),
    (r'.*\.sc\.ctm\.net', 'CN', 'SC', 'Chengdu', 'China Telecom'),
    (r'.*\.cdtelecom\.cn', 'CN', 'SC', 'Chengdu', 'China Telecom'),
    (r'.*\.hb\.ctm\.net', 'CN', 'HB', 'Wuhan', 'China Telecom'),
    (r'.*\.ln\.ctm\.net', 'CN', 'LN', 'Shenyang', 'China Telecom'),
    (r'.*\.sd\.ctm\.net', 'CN', 'SD', 'Jinan', 'China Telecom'),
    
    # 中国联通
    (r'.*\.bjunicom\.cn', 'CN', 'BJ', 'Beijing', 'China Unicom'),
    (r'.*\.shunicom\.cn', 'CN', 'SH', 'Shanghai', 'China Unicom'),
    (r'.*\.gdunicom\.cn', 'CN', 'GD', 'Guangzhou', 'China Unicom'),
    (r'.*\.jsunicom\.cn', 'CN', 'JS', 'Nanjing', 'China Unicom'),
    
    # 中国移动
    (r'.*\.bj\.cmcc\.cn', 'CN', 'BJ', 'Beijing', 'China Mobile'),
    (r'.*\.sh\.cmcc\.cn', 'CN', 'SH', 'Shanghai', 'China Mobile'),
    (r'.*\.gd\.cmcc\.cn', 'CN', 'GD', 'Guangzhou', 'China Mobile'),
    
    # 美国
    (r'.*\.comcast\.net', 'US', '', '', 'Comcast'),
    (r'.*\.verizon\.net', 'US', '', '', 'Verizon'),
    (r'.*\.att\.net', 'US', '', '', 'AT&T'),
    (r'.*\.charter\.com', 'US', '', '', 'Charter'),
    
    # 欧洲
    (r'.*\.bt\.net', 'GB', '', '', 'BT'),
    (r'.*\.orange\.fr', 'FR', '', '', 'Orange'),
    (r'.*\.telefonica\.com', 'ES', '', '', 'Telefonica'),
    
    # 日本
    (r'.*\.ocn\.ne\.jp', 'JP', '', '', 'NTT'),
    (r'.*\.softbank\.jp', 'JP', '', '', 'SoftBank'),
    
    # 韩国
    (r'.*\.kt\.com', 'KR', '', '', 'KT'),
    (r'.*\.sktelecom\.com', 'KR', '', '', 'SK Telecom'),
    
    # 云厂商
    (r'.*\.amazonaws\.com', 'US', '', '', 'AWS'),
    (r'.*\.googleusercontent\.com', 'US', '', '', 'Google Cloud'),
    (r'.*\.cloudflare\.com', 'US', '', '', 'Cloudflare'),
    (r'.*\.azure\.com', 'US', '', '', 'Azure'),
]

# 预编译所有正则
PTR_PATTERNS = [(re.compile(p), c, r, city, isp) for p, c, r, city, isp in PTR_PATTERNS_RAW]


def parse_ptr(ptr: str) -> tuple:
    """
    解析 PTR 记录，推断位置（使用预编译正则）
    返回: (country, region, city, isp, confidence)
    """
    ptr_lower = ptr.lower()
    
    # 使用预编译正则，大幅提升性能
    for pattern, country, region, city, isp in PTR_PATTERNS:
        if pattern.match(ptr_lower):
            confidence = 4 if city else 3
            return country, region, city, isp, confidence
    
    # 云厂商区域检测（优先）
    # AWS
    if 'amazonaws.com' in ptr_lower:
        if 'ap-southeast-1' in ptr_lower or 'ap-southeast' in ptr_lower:
            return 'SG', '', 'Singapore', 'AWS', 4
        if 'ap-southeast-2' in ptr_lower:
            return 'AU', '', 'Sydney', 'AWS', 4
        if 'ap-northeast-1' in ptr_lower:
            return 'JP', '', 'Tokyo', 'AWS', 4
        if 'ap-northeast-2' in ptr_lower:
            return 'KR', '', 'Seoul', 'AWS', 4
        if 'ap-south-1' in ptr_lower:
            return 'IN', '', 'Mumbai', 'AWS', 4
        if 'eu-west-1' in ptr_lower:
            return 'IE', '', 'Dublin', 'AWS', 4
        if 'eu-west-2' in ptr_lower:
            return 'GB', '', 'London', 'AWS', 4
        if 'eu-central-1' in ptr_lower:
            return 'DE', '', 'Frankfurt', 'AWS', 4
        if 'us-east-1' in ptr_lower:
            return 'US', '', 'Virginia', 'AWS', 4
        if 'us-west-2' in ptr_lower:
            return 'US', '', 'Oregon', 'AWS', 4
        if 'us-west-1' in ptr_lower:
            return 'US', '', 'California', 'AWS', 4
        if 'ca-central-1' in ptr_lower:
            return 'CA', '', 'Montreal', 'AWS', 4
        if 'sa-east-1' in ptr_lower:
            return 'BR', '', 'Sao Paulo', 'AWS', 4
        if 'compute-1' in ptr_lower or 'ec2-' in ptr_lower:
            return 'US', '', 'Virginia', 'AWS', 3  # 默认美国东部
        return 'US', '', '', 'AWS', 2  # 默认美国
    
    # Verizon FIOS 城市检测
    if 'verizon.net' in ptr_lower or 'fios' in ptr_lower:
        if 'nycmny' in ptr_lower or 'nyc' in ptr_lower:
            return 'US', 'NY', 'New York', 'Verizon', 4
        if 'bos' in ptr_lower or 'boston' in ptr_lower:
            return 'US', 'MA', 'Boston', 'Verizon', 4
        if 'phi' in ptr_lower or 'philadelphia' in ptr_lower:
            return 'US', 'PA', 'Philadelphia', 'Verizon', 4
        if 'was' in ptr_lower or 'washington' in ptr_lower:
            return 'US', 'DC', 'Washington DC', 'Verizon', 4
        if 'chi' in ptr_lower or 'chicago' in ptr_lower:
            return 'US', 'IL', 'Chicago', 'Verizon', 4
        if 'los' in ptr_lower or 'lax' in ptr_lower:
            return 'US', 'CA', 'Los Angeles', 'Verizon', 4
        if 'san' in ptr_lower or 'sanfran' in ptr_lower:
            return 'US', 'CA', 'San Francisco', 'Verizon', 4
        return 'US', '', '', 'Verizon', 3
    
    # 快速字符串检测（避免正则）
    if '.cn' in ptr_lower or 'telecom.cn' in ptr_lower or 'unicom.cn' in ptr_lower:
        return 'CN', '', '', '', 2
    if '.jp' in ptr_lower:
        return 'JP', '', '', '', 2
    if '.kr' in ptr_lower:
        return 'KR', '', '', '', 2
    if '.uk' in ptr_lower:
        return 'GB', '', '', '', 2
    if '.de' in ptr_lower:
        return 'DE', '', '', '', 2
    if '.fr' in ptr_lower:
        return 'FR', '', '', '', 2
    if ptr_lower.endswith(('.com', '.net')):
        return 'US', '', '', '', 1
    
    return '', '', '', '', 0


def import_rdns_file(gz_path: str, db_path: str = "ip_locations.db", 
                     sample_rate: float = 1.0, min_confidence: int = 2,
                     batch_size: int = 10000):
    """
    导入 RDNS PTR 文件（优化版 - 批量插入）
    :param gz_path: gzip 文件路径
    :param sample_rate: 采样率 (1.0=全部)
    :param min_confidence: 最小置信度
    :param batch_size: 批量插入大小
    """
    print(f"导入 RDNS PTR: {gz_path}")
    print(f"采样率: {sample_rate}, 最小置信度: {min_confidence}, 批量: {batch_size}")
    
    conn = sqlite3.connect(db_path, timeout=60)
    cursor = conn.cursor()
    
    # 清空旧 L4 数据
    cursor.execute('DELETE FROM raw_l4_ptr')
    conn.commit()
    
    # 优化 SQLite 性能
    cursor.execute('PRAGMA journal_mode=WAL')
    cursor.execute('PRAGMA synchronous=NORMAL')
    cursor.execute('PRAGMA cache_size=100000')
    cursor.execute('PRAGMA temp_store=MEMORY')
    
    processed = 0
    matched = 0
    errors = 0
    batch = []
    
    # 统计
    country_stats = defaultdict(int)
    
    insert_sql = '''
        INSERT INTO raw_l4_ptr 
        (ip, ptr_record, domain_pattern, inferred_country, inferred_city, confidence)
        VALUES (?, ?, ?, ?, ?, ?)
    '''
    
    with gzip.open(gz_path, 'rt', encoding='utf-8', errors='ignore') as f:
        for line in f:
            # 采样 - 使用随机采样避免周期性偏差
            if sample_rate < 1.0:
                import random
                if random.random() > sample_rate:
                    processed += 1
                    continue
            
            try:
                data = json.loads(line)
                ip = data.get('ip', '')
                ptr_list = data.get('ptr', [])
                
                if not ip or not ptr_list:
                    processed += 1
                    continue
                
                ptr = ptr_list[0]
                
                # 解析位置
                country, region, city, isp, confidence = parse_ptr(ptr)
                
                if confidence >= min_confidence:
                    ip_int = int(ipaddress.ip_address(ip))
                    batch.append((ip_int, ptr, isp, country, city, confidence))
                    
                    matched += 1
                    country_stats[country] += 1
                    
                    # 批量插入
                    if len(batch) >= batch_size:
                        cursor.executemany(insert_sql, batch)
                        batch = []
                        
                        if matched % 50000 == 0:
                            conn.commit()
                            print(f"  处理 {processed:,}, 匹配 {matched:,}...")
                
                processed += 1
                
            except Exception as e:
                errors += 1
                if errors <= 3:
                    print(f"  错误: {e}")
                continue
    
    # 插入剩余数据
    if batch:
        cursor.executemany(insert_sql, batch)
    
    conn.commit()
    conn.close()
    
    print(f"\n导入完成:")
    print(f"  处理: {processed:,}")
    print(f"  匹配: {matched:,}")
    print(f"  错误: {errors}")
    print(f"\n国家分布:")
    for country, count in sorted(country_stats.items(), key=lambda x: -x[1])[:10]:
        print(f"  {country}: {count:,}")
    
    return matched


def query_ptr(ip: str, db_path: str = "ip_locations.db"):
    """查询 IP 的 PTR 信息"""
    try:
        ip_int = int(ipaddress.ip_address(ip))
    except:
        print(f"无效 IP: {ip}")
        return
    
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    
    cursor.execute('''
        SELECT ptr_record, inferred_country, inferred_city, confidence
        FROM raw_l4_ptr
        WHERE ip = ?
    ''', (ip_int,))
    
    row = cursor.fetchone()
    conn.close()
    
    if row:
        print(f"{ip}:")
        print(f"  PTR: {row[0]}")
        print(f"  推断: {row[1]}, {row[2]} (置信度: {row[3]})")
        return row
    else:
        print(f"{ip}: 无 PTR 记录")
        return None


if __name__ == '__main__':
    if len(sys.argv) < 2:
        print("用法:")
        print(f"  {sys.argv[0]} import <gz文件> [采样率] [最小置信度]")
        print(f"  {sys.argv[0]} query <IP>")
        print(f"\n示例:")
        print(f"  python {sys.argv[0]} import 2026-03_rdns_ipv4.json.gz")
        print(f"  python {sys.argv[0]} import 2026-03_rdns_ipv4.json.gz 0.1 3")
        print(f"  python {sys.argv[0]} query 8.8.8.8")
        sys.exit(1)
    
    command = sys.argv[1]
    
    if command == 'import':
        if len(sys.argv) < 3:
            print("请指定文件路径")
            sys.exit(1)
        
        gz_file = sys.argv[2]
        sample = float(sys.argv[3]) if len(sys.argv) > 3 else 1.0
        min_conf = int(sys.argv[4]) if len(sys.argv) > 4 else 2
        
        import_rdns_file(gz_file, sample_rate=sample, min_confidence=min_conf)
    
    elif command == 'query':
        if len(sys.argv) < 3:
            print("请指定 IP")
            sys.exit(1)
        query_ptr(sys.argv[2])
    
    else:
        print("未知命令")
        sys.exit(1)
