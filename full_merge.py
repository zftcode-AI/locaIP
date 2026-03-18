#!/usr/bin/env python3
"""
完整四层数据融合
L1(Geofeed) > L2+L3(ASN+PeeringDB) > L4(PTR)
"""

import sqlite3
import ipaddress


def full_merge(db_path: str = "ip_locations.db"):
    """执行完整融合"""
    conn = sqlite3.connect(db_path, timeout=60)
    cursor = conn.cursor()
    
    print("开始完整数据融合...")
    print("-" * 50)
    
    # 1. 清空旧融合数据
    cursor.execute('DELETE FROM merged_ip_locations')
    conn.commit()
    print("1. 已清空旧融合数据")
    
    # 2. 先导入 L1 数据（最高优先级）
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
    ''')
    l1_count = cursor.rowcount
    conn.commit()
    print(f"2. L1 数据导入: {l1_count} 条")
    
    # 3. 处理 L2+L3 数据（对不在 L1 中的 IP）
    # 获取所有 L2 的 IP 段
    cursor.execute('SELECT DISTINCT ip_start, ip_end FROM raw_l2_asn_mapping')
    l2_ranges = cursor.fetchall()
    print(f"3. L2 IP 段数量: {len(l2_ranges)}")
    
    # 为每个 L2 段查找 ASN，然后找 L3 位置
    l23_count = 0
    for ip_start, ip_end in l2_ranges:
        # 检查是否已有 L1 数据覆盖
        cursor.execute('''
            SELECT 1 FROM merged_ip_locations 
            WHERE ip_start = ? AND ip_end = ? AND final_source = 'L1'
        ''', (ip_start, ip_end))
        if cursor.fetchone():
            continue  # 已有 L1 数据，跳过
        
        # 获取 ASN
        cursor.execute('''
            SELECT asn FROM raw_l2_asn_mapping
            WHERE ip_start = ? AND ip_end = ?
            LIMIT 1
        ''', (ip_start, ip_end))
        row = cursor.fetchone()
        if not row:
            continue
        
        asn = row[0]
        
        # 获取 L3 位置
        cursor.execute('''
            SELECT org_name, country, city, latitude, longitude
            FROM raw_l3_asn_info
            WHERE asn = ? AND country != ''
            LIMIT 1
        ''', (asn,))
        l3 = cursor.fetchone()
        
        if l3:
            org_name, country, city, lat, lon = l3
            confidence = 3 if city else 2
            
            cursor.execute('''
                INSERT INTO merged_ip_locations 
                (ip_start, ip_end,
                 l2_asn, l2_source,
                 l3_country, l3_city, l3_lat, l3_lon,
                 final_country, final_city, final_lat, final_lon,
                 final_source, confidence)
                VALUES (?, ?, ?, 'caida', ?, ?, ?, ?, ?, ?, ?, ?, 'L3', ?)
            ''', (ip_start, ip_end, asn, country, city, lat, lon,
                  country, city, lat, lon, confidence))
            l23_count += 1
            
            if l23_count % 10000 == 0:
                conn.commit()
                print(f"   已融合 L2+L3: {l23_count}...")
    
    conn.commit()
    print(f"   L2+L3 融合完成: {l23_count} 条")
    
    # 4. 统计结果
    cursor.execute('SELECT COUNT(*) FROM merged_ip_locations')
    total = cursor.fetchone()[0]
    
    cursor.execute('SELECT COUNT(*) FROM merged_ip_locations WHERE final_source = "L1"')
    l1_final = cursor.fetchone()[0]
    
    cursor.execute('SELECT COUNT(*) FROM merged_ip_locations WHERE final_source = "L3"')
    l3_final = cursor.fetchone()[0]
    
    conn.close()
    
    print("-" * 50)
    print("融合完成!")
    print(f"  总记录: {total}")
    print(f"  L1(Geofeed): {l1_final}")
    print(f"  L3(PeeringDB): {l3_final}")
    
    return total


def test_query(ip: str, db_path: str = "ip_locations.db"):
    """测试查询"""
    import ipaddress
    
    ip_int = int(ipaddress.ip_address(ip))
    
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    
    cursor.execute('''
        SELECT ip_start, ip_end, l1_source, l2_asn,
               l3_country, l3_city,
               final_country, final_city, final_source, confidence
        FROM merged_ip_locations
        WHERE ip_start <= ? AND ip_end >= ?
        ORDER BY confidence DESC
        LIMIT 1
    ''', (ip_int, ip_int))
    
    row = cursor.fetchone()
    conn.close()
    
    if row:
        print(f"{ip}:")
        print(f"  来源: {row[8]} (置信度: {row[9]})")
        print(f"  位置: {row[6]}, {row[7]}")
        if row[3]:  # ASN
            print(f"  ASN: {row[3]}")
        print(f"  IP段: {ipaddress.ip_address(row[0])} - {ipaddress.ip_address(row[1])}")
    else:
        print(f"{ip}: 未找到")


if __name__ == '__main__':
    import sys
    
    if len(sys.argv) > 1 and sys.argv[1] == 'query':
        ip = sys.argv[2] if len(sys.argv) > 2 else "8.8.8.8"
        test_query(ip)
    else:
        full_merge()
        
        # 测试几个 IP
        print("\n测试查询:")
        test_query("8.8.8.8")
        test_query("1.1.1.1")
        test_query("157.167.3.1")
