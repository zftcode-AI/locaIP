#!/usr/bin/env python3
"""
L4 层 PTR (反向DNS) 数据导入
用于补充 L1-L3 查不到的 IP
"""

import gzip
import json
import re
import sqlite3
import sys
from pathlib import Path
from collections import defaultdict


# 域名模式 -> 位置的映射规则
PTR_PATTERNS = {
    # 中国电信
    r'.*\.bjtelecom\.cn': ('CN', 'Beijing'),
    r'.*\.shtelecom\.cn': ('CN', 'Shanghai'),
    r'.*\.gddtelecom\.cn': ('CN', 'Guangzhou'),
    r'.*\.ctm\.net': ('CN', ''),  # 中国电信通用
    
    # 中国联通
    r'.*\.unicom\.cn': ('CN', ''),
    r'.*\.bjunicom\.cn': ('CN', 'Beijing'),
    r'.*\.shunicom\.cn': ('CN', 'Shanghai'),
    
    # 中国移动
    r'.*\.cmcc\.cn': ('CN', ''),
    r'.*\.chinamobile\.com': ('CN', ''),
    
    # 美国主要运营商
    r'.*\.comcast\.net': ('US', ''),
    r'.*\.verizon\.net': ('US', ''),
    r'.*\.att\.net': ('US', ''),
    r'.*\.charter\.com': ('US', ''),
    
    # 欧洲
    r'.*\.bt\.net': ('GB', ''),  # 英国电信
    r'.*\.deutschetelekom\.': ('DE', ''),
    r'.*\.orange\.fr': ('FR', ''),
    
    # 云厂商
    r'.*\.amazonaws\.com': ('', ''),  # AWS - 已有 L1
    r'.*\.googleusercontent\.com': ('', ''),  # GCP - 已有 L1
    r'.*\.cloudflare\.': ('', ''),  # Cloudflare - 已有 L3
    
    # 日本
    r'.*\.jpne\.co\.jp': ('JP', ''),
    r'.*\.ocn\.ne\.jp': ('JP', ''),
    
    # 韩国
    r'.*\.kt\.com': ('KR', ''),
    r'.*\.sktelecom\.com': ('KR', ''),
}


def parse_ptr_record(ptr: str) -> tuple:
    """
    解析 PTR 记录，推断位置
    返回: (country, city, confidence, pattern)
    """
    ptr_lower = ptr.lower()
    
    for pattern, (country, city) in PTR_PATTERNS.items():
        if re.match(pattern, ptr_lower):
            confidence = 2 if city else 1
            return country, city, confidence, pattern
    
    # 尝试从域名后缀推断国家
    tld_country_map = {
        '.cn': 'CN',
        '.jp': 'JP',
        '.kr': 'KR',
        '.uk': 'GB',
        '.de': 'DE',
        '.fr': 'FR',
        '.au': 'AU',
        '.br': 'BR',
        '.in': 'IN',
        '.ru': 'RU',
    }
    
    for tld, country in tld_country_map.items():
        if ptr_lower.endswith(tld):
            return country, '', 1, f'TLD:{tld}'
    
    return '', '', 0, ''


def import_sonar_rdns(gz_path: str, db_path: str = "ip_locations.db", sample_rate: float = 1.0):
    """
    导入 Sonar RDNS 数据
    :param gz_path: Sonar rdns.gz 文件路径
    :param sample_rate: 采样率 (1.0=全部, 0.1=10%)
    """
    print(f"导入 Sonar RDNS: {gz_path}")
    print(f"采样率: {sample_rate*100}%")
    
    conn = sqlite3.connect(db_path, timeout=60)
    cursor = conn.cursor()
    
    # 清空旧 L4 数据
    cursor.execute('DELETE FROM raw_l4_ptr')
    conn.commit()
    
    count = 0
    matched = 0
    errors = 0
    
    with gzip.open(gz_path, 'rt', encoding='utf-8', errors='ignore') as f:
        for line_num, line in enumerate(f, 1):
            # 采样
            if sample_rate < 1.0 and hash(line) % 100 > int(sample_rate * 100):
                continue
            
            try:
                # Sonar 格式: {"timestamp":"...","name":"ptr_record","type":"ptr","value":"ip"}
                data = json.loads(line)
                ptr = data.get('name', '').strip()
                ip = data.get('value', '').strip()
                
                if not ptr or not ip:
                    continue
                
                # 解析 PTR 推断位置
                country, city, confidence, pattern = parse_ptr_record(ptr)
                
                if confidence > 0:
                    # 转换 IP 为整数
                    import ipaddress
                    ip_int = int(ipaddress.ip_address(ip))
                    
                    cursor.execute('''
                        INSERT OR REPLACE INTO raw_l4_ptr 
                        (ip, ptr_record, domain_pattern, inferred_country, inferred_city, confidence)
                        VALUES (?, ?, ?, ?, ?, ?)
                    ''', (ip_int, ptr, pattern, country, city, confidence))
                    
                    matched += 1
                
                count += 1
                
                if count % 100000 == 0:
                    conn.commit()
                    print(f"  处理 {count}, 匹配 {matched}...")
                    
            except Exception as e:
                errors += 1
                if errors <= 3:
                    print(f"  错误 行{line_num}: {e}")
                continue
    
    conn.commit()
    conn.close()
    
    print(f"导入完成: 处理 {count}, 匹配 {matched}, 错误 {errors}")
    return matched


def query_ptr(ip: str, db_path: str = "ip_locations.db"):
    """查询 IP 的 PTR 信息"""
    import ipaddress
    
    ip_int = int(ipaddress.ip_address(ip))
    
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


def dig_ptr(ip: str):
    """使用系统 dig 命令查询 PTR（需要安装 bind-utils）"""
    import subprocess
    
    try:
        result = subprocess.run(['dig', '+short', '-x', ip], 
                                capture_output=True, text=True, timeout=5)
        ptr = result.stdout.strip()
        if ptr:
            print(f"{ip} -> {ptr}")
            country, city, confidence, pattern = parse_ptr_record(ptr)
            if confidence > 0:
                print(f"  推断: {country}, {city} (置信度: {confidence})")
            return ptr
    except Exception as e:
        print(f"查询失败: {e}")
    
    return None


if __name__ == '__main__':
    if len(sys.argv) < 2:
        print("用法:")
        print(f"  导入: python {sys.argv[0]} import sonar.rdns.json.gz [采样率]")
        print(f"  查询: python {sys.argv[0]} query IP")
        print(f"  dig:  python {sys.argv[0]} dig IP")
        sys.exit(1)
    
    command = sys.argv[1]
    
    if command == 'import':
        if len(sys.argv) < 3:
            print("请指定文件路径")
            sys.exit(1)
        gz_file = sys.argv[2]
        sample = float(sys.argv[3]) if len(sys.argv) > 3 else 1.0
        import_sonar_rdns(gz_file, sample_rate=sample)
    
    elif command == 'query':
        if len(sys.argv) < 3:
            print("请指定 IP")
            sys.exit(1)
        query_ptr(sys.argv[2])
    
    elif command == 'dig':
        if len(sys.argv) < 3:
            print("请指定 IP")
            sys.exit(1)
        dig_ptr(sys.argv[2])
    
    else:
        print("未知命令")
        sys.exit(1)
