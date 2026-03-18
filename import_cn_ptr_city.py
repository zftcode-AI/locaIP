#!/usr/bin/env python3
"""
国内运营商 PTR 城市推断
通过反向 DNS 域名模式识别城市
"""

import ipaddress
import re
import sqlite3
import sys
import subprocess
from pathlib import Path
from collections import defaultdict


# 国内运营商 PTR 域名模式 -> 城市映射
# 格式: (正则模式, 省份代码, 城市名称)
CN_PTR_CITY_PATTERNS = [
    # 中国电信 (CT)
    # 广东电信
    (r'.*\.gd\.ctm\.net', 'GD', 'Guangzhou'),
    (r'.*\.gddtelecom\.cn', 'GD', 'Guangzhou'),
    (r'.*\.sztelecom\.cn', 'GD', 'Shenzhen'),
    (r'.*\.sz\.ctm\.net', 'GD', 'Shenzhen'),
    (r'.*\.dgtelecom\.cn', 'GD', 'Dongguan'),
    (r'.*\.fs\.ctm\.net', 'GD', 'Foshan'),
    (r'.*\.zh\.ctm\.net', 'GD', 'Zhuhai'),
    (r'.*\.st\.ctm\.net', 'GD', 'Shantou'),
    (r'.*\.zj\.ctm\.net', 'GD', 'Zhanjiang'),
    
    # 北京电信
    (r'.*\.bj\.ctm\.net', 'BJ', 'Beijing'),
    (r'.*\.bjtelecom\.cn', 'BJ', 'Beijing'),
    
    # 上海电信
    (r'.*\.sh\.ctm\.net', 'SH', 'Shanghai'),
    (r'.*\.shtelecom\.cn', 'SH', 'Shanghai'),
    
    # 江苏电信
    (r'.*\.js\.ctm\.net', 'JS', 'Nanjing'),
    (r'.*\.njtelecom\.cn', 'JS', 'Nanjing'),
    (r'.*\.sz\.js\.ctm\.net', 'JS', 'Suzhou'),
    (r'.*\.wx\.js\.ctm\.net', 'JS', 'Wuxi'),
    
    # 浙江电信
    (r'.*\.zj\.ctm\.net', 'ZJ', 'Hangzhou'),
    (r'.*\.hztelecom\.cn', 'ZJ', 'Hangzhou'),
    (r'.*\.nb\.zj\.ctm\.net', 'ZJ', 'Ningbo'),
    (r'.*\.wz\.zj\.ctm\.net', 'ZJ', 'Wenzhou'),
    
    # 福建电信
    (r'.*\.fj\.ctm\.net', 'FJ', 'Fuzhou'),
    (r'.*\.xm\.fj\.ctm\.net', 'FJ', 'Xiamen'),
    
    # 山东电信
    (r'.*\.sd\.ctm\.net', 'SD', 'Jinan'),
    (r'.*\.qd\.sd\.ctm\.net', 'SD', 'Qingdao'),
    
    # 河南电信
    (r'.*\.ha\.ctm\.net', 'HEN', 'Zhengzhou'),
    
    # 湖北电信
    (r'.*\.hb\.ctm\.net', 'HB', 'Wuhan'),
    (r'.*\.whtelecom\.cn', 'HB', 'Wuhan'),
    
    # 湖南电信
    (r'.*\.hn\.ctm\.net', 'HN', 'Changsha'),
    
    # 四川电信
    (r'.*\.sc\.ctm\.net', 'SC', 'Chengdu'),
    (r'.*\.cdtelecom\.cn', 'SC', 'Chengdu'),
    
    # 重庆电信
    (r'.*\.cq\.ctm\.net', 'CQ', 'Chongqing'),
    
    # 陕西电信
    (r'.*\.sn\.ctm\.net', 'SN', 'Xi\'an'),
    (r'.*\.xatelecom\.cn', 'SN', 'Xi\'an'),
    
    # 辽宁电信
    (r'.*\.ln\.ctm\.net', 'LN', 'Shenyang'),
    (r'.*\.sy\.ln\.ctm\.net', 'LN', 'Shenyang'),
    (r'.*\.dl\.ln\.ctm\.net', 'LN', 'Dalian'),
    
    # 中国联通 (CU)
    (r'.*\.bjunicom\.cn', 'BJ', 'Beijing'),
    (r'.*\.shunicom\.cn', 'SH', 'Shanghai'),
    (r'.*\.gdunicom\.cn', 'GD', 'Guangzhou'),
    (r'.*\.jsunicom\.cn', 'JS', 'Nanjing'),
    (r'.*\.sdunicom\.cn', 'SD', 'Jinan'),
    (r'.*\.lnunicom\.cn', 'LN', 'Shenyang'),
    (r'.*\.hbunicom\.cn', 'HB', 'Wuhan'),
    (r'.*\.scunicom\.cn', 'SC', 'Chengdu'),
    (r'.*\.zjunicom\.cn', 'ZJ', 'Hangzhou'),
    (r'.*\.fjunicom\.cn', 'FJ', 'Fuzhou'),
    
    # 中国移动 (CM)
    (r'.*\.bj\.cmcc\.cn', 'BJ', 'Beijing'),
    (r'.*\.sh\.cmcc\.cn', 'SH', 'Shanghai'),
    (r'.*\.gd\.cmcc\.cn', 'GD', 'Guangzhou'),
    (r'.*\.js\.cmcc\.cn', 'JS', 'Nanjing'),
    (r'.*\.sd\.cmcc\.cn', 'SD', 'Jinan'),
    (r'.*\.zj\.cmcc\.cn', 'ZJ', 'Hangzhou'),
    (r'.*\.hb\.cmcc\.cn', 'HB', 'Wuhan'),
    (r'.*\.sc\.cmcc\.cn', 'SC', 'Chengdu'),
    
    # 铁通
    (r'.*\.bj\.railcom\.cn', 'BJ', 'Beijing'),
    (r'.*\.sh\.railcom\.cn', 'SH', 'Shanghai'),
    (r'.*\.gd\.railcom\.cn', 'GD', 'Guangzhou'),
    
    # 广电
    (r'.*\.bj\.catv\.cn', 'BJ', 'Beijing'),
    (r'.*\.sh\.catv\.cn', 'SH', 'Shanghai'),
    (r'.*\.gd\.catv\.cn', 'GD', 'Guangzhou'),
]


