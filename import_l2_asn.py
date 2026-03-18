#!/usr/bin/env python3
"""
L2 层 ASN 数据导入脚本
支持 CAIDA pfx2as 和 BGP 数据
"""

import argparse
import gzip
import sqlite3
import sys
from pathlib import Path
from ipaddress import ip_network

sys.path.insert(0, str(Path(__file__).parent))
from ip_locator_core import IPConverter


def import_caida_pfx2as(file_path: str, db_path: str = "ip_locations.db", batch_size: int = 5000):
    """
    导入 CAIDA pfx2as 文件
    格式: ip_start prefix_len asn
    示例: 16777216 24 13335
    """
    conn = sqlite3.connect(db_path, timeout=60)
    cursor = conn.cursor()
    
    # 清空旧数据
    cursor.execute('DELETE FROM raw_l2_asn_mapping WHERE source = "caida"')
    conn.commit()
    
    opener = gzip.open if file_path.endswith('.gz') else open
    
    batch = []
    count = 0
    errors = 0
    
    print(f"导入 CAIDA pfx2as: {file_path}")
    
    with opener(file_path, 'rt', encoding='utf-8', errors='ignore') as f:
        for line_num, line in enumerate(f, 1):
            line = line.strip()
            if not line or line.startswith('#'):
                continue
            
            parts = line.split('\t')
            if len(parts) < 3:
                parts = line.split()
            
            if len(parts) < 3:
                errors += 1
                continue
            
            try:
                # 解析: ip_start(可以是IP字符串或整数) prefix_len asn
                ip_start_str = parts[0]
                prefix_len = int(parts[1])
                
                # 处理多 ASN 情况 (如 "8034,8035" 取第一个)
                asn_str = parts[2].split(',')[0].strip()
                asn = int(asn_str)
                
                # IP 可能是字符串格式(1.0.0.0)或整数格式(16777216)
                if '.' in ip_start_str:
                    # IP 字符串格式
                    import ipaddress
                    ip_start = int(ipaddress.ip_address(ip_start_str))
                else:
                    # 整数格式
                    ip_start = int(ip_start_str)
                
                # 确保 IP 在有效范围 (IPv4)
                if ip_start < 0 or ip_start > 4294967295:
                    errors += 1
                    continue
                
                # 计算结束 IP
                ip_end = ip_start + (1 << (32 - prefix_len)) - 1
                
                # 确保结束 IP 不溢出
                if ip_end > 4294967295:
                    ip_end = 4294967295
                
                # 再次检查数值范围
                if not (0 <= ip_start <= 4294967295 and 0 <= ip_end <= 4294967295 and 0 <= asn <= 4294967295):
                    errors += 1
                    continue
                
                batch.append((ip_start, ip_end, asn, 'caida'))
                
                if len(batch) >= batch_size:
                    cursor.executemany('''
                        INSERT OR REPLACE INTO raw_l2_asn_mapping 
                        (ip_start, ip_end, asn, source)
                        VALUES (?, ?, ?, ?)
                    ''', batch)
                    conn.commit()
                    count += len(batch)
                    batch = []
                    
                    if count % 50000 == 0:
                        print(f"  已导入 {count} 条...")
                        
            except (ValueError, IndexError) as e:
                errors += 1
                if errors <= 3:
                    print(f"  解析错误 行{line_num}: {line[:50]}... - {e}")
                continue
    
    # 插入剩余
    if batch:
        cursor.executemany('''
            INSERT OR REPLACE INTO raw_l2_asn_mapping 
            (ip_start, ip_end, asn, source)
            VALUES (?, ?, ?, ?)
        ''', batch)
        conn.commit()
        count += len(batch)
    
    conn.close()
    print(f"导入完成: {count} 条, 错误: {errors} 条")
    return count


def import_bgp_dump(file_path: str, db_path: str = "ip_locations.db"):
    """
    导入 BGP 路由表 (MRT 格式需要额外库，这里 placeholder)
    实际实现需要安装: pip install mrtparse
    """
    print("BGP MRT 导入需要安装 mrtparse 库")
    print("pip install mrtparse")
    print("然后实现解析逻辑")


def query_asn(ip: str, db_path: str = "ip_locations.db"):
    """查询 IP 的 ASN"""
    import ipaddress
    
    ip_int = int(ipaddress.ip_address(ip))
    
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    
    cursor.execute('''
        SELECT asn, source FROM raw_l2_asn_mapping
        WHERE ip_start <= ? AND ip_end >= ?
        LIMIT 1
    ''', (ip_int, ip_int))
    
    row = cursor.fetchone()
    conn.close()
    
    if row:
        print(f"{ip} -> ASN {row[0]} (来源: {row[1]})")
        return row[0]
    else:
        print(f"{ip} -> ASN 未找到")
        return None


def download_caida_latest(output_dir: str = "."):
    """
    下载最新的 CAIDA pfx2as 文件
    需要 CAIDA 账号
    """
    import urllib.request
    from datetime import datetime
    
    # 构建最新日期 URL
    now = datetime.now()
    year = now.year
    month = now.month
    
    # CAIDA 数据 URL 格式
    base_url = f"https://publicdata.caida.org/datasets/routing/routeviews-prefix2as/{year}/{month:02d}/"
    
    print(f"尝试下载最新数据从: {base_url}")
    print("注意: 需要 CAIDA 账号才能下载")
    print("请手动下载后使用 import 命令导入")
    
    return None


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='L2 ASN 数据导入')
    parser.add_argument('command', choices=['import', 'query', 'download'], 
                        help='命令: import(导入文件), query(查询ASN), download(下载最新)')
    parser.add_argument('file_or_ip', nargs='?', help='文件路径或IP地址')
    parser.add_argument('--db', default='ip_locations.db', help='数据库路径')
    parser.add_argument('--source', default='caida', choices=['caida', 'bgp'], 
                        help='数据来源类型')
    parser.add_argument('--batch-size', type=int, default=5000, help='批量插入大小')
    
    args = parser.parse_args()
    
    if args.command == 'import':
        if not args.file_or_ip:
            print("错误: 请指定文件路径")
            sys.exit(1)
        
        if args.source == 'caida':
            import_caida_pfx2as(args.file_or_ip, args.db, args.batch_size)
        elif args.source == 'bgp':
            import_bgp_dump(args.file_or_ip, args.db)
    
    elif args.command == 'query':
        if not args.file_or_ip:
            print("错误: 请指定IP地址")
            sys.exit(1)
        query_asn(args.file_or_ip, args.db)
    
    elif args.command == 'download':
        download_caida_latest()
