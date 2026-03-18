#!/usr/bin/env python3
"""
导入 PeeringDB 全量 dump 文件 (peeringdb_2_dump_*.json)
包含 net, fac, netfac 等完整关系
"""

import json
import sqlite3
import sys
from collections import defaultdict


def import_peeringdb_dump(json_path: str, db_path: str = "ip_locations.db"):
    """导入 PeeringDB 全量 dump"""
    
    print(f"加载 PeeringDB dump: {json_path}")
    with open(json_path, 'r', encoding='utf-8') as f:
        data = json.load(f)
    
    # 建立设施 ID → 位置 映射
    fac_locations = {}
    fac_data = data.get('fac', {})
    if isinstance(fac_data, dict):
        fac_list = fac_data.get('data', [])
    else:
        fac_list = fac_data if isinstance(fac_data, list) else []
    
    for fac in fac_list:
        fac_id = fac.get('id')
        if fac_id:
            fac_locations[fac_id] = {
                'name': fac.get('name', ''),
                'city': fac.get('city', ''),
                'country': fac.get('country', ''),
                'state': fac.get('state', ''),
                'latitude': fac.get('latitude'),
                'longitude': fac.get('longitude'),
            }
    
    print(f"设施数量: {len(fac_locations)}")
    
    # 建立 ASN → 设施列表 映射
    asn_facilities = defaultdict(list)
    netfac_data = data.get('netfac', {})
    if isinstance(netfac_data, dict):
        netfac_list = netfac_data.get('data', [])
    else:
        netfac_list = netfac_data if isinstance(netfac_data, list) else []
    
    for netfac in netfac_list:
        net_id = netfac.get('net_id')
        fac_id = netfac.get('fac_id')
        if net_id and fac_id and fac_id in fac_locations:
            asn_facilities[net_id].append(fac_locations[fac_id])
    
    print(f"网络-设施关联数量: {len(data.get('netfac', []))}")
    
    # 处理网络数据
    conn = sqlite3.connect(db_path, timeout=60)
    cursor = conn.cursor()
    
    count = 0
    skipped = 0
    
    # net 是字典，数据在 'data' 键下
    net_data = data.get('net', {})
    if isinstance(net_data, dict):
        net_list = net_data.get('data', [])
    else:
        net_list = net_data if isinstance(net_data, list) else []
    
    for net in net_list:
        net_id = net.get('id')
        asn = net.get('asn')
        name = net.get('name', '')
        
        if not asn:
            skipped += 1
            continue
        
        # 获取该 ASN 的设施列表
        facilities = asn_facilities.get(net_id, [])
        
        # 推断主位置（设施最多的城市）
        city_count = defaultdict(int)
        city_info = {}
        
        for fac in facilities:
            city = fac.get('city', '')
            country = fac.get('country', '')
            if city and country:
                key = (country, city)
                city_count[key] += 1
                city_info[key] = fac  # 保存完整信息
        
        if city_count:
            # 取设施最多的城市
            main_key = max(city_count.items(), key=lambda x: x[1])[0]
            main_fac = city_info[main_key]
            country, city = main_key
            confidence = min(4, 2 + len(facilities) // 3)
        else:
            # 无设施信息
            country = ''
            city = ''
            main_fac = {}
            confidence = 1
        
        facilities_json = json.dumps(facilities)
        
        try:
            cursor.execute('''
                INSERT OR REPLACE INTO raw_l3_asn_info 
                (asn, org_name, country, city, latitude, longitude, facilities, source)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ''', (
                asn,
                name,
                country,
                city,
                main_fac.get('latitude'),
                main_fac.get('longitude'),
                facilities_json,
                'peeringdb_dump'
            ))
            count += 1
            
            if count % 1000 == 0:
                conn.commit()
                print(f"  已导入 {count}...")
                
        except Exception as e:
            skipped += 1
            continue
    
    conn.commit()
    conn.close()
    
    print(f"导入完成: {count} 条, 跳过: {skipped} 条")
    return count


def query_asn_from_dump(asn: int, json_path: str):
    """从 dump 文件直接查询 ASN（不导入数据库）"""
    with open(json_path, 'r', encoding='utf-8') as f:
        data = json.load(f)
    
    # 获取 net 列表
    net_data = data.get('net', {})
    net_list = net_data.get('data', []) if isinstance(net_data, dict) else net_data
    
    # 找网络
    net_info = None
    for net in net_list:
        if net.get('asn') == asn:
            net_info = net
            break
    
    if not net_info:
        print(f"ASN {asn} 未找到")
        return
    
    print(f"ASN {asn}: {net_info.get('name')}")
    
    # 获取 netfac 列表
    netfac_data = data.get('netfac', {})
    netfac_list = netfac_data.get('data', []) if isinstance(netfac_data, dict) else netfac_data
    
    # 找设施（netfac 里已包含位置信息）
    net_id = net_info.get('id')
    facilities = [nf for nf in netfac_list if nf.get('net_id') == net_id]
    
    print(f"设施数量: {len(facilities)}")
    
    # 去重显示
    seen = set()
    for fac in facilities[:10]:  # 只显示前10个
        city = fac.get('city', '')
        country = fac.get('country', '')
        name = fac.get('name', '')
        key = (name, city, country)
        if key not in seen:
            seen.add(key)
            print(f"  - {name}: {city}, {country}")
    
    if len(facilities) > 10:
        print(f"  ... 还有 {len(facilities) - 10} 个设施")


if __name__ == '__main__':
    if len(sys.argv) < 2:
        print("用法:")
        print(f"  导入: python {sys.argv[0]} import peeringdb_2_dump_*.json")
        print(f"  查询: python {sys.argv[0]} query ASN peeringdb_2_dump_*.json")
        sys.exit(1)
    
    command = sys.argv[1]
    
    if command == 'import' and len(sys.argv) >= 3:
        json_file = sys.argv[2]
        import_peeringdb_dump(json_file)
    
    elif command == 'query' and len(sys.argv) >= 4:
        asn = int(sys.argv[2])
        json_file = sys.argv[3]
        query_asn_from_dump(asn, json_file)
    
    else:
        print("参数错误")
        sys.exit(1)
