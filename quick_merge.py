#!/usr/bin/env python3
"""
快速融合脚本 - 仅处理 L1 Geofeed 数据到 merged 表
"""

import sqlite3
import sys


def quick_merge_l1(db_path: str = "ip_locations.db", batch_size: int = 10000):
    """快速融合 L1 数据"""
    conn = sqlite3.connect(db_path, timeout=60)
    cursor = conn.cursor()
    
    # 检查 L1 数据量
    cursor.execute('SELECT COUNT(*) FROM raw_l1_authoritative WHERE source = "geofeed"')
    total = cursor.fetchone()[0]
    print(f"L1 Geofeed 数据: {total} 条")
    
    if total == 0:
        print("没有 L1 数据需要融合")
        return
    
    # 清空旧融合数据
    cursor.execute('DELETE FROM merged_ip_locations')
    conn.commit()
    print("已清空旧融合数据")
    
    # 直接从 L1 复制到 merged（简化版融合）
    cursor.execute('''
        INSERT INTO merged_ip_locations 
        (ip_start, ip_end, 
         l1_source, l1_country, l1_city, l1_lat, l1_lon,
         final_country, final_city, final_lat, final_lon, 
         final_source, confidence)
        SELECT 
            ip_start, ip_end,
            source, country, city, latitude, longitude,
            country, city, latitude, longitude,
            'L1', 5
        FROM raw_l1_authoritative
        WHERE source = 'geofeed'
    ''')
    
    conn.commit()
    
    cursor.execute('SELECT COUNT(*) FROM merged_ip_locations')
    merged = cursor.fetchone()[0]
    print(f"融合完成: {merged} 条")
    
    conn.close()


def test_query(ip: str, db_path: str = "ip_locations.db"):
    """测试查询单个 IP"""
    import ipaddress
    
    ip_int = int(ipaddress.ip_address(ip))
    
    conn = sqlite3.connect(db_path, timeout=30)
    cursor = conn.cursor()
    
    cursor.execute('''
        SELECT ip_start, ip_end, final_country, final_city, final_source, confidence
        FROM merged_ip_locations
        WHERE ip_start <= ? AND ip_end >= ?
        LIMIT 1
    ''', (ip_int, ip_int))
    
    row = cursor.fetchone()
    conn.close()
    
    if row:
        print(f"{ip} -> {row[2]}, {row[3]} (来源: {row[4]}, 置信度: {row[5]})")
        print(f"  IP段: {ipaddress.ip_address(row[0])} - {ipaddress.ip_address(row[1])}")
    else:
        print(f"{ip} -> 未找到")


if __name__ == '__main__':
    if len(sys.argv) > 1 and sys.argv[1] == 'query':
        # 查询模式: python quick_merge.py query 157.167.3.1
        ip = sys.argv[2] if len(sys.argv) > 2 else "157.167.3.1"
        test_query(ip)
    else:
        # 融合模式
        quick_merge_l1()
        
        # 测试查询
        print("\n测试查询:")
        test_query("213.21.200.1")
        test_query("192.109.82.10")
        test_query("192.109.82.26")
        test_query("157.167.3.1")
