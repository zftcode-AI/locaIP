#!/usr/bin/env python3
"""
APNIC 国内 IP 段导入
从 APNIC 获取中国 IP 段分配数据
"""

import csv
import ipaddress
import sqlite3
import sys
import urllib.request
from pathlib import Path
from collections import defaultdict


APNIC_DELEGATED_URL = "https://ftp.apnic.net/apnic/stats/apnic/delegated-apnic-latest"


def download_apnic_data():
    """下载 APNIC 分配数据"""
    print(f"下载 APNIC 数据...")
    try:
        with urllib.request.urlopen(APNIC_DELEGATED_URL, timeout=60) as response:
            data = response.read().decode('utf-8')
        print(f"  下载完成: {len(data)} 字节")
        return data
    except Exception as e:
        print(f"  下载失败: {e}")
        return None


def parse_apnic_cn(data: str):
    """
    解析 APNIC 数据，提取中国 IPv4 段
    格式: registry|cc|type|start|value|date|status|opaque-id
    """
    cn_ranges = []
    
    for line in data.strip().split('\n'):
        if line.startswith('#') or not line.strip():
            continue
        
        parts = line.split('|')
        if len(parts) < 7:
            continue
        
        registry, cc, ip_type, start, value, date, status = parts[:7]
        
        # 只取中国的 IPv4 段
        if cc != 'CN' or ip_type != 'ipv4':
            continue
        
        # 计算 CIDR
        try:
            ip_start = ipaddress.ip_address(start)
            ip_count = int(value)
            
            # 转换为 CIDR 列表
            network = ipaddress.ip_network(f"{start}/{32-ip_count.bit_length()+1}", strict=False)
            
            # 获取运营商信息
            opaque_id = parts[7] if len(parts) > 7 else ''
            
            cn_ranges.append({
                'ip_start': int(ipaddress.ip_address(network.network_address)),
                'ip_end': int(ipaddress.ip_address(network.broadcast_address)),
                'cidr': str(network),
                'country': 'CN',
                'source': 'apnic',
                'status': status,
                'opaque_id': opaque_id
            })
            
        except Exception as e:
            continue
    
    return cn_ranges


def import_to_l1(ranges: list, db_path: str = "ip_locations.db"):
    """导入到 L1 表"""
    print(f"导入 {len(ranges)} 条中国 IP 段到 L1...")
    
    conn = sqlite3.connect(db_path, timeout=60)
    cursor = conn.cursor()
    
    # 统计
    inserted = 0
    skipped = 0
    
    for r in ranges:
        # 检查是否已有 L1 数据覆盖
        cursor.execute('''
            SELECT 1 FROM raw_l1_authoritative 
            WHERE ip_start <= ? AND ip_end >= ?
            LIMIT 1
        ''', (r['ip_start'], r['ip_end']))
        
        if cursor.fetchone():
            skipped += 1
            continue
        
        # 插入 APNIC 数据
        cursor.execute('''
            INSERT INTO raw_l1_authoritative 
            (ip_start, ip_end, source, country, city, latitude, longitude, raw_data)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        ''', (
            r['ip_start'], r['ip_end'],
            'apnic',
            'CN',
            '',  # 城市未知
            None, None,
            json.dumps({
                'cidr': r['cidr'],
                'status': r['status'],
                'opaque_id': r['opaque_id']
            })
        ))
        inserted += 1
        
        if inserted % 10000 == 0:
            conn.commit()
            print(f"  已导入 {inserted}...")
    
    conn.commit()
    conn.close()
    
    print(f"导入完成: 新增 {inserted}, 跳过 {skipped}")
    return inserted


def merge_cn_data(db_path: str = "ip_locations.db"):
    """
    重新融合，确保 APNIC CN 数据优先级正确
    """
    print("重新融合数据（包含 APNIC CN）...")
    
    # 直接调用 full_merge
    import subprocess
    result = subprocess.run(['python', 'full_merge.py'], 
                          capture_output=True, text=True)
    print(result.stdout)
    if result.stderr:
        print(result.stderr)


def query_cn_ip(ip: str, db_path: str = "ip_locations.db"):
    """查询 IP 是否在中国"""
    try:
        ip_int = int(ipaddress.ip_address(ip))
    except:
        print(f"无效 IP: {ip}")
        return
    
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    
    # 查 L1
    cursor.execute('''
        SELECT source, country, city FROM raw_l1_authoritative
        WHERE ip_start <= ? AND ip_end >= ?
        ORDER BY (source = 'geofeed') DESC
        LIMIT 1
    ''', (ip_int, ip_int))
    
    row = cursor.fetchone()
    conn.close()
    
    if row:
        print(f"{ip}:")
        print(f"  来源: {row[0]}")
        print(f"  国家: {row[1]}")
        if row[2]:
            print(f"  城市: {row[2]}")
    else:
        print(f"{ip}: 未找到")


if __name__ == '__main__':
    import json
    
    if len(sys.argv) < 2:
        print("用法:")
        print(f"  {sys.argv[0]} download  - 下载并导入 APNIC 数据")
        print(f"  {sys.argv[0]} query IP   - 查询 IP")
        sys.exit(1)
    
    command = sys.argv[1]
    
    if command == 'download':
        data = download_apnic_data()
        if data:
            ranges = parse_apnic_cn(data)
            print(f"找到 {len(ranges)} 个中国 IP 段")
            import_to_l1(ranges)
            merge_cn_data()
    
    elif command == 'query':
        if len(sys.argv) < 3:
            print("请指定 IP")
            sys.exit(1)
        query_cn_ip(sys.argv[2])
    
    else:
        print("未知命令")
        sys.exit(1)
