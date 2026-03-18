#!/usr/bin/env python3
"""
导入 PeeringDB 页面导出的 JSON 文件
"""

import json
import sqlite3
import sys
from pathlib import Path


def import_peeringdb_json(json_path: str, db_path: str = "ip_locations.db"):
    """导入 PeeringDB JSON 导出文件"""
    
    with open(json_path, 'r', encoding='utf-8') as f:
        data = json.load(f)
    
    # 数据可能在 'data' 键下，也可能是列表
    if isinstance(data, dict) and 'data' in data:
        networks = data['data']
    elif isinstance(data, list):
        networks = data
    else:
        print("无法识别的 JSON 格式")
        return
    
    print(f"找到 {len(networks)} 个网络记录")
    
    conn = sqlite3.connect(db_path, timeout=60)
    cursor = conn.cursor()
    
    count = 0
    errors = 0
    
    for net in networks:
        try:
            asn = net.get('asn')
            if not asn:
                continue
            
            org_name = net.get('name', '')
            
            # 从 org 信息获取国家/城市
            org = net.get('org', {})
            country = org.get('country', '') if org else ''
            city = org.get('city', '') if org else ''
            
            # 提取设施信息
            facilities = []
            for fac in net.get('netfac_set', []):
                fac_info = {
                    'name': fac.get('name', ''),
                    'city': fac.get('city', ''),
                    'country': fac.get('country', ''),
                }
                if fac_info['city'] or fac_info['country']:
                    facilities.append(fac_info)
            
            facilities_json = json.dumps(facilities)
            
            # 推断主位置
            if not city or not country:
                # 从设施推断
                for fac in facilities:
                    if fac.get('city') and fac.get('country'):
                        city = fac['city']
                        country = fac['country']
                        break
            
            cursor.execute('''
                INSERT OR REPLACE INTO raw_l3_asn_info 
                (asn, org_name, country, city, latitude, longitude, facilities, source)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ''', (
                asn, org_name, country, city, None, None, facilities_json, 'peeringdb_export'
            ))
            
            count += 1
            
            if count % 1000 == 0:
                conn.commit()
                print(f"  已导入 {count}...")
                
        except Exception as e:
            errors += 1
            continue
    
    conn.commit()
    conn.close()
    
    print(f"导入完成: {count} 条, 错误: {errors} 条")


if __name__ == '__main__':
    if len(sys.argv) < 2:
        print("用法: python import_peeringdb_json.py <peeringdb_export.json>")
        sys.exit(1)
    
    json_file = sys.argv[1]
    import_peeringdb_json(json_file)