def parse_ptr_city(ptr: str) -> tuple:
    """
    解析 PTR 记录，推断国内城市
    返回: (country, province, city, confidence)
    """
    ptr_lower = ptr.lower()
    
    for pattern, province, city in CN_PTR_CITY_PATTERNS:
        if re.match(pattern, ptr_lower):
            return 'CN', province, city, 4  # 高置信度
    
    # 通用中国运营商检测
    if any(x in ptr_lower for x in ['.ctm.net', 'telecom.cn', 'unicom.cn', 'cmcc.cn', 'railcom.cn']):
        return 'CN', '', '', 2  # 仅确认是中国
    
    return '', '', '', 0


def dig_ptr(ip: str) -> str:
    """使用 dig 查询 PTR"""
    try:
        result = subprocess.run(
            ['dig', '+short', '-x', ip, '@114.114.114.114'],
            capture_output=True, text=True, timeout=5
        )
        ptr = result.stdout.strip().rstrip('.')
        return ptr if ptr else None
    except Exception:
        return None


def update_cn_city_by_ptr(db_path: str = "ip_locations.db", sample_ips: list = None):
    """
    通过 PTR 更新国内 IP 的城市信息
    :param sample_ips: 要测试的 IP 列表，为 None 则查询数据库中的中国 IP
    """
    print("通过 PTR 推断国内 IP 城市...")
    
    conn = sqlite3.connect(db_path, timeout=60)
    cursor = conn.cursor()
    
    # 获取需要更新的中国 IP 段（没有城市信息的）
    if sample_ips:
        ip_ranges = []
        for ip in sample_ips:
            try:
                ip_int = int(ipaddress.ip_address(ip))
                cursor.execute('''
                    SELECT ip_start, ip_end FROM raw_l1_authoritative
                    WHERE ip_start <= ? AND ip_end >= ? AND country = 'CN'
                ''', (ip_int, ip_int))
                row = cursor.fetchone()
                if row:
                    ip_ranges.append(row)
            except:
                continue
    else:
        cursor.execute('''
            SELECT DISTINCT ip_start, ip_end FROM raw_l1_authoritative
            WHERE country = 'CN' AND (city IS NULL OR city = '')
            LIMIT 100
        ''')
        ip_ranges = cursor.fetchall()
    
    print(f"需要检测的 IP 段: {len(ip_ranges)}")
    
    updated = 0
    for ip_start, ip_end in ip_ranges:
        # 取段内一个 IP 进行 PTR 查询
        test_ip = str(ipaddress.ip_address(ip_start + 1))
        
        ptr = dig_ptr(test_ip)
        if not ptr:
            continue
        
        country, province, city, confidence = parse_ptr_city(ptr)
        
        if city:  # 成功推断城市
            cursor.execute('''
                UPDATE raw_l1_authoritative
                SET city = ?, region = ?, raw_data = json_patch(raw_data, ?)
                WHERE ip_start = ? AND ip_end = ?
            ''', (city, province, 
                  json.dumps({'ptr': ptr, 'ptr_confidence': confidence}),
                  ip_start, ip_end))
            updated += 1
            print(f"  {test_ip}: {ptr} -> {city} ({confidence})")
        
        if updated >= 50:  # 限制更新数量
            break
    
    conn.commit()
    conn.close()
    
    print(f"更新完成: {updated} 条")
    return updated


