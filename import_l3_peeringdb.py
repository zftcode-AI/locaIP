#!/usr/bin/env python3
"""
L3 层 PeeringDB 数据导入
ASN → 地区/设施位置
"""

import argparse
import json
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))


def fetch_peeringdb_net(asn: int, api_key: str = None) -> dict:
    """
    从 PeeringDB API 获取 ASN 信息
    需要 API Key (免费注册)
    """
    import urllib.request
    import urllib.error
    
    url = f"https://www.peeringdb.com/api/net?asn={asn}"
    
    headers = {}
    if api_key:
        headers['Authorization'] = f'Api-Key {api_key}'
    
    try:
        req = urllib.request.Request(url, headers=headers)
        with urllib.request.urlopen(req, timeout=30) as response:
            data = json.loads(response.read().decode('utf-8'))
            if data.get('data') and len(data['data']) > 0:
                return data['data'][0]
    except urllib.error.HTTPError as e:
        if e.code == 404:
            print(f"  ASN {asn} 在 PeeringDB 中未找到")
        else:
            print(f"  查询 ASN {asn} 失败: {e}")
    except Exception as e:
        print(f"  查询 ASN {asn} 错误: {e}")
    
    return None


def parse_peeringdb_data(net_data: dict) -> dict:
    """解析 PeeringDB 返回的数据"""
    if not net_data:
        return None
    
    result = {
        'asn': net_data.get('asn'),
        'org_name': net_data.get('name', ''),
        'website': net_data.get('website', ''),
        'info_type': net_data.get('info_type', ''),  # 网络类型
        'info_prefixes4': net_data.get('info_prefixes4', 0),
    }
    
    # 提取设施信息
    facilities = []
    for fac in net_data.get('netfac_set', []):
        fac_info = {
            'name': fac.get('name', ''),
            'city': fac.get('city', ''),
            'country': fac.get('country', ''),
            'latitude': fac.get('latitude'),
            'longitude': fac.get('longitude'),
        }
        if fac_info['city'] or fac_info['country']:
            facilities.append(fac_info)
    
    result['facilities'] = facilities
    
    # 提取 IXP 信息
    ixps = []
    for ix in net_data.get('netixlan_set', []):
        ix_info = {
            'name': ix.get('name', ''),
            'city': ix.get('city', ''),
            'country': ix.get('country', ''),
        }
        if ix_info['city'] or ix_info['country']:
            ixps.append(ix_info)
    
    result['ixps'] = ixps
    
    # 推断主位置（设施最多的城市）
    city_count = {}
    for fac in facilities:
        city = fac.get('city', '')
        country = fac.get('country', '')
        if city and country:
            key = f"{country},{city}"
            city_count[key] = city_count.get(key, 0) + 1
    
    if city_count:
        # 取设施最多的城市
        main_location = max(city_count.items(), key=lambda x: x[1])
        country, city = main_location[0].split(',', 1)
        result['inferred_country'] = country
        result['inferred_city'] = city
        result['confidence'] = min(4, 2 + len(facilities) // 3)  # 设施越多置信度越高
    else:
        # 无法推断位置
        result['inferred_country'] = None
        result['inferred_city'] = None
        result['confidence'] = 1
    
    return result


def import_asn_info(asn: int, db_path: str = "ip_locations.db", api_key: str = None):
    """导入单个 ASN 的信息"""
    print(f"查询 ASN {asn}...")
    
    net_data = fetch_peeringdb_net(asn, api_key)
    if not net_data:
        return False
    
    parsed = parse_peeringdb_data(net_data)
    if not parsed:
        return False
    
    # 保存到数据库
    conn = sqlite3.connect(db_path, timeout=60)
    cursor = conn.cursor()
    
    facilities_json = json.dumps(parsed.get('facilities', []))
    
    cursor.execute('''
        INSERT OR REPLACE INTO raw_l3_asn_info 
        (asn, org_name, country, city, latitude, longitude, facilities, source)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
    ''', (
        parsed['asn'],
        parsed['org_name'],
        parsed.get('inferred_country', ''),
        parsed.get('inferred_city', ''),
        None,  # latitude
        None,  # longitude
        facilities_json,
        'peeringdb'
    ))
    
    conn.commit()
    conn.close()
    
    print(f"  ✓ {parsed['org_name']}")
    print(f"  位置: {parsed.get('inferred_country')}, {parsed.get('inferred_city')}")
    print(f"  设施数: {len(parsed.get('facilities', []))}")
    
    return True


def batch_import_from_l2(db_path: str = "ip_locations.db", api_key: str = None, limit: int = 100):
    """
    从 L2 的 ASN 列表批量导入 L3 信息
    只处理前 N 个不同的 ASN（避免 API 限流）
    """
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    
    # 获取 L2 中所有唯一的 ASN
    cursor.execute('''
        SELECT DISTINCT asn FROM raw_l2_asn_mapping 
        WHERE asn NOT IN (SELECT asn FROM raw_l3_asn_info)
        ORDER BY asn
        LIMIT ?
    ''', (limit,))
    
    asns = [row[0] for row in cursor.fetchall()]
    conn.close()
    
    print(f"找到 {len(asns)} 个待查询的 ASN")
    print("-" * 50)
    
    success = 0
    for asn in asns:
        if import_asn_info(asn, db_path, api_key):
            success += 1
    
    print("-" * 50)
    print(f"导入完成: {success}/{len(asns)}")


# ASN 所属国家映射（用于修正显示）
ASN_COUNTRY_MAP = {
    # 中国运营商
    4134: 'CN',  # 中国电信
    4837: 'CN',  # 中国联通
    9808: 'CN',  # 中国移动
    7497: 'CN',  # 中国科技网
    4538: 'CN',  # 中国教育网
    9394: 'CN',  # 中国铁通
    58453: 'CN', # 中国广电网
    # 美国主要运营商
    7922: 'US',  # Comcast
    701: 'US',   # Verizon
    7018: 'US',  # AT&T
    7843: 'US',  # Charter
    3356: 'US',  # Level3
    174: 'US',   # Cogent
    1299: 'SE',  # Telia
    3257: 'DE',  # GTT
    2914: 'US',  # NTT America
    3491: 'US',  # PCCW
    6762: 'IT',  # Telecom Italia
    6830: 'AT',  # Liberty Global
    5511: 'FR',  # Orange
    6453: 'US',  # TATA
    6461: 'US',  # Zayo
    12956: 'ES', # Telefonica
    15412: 'GB', # Colt
    20485: 'RU', # TransTelecom
    2497: 'JP',  # IIJ
    2516: 'JP',  # KDDI
    4725: 'JP',  # SoftBank
    4766: 'KR',  # KINX
    9318: 'KR',  # SK Broadband
    4760: 'HK',  # HKT
    4637: 'HK',  # Telstra
    7545: 'AU',  # TPG
    1221: 'AU',  # Telstra Australia
    9505: 'TW',  # TWGate
    3462: 'TW',  # Hinet
    24158: 'TW', # Taiwan Mobile
    3786: 'TH',  # Loxley
    45629: 'IN', # Jio
    55836: 'IN', # Reliance
    9829: 'IN',  # BSNL
    9498: 'IN',  # Bharti Airtel
    2856: 'GB',  # BT
    3215: 'FR',  # Orange France
    3320: 'DE',  # DTAG
    6830: 'AT',  # A1
    3303: 'CH',  # Swisscom
    5391: 'HR',  # T-Com
    9145: 'TR',  # Turk Telecom
    36947: 'ZA', # MTN
    37168: 'ZA', # Cell-C
    8452: 'EG',  # TE Data
    36935: 'NG', # Vodacom
    37061: 'KE', # Safaricom
    36903: 'MA', # Maroc Telecom
    37457: 'ZA', # Telkom SA
    15169: 'US', # Google
    16509: 'US', # Amazon
    8075: 'US',  # Microsoft
    13335: 'US', # Cloudflare
    32934: 'US', # Facebook
    46489: 'US', # Twitch
    16591: 'US', # Google Fiber
    15133: 'US', # Verizon Business
    20940: 'US', # Akamai
    22822: 'US', # Limelight
    2906: 'US',  # Netflix
    6185: 'US',  # Apple
    714: 'US',   # Apple
    6185: 'US',  # Apple
    2709: 'US',  # Cogent (Google)
    43531: 'US', # Google (Youtube)
}


def query_asn_location(asn: int, db_path: str = "ip_locations.db"):
    """查询 ASN 的位置信息"""
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    
    cursor.execute('''
        SELECT asn, org_name, country, city, facilities
        FROM raw_l3_asn_info
        WHERE asn = ?
    ''', (asn,))
    
    row = cursor.fetchone()
    conn.close()
    
    if row:
        asn_id, org_name, db_country, db_city, facilities_json = row
        
        # 优先使用 ASN 映射的国家
        actual_country = ASN_COUNTRY_MAP.get(asn, db_country)
        
        print(f"ASN {asn_id}: {org_name}")
        
        # 如果国家不匹配，显示修正信息
        if actual_country != db_country:
            print(f"  数据库位置: {db_country}, {db_city}")
            print(f"  实际归属: {actual_country} (基于ASN注册信息)")
        else:
            print(f"  推断位置: {db_country}, {db_city}")
        
        facilities = json.loads(facilities_json) if facilities_json else []
        print(f"  设施数: {len(facilities)}")
        
        # 筛选该国家的设施
        if facilities:
            country_facs = [f for f in facilities if f.get('country') == actual_country]
            other_facs = [f for f in facilities if f.get('country') != actual_country]
            
            if country_facs:
                print(f"  {actual_country} 国内设施 ({len(country_facs)}个):")
                for fac in country_facs[:5]:
                    print(f"    - {fac.get('city')}, {fac.get('country')}")
            
            if other_facs and len(country_facs) < 5:
                print(f"  国际设施 ({len(other_facs)}个):")
                for fac in other_facs[:5-len(country_facs)]:
                    print(f"    - {fac.get('city')}, {fac.get('country')}")
                    
        return True
    else:
        print(f"ASN {asn} 未找到")
        return False


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='L3 PeeringDB ASN 信息导入')
    parser.add_argument('command', choices=['import', 'batch', 'query'],
                        help='import(导入单个ASN), batch(批量导入), query(查询)')
    parser.add_argument('asn_or_limit', nargs='?', type=int,
                        help='ASN 号码或批量限制数量')
    parser.add_argument('--db', default='ip_locations.db', help='数据库路径')
    parser.add_argument('--api-key', help='PeeringDB API Key')
    
    args = parser.parse_args()
    
    if args.command == 'import':
        if not args.asn_or_limit:
            print("错误: 请指定 ASN")
            sys.exit(1)
        import_asn_info(args.asn_or_limit, args.db, args.api_key)
    
    elif args.command == 'batch':
        limit = args.asn_or_limit or 100
        batch_import_from_l2(args.db, args.api_key, limit)
    
    elif args.command == 'query':
        if not args.asn_or_limit:
            print("错误: 请指定 ASN")
            sys.exit(1)
        query_asn_location(args.asn_or_limit, args.db)
