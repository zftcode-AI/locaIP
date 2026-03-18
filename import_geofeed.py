#!/usr/bin/env python3
"""
Geofeed CSV 导入脚本
用法: python import_geofeed.py <geofeed.csv> [--db ip_locations.db]
"""

import argparse
import sys
from pathlib import Path

# 确保能导入核心模块
sys.path.insert(0, str(Path(__file__).parent))

from ip_locator_core import IPLocationDatabase


def main():
    parser = argparse.ArgumentParser(description='导入 Geofeed CSV 到 IP 定位数据库')
    parser.add_argument('csv_file', help='Geofeed CSV 文件路径')
    parser.add_argument('--db', default='ip_locations.db', help='数据库文件路径 (默认: ip_locations.db)')
    parser.add_argument('--batch-size', type=int, default=1000, help='批量插入大小 (默认: 1000)')
    
    args = parser.parse_args()
    
    # 检查文件是否存在
    csv_path = Path(args.csv_file)
    if not csv_path.exists():
        print(f"错误: 文件不存在: {csv_path}")
        sys.exit(1)
    
    print(f"导入 Geofeed 文件: {csv_path}")
    print(f"目标数据库: {args.db}")
    print("-" * 50)
    
    # 初始化数据库
    db = IPLocationDatabase(args.db)
    
    try:
        # 导入数据
        count = db.import_geofeed(str(csv_path), batch_size=args.batch_size)
        print(f"\n成功导入 {count} 条 Geofeed 记录")
        
        # 显示统计
        import sqlite3
        conn = sqlite3.connect(args.db)
        cursor = conn.cursor()
        
        cursor.execute('SELECT COUNT(*) FROM raw_l1_authoritative WHERE source = "geofeed"')
        total = cursor.fetchone()[0]
        print(f"数据库中 Geofeed 记录总数: {total}")
        
        # 显示样本
        print("\n样本数据:")
        cursor.execute('''
            SELECT ip_start, ip_end, country, region, city 
            FROM raw_l1_authoritative 
            WHERE source = "geofeed"
            LIMIT 5
        ''')
        for row in cursor.fetchall():
            from ip_locator_core import IPConverter
            start_ip = IPConverter.int_to_ip(row[0])
            end_ip = IPConverter.int_to_ip(row[1])
            print(f"  {start_ip}-{end_ip}: {row[2]}, {row[3]}, {row[4]}")
        
        conn.close()
        
    except Exception as e:
        print(f"导入失败: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
    finally:
        db.close()


if __name__ == '__main__':
    main()
