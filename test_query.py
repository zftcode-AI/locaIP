#!/usr/bin/env python3
"""
IP 定位查询测试脚本
"""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))

from ip_locator_core import IPLocationDatabase, IPConverter


def test_basic_query(db_path: str = "ip_locations.db"):
    """基础查询测试"""
    print("=" * 60)
    print("IP 定位查询测试")
    print("=" * 60)
    
    db = IPLocationDatabase(db_path)
    
    # 1. 先检查数据库统计
    print("\n【数据库统计】")
    import sqlite3
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    
    cursor.execute('SELECT COUNT(*) FROM raw_l1_authoritative WHERE source = "geofeed"')
    l1_count = cursor.fetchone()[0]
    print(f"  L1 Geofeed 记录: {l1_count} 条")
    
    cursor.execute('SELECT COUNT(*) FROM raw_l2_asn_mapping')
    l2_count = cursor.fetchone()[0]
    print(f"  L2 ASN 映射: {l2_count} 条")
    
    cursor.execute('SELECT COUNT(*) FROM raw_l3_asn_info')
    l3_count = cursor.fetchone()[0]
    print(f"  L3 ASN 信息: {l3_count} 条")
    
    cursor.execute('SELECT COUNT(*) FROM merged_ip_locations')
    merged_count = cursor.fetchone()[0]
    print(f"  融合后记录: {merged_count} 条")
    
    conn.close()
    
    if l1_count == 0:
        print("\n⚠️  没有 Geofeed 数据，请先导入数据")
        db.close()
        return
    
    # 2. 加载到内存
    print("\n【加载到内存索引】")
    db.load_to_memory()
    
    # 3. 测试查询
    print("\n【查询测试】")
    
    # 测试用例
    test_ips = [
        "213.21.200.1",      # 应该在 LV-RIX Riga
        "192.109.82.10",     # 应该在 DE-BE Berlin
        "192.109.82.26",     # 应该在 DE-HE Frankfurt (/32精确匹配)
        "192.109.82.75",     # 应该在 DE-HE Frankfurt (/32精确匹配)
        "8.8.8.8",           # 未知IP
        "1.1.1.1",           # 未知IP
    ]
    
    for ip in test_ips:
        result = db.query(ip)
        if result:
            print(f"  {ip:>15} -> {result.country:>4}, {result.city:>15} "
                  f"(来源: {result.source_detail}, 置信度: {result.confidence})")
        else:
            print(f"  {ip:>15} -> 未找到")
    
    # 4. 详细查询测试
    print("\n【详细查询示例】")
    detail_ip = "213.21.200.1"
    print(f"查询 {detail_ip} 的详细信息:")
    
    detail = db.query_detail(detail_ip)
    if 'final' in detail:
        final = detail['final']
        print(f"  最终位置: {final.get('final_country')}, {final.get('final_city')}")
        print(f"  数据来源: {final.get('final_source')}")
        print(f"  置信度: {final.get('confidence')}")
    
    if 'L1' in detail.get('layers', {}):
        l1_data = detail['layers']['L1'][0]
        print(f"  L1原始: {l1_data.get('country')}, {l1_data.get('city')}")
    
    db.close()
    print("\n测试完成!")


def interactive_query(db_path: str = "ip_locations.db"):
    """交互式查询"""
    print("\n" + "=" * 60)
    print("交互式查询模式 (输入 'quit' 退出)")
    print("=" * 60)
    
    db = IPLocationDatabase(db_path)
    db.load_to_memory()
    
    while True:
        try:
            ip = input("\n请输入IP (或 'quit'): ").strip()
            if ip.lower() in ('quit', 'exit', 'q'):
                break
            
            if not ip:
                continue
            
            # 验证IP格式
            try:
                IPConverter.ip_to_int(ip)
            except ValueError:
                print(f"  ❌ 无效的IP格式: {ip}")
                continue
            
            result = db.query(ip)
            if result:
                print(f"  ✅ {ip}")
                print(f"     位置: {result.country}, {result.city}")
                print(f"     坐标: {result.latitude}, {result.longitude}")
                print(f"     来源: {result.source_detail} (置信度: {result.confidence})")
                print(f"     IP段: {result.ip_prefix}")
            else:
                print(f"  ❌ 未找到 {ip} 的位置信息")
                
        except KeyboardInterrupt:
            print("\n退出")
            break
        except Exception as e:
            print(f"  错误: {e}")
    
    db.close()
    print("\n再见!")


if __name__ == '__main__':
    import argparse
    
    parser = argparse.ArgumentParser(description='IP定位查询测试')
    parser.add_argument('--db', default='ip_locations.db', help='数据库路径')
    parser.add_argument('--interactive', '-i', action='store_true', help='交互模式')
    
    args = parser.parse_args()
    
    if args.interactive:
        interactive_query(args.db)
    else:
        test_basic_query(args.db)