def query_ip_with_ptr(ip: str, db_path: str = "ip_locations.db"):
    """查询 IP 并显示 PTR 信息"""
    try:
        ip_int = int(ipaddress.ip_address(ip))
    except:
        print(f"无效 IP: {ip}")
        return
    
    # 查数据库
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    
    cursor.execute('''
        SELECT source, country, city, raw_data FROM raw_l1_authoritative
        WHERE ip_start <= ? AND ip_end >= ?
        LIMIT 1
    ''', (ip_int, ip_int))
    
    row = cursor.fetchone()
    conn.close()
    
    # PTR 查询
    ptr = dig_ptr(ip)
    ptr_country, ptr_province, ptr_city, ptr_confidence = parse_ptr_city(ptr) if ptr else ('', '', '', 0)
    
    print(f"{ip}:")
    
    if row:
        print(f"  数据库: {row[0]} | {row[1]}, {row[2] if row[2] else '未知城市'}")
    else:
        print(f"  数据库: 未找到")
    
    if ptr:
        print(f"  PTR: {ptr}")
        if ptr_city:
            print(f"  PTR推断: CN, {ptr_province}, {ptr_city} (置信度{ptr_confidence})")
        elif ptr_country:
            print(f"  PTR推断: {ptr_country} (运营商识别)")
    else:
        print(f"  PTR: 查询失败")


if __name__ == '__main__':
    import json
    
    if len(sys.argv) < 2:
        print("用法:")
        print(f"  {sys.argv[0]} query IP       - 查询 IP（含PTR）")
        print(f"  {sys.argv[0]} update         - 更新数据库中的中国IP城市")
        print(f"  {sys.argv[0]} test IP1 IP2   - 测试多个IP")
        sys.exit(1)
    
    command = sys.argv[1]
    
    if command == 'query':
        if len(sys.argv) < 3:
            print("请指定 IP")
            sys.exit(1)
        query_ip_with_ptr(sys.argv[2])
    
    elif command == 'update':
        update_cn_city_by_ptr()
    
    elif command == 'test':
        for ip in sys.argv[2:]:
            query_ip_with_ptr(ip)
            print()
    
    else:
        print("未知命令")
        sys.exit(1)
