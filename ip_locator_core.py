"""
IP 定位系统核心模块
支持四层数据源融合、区间树索引、SQLite存储
"""

import sqlite3
import ipaddress
import json
from typing import Optional, List, Dict, Tuple, NamedTuple
from dataclasses import dataclass
from enum import IntEnum
import bisect


class DataSource(IntEnum):
    """数据源层级"""
    UNKNOWN = 0
    L4_PTR = 1          # Project Sonar PTR
    L3_ASN_INFO = 2     # PeeringDB/IXP
    L2_ASN_MAPPING = 3  # CAIDA/BGP (仅作为中间层)
    L1_AUTHORITATIVE = 4  # Geofeed/云厂商


@dataclass
class IPLocation:
    """IP位置记录"""
    ip_start: int
    ip_end: int
    country: str
    city: str
    region: str = ""
    latitude: Optional[float] = None
    longitude: Optional[float] = None
    asn: Optional[int] = None
    source: DataSource = DataSource.UNKNOWN
    source_detail: str = ""  # 具体来源，如 'aws', 'geofeed', 'peeringdb'
    confidence: int = 0      # 1-5
    raw_data: str = ""       # 原始数据JSON

    @property
    def ip_prefix(self) -> str:
        """返回IP前缀表示"""
        start_ip = ipaddress.ip_address(self.ip_start)
        # 计算掩码长度
        range_size = self.ip_end - self.ip_start + 1
        prefix_len = 32 - (range_size - 1).bit_length()
        return f"{start_ip}/{prefix_len}"


class IPConverter:
    """IP地址转换工具"""
    
    @staticmethod
    def ip_to_int(ip_str: str) -> int:
        """IP字符串转整数"""
        return int(ipaddress.ip_address(ip_str.strip()))
    
    @staticmethod
    def int_to_ip(ip_int: int) -> str:
        """整数转IP字符串"""
        return str(ipaddress.ip_address(ip_int))
    
    @staticmethod
    def prefix_to_range(prefix: str) -> Tuple[int, int]:
        """IP前缀转整数范围 (start, end)"""
        network = ipaddress.ip_network(prefix.strip(), strict=False)
        return (
            int(network.network_address),
            int(network.broadcast_address)
        )
    
    @staticmethod
    def range_to_prefixes(ip_start: int, ip_end: int) -> List[str]:
        """整数范围转最小区间前缀列表"""
        prefixes = []
        current = ip_start
        
        while current <= ip_end:
            # 计算当前位置可以使用的最大掩码
            # 找到最低位的1
            lowest_bit = current & -current
            # 计算剩余范围
            remaining = ip_end - current + 1
            # 取两者较小值
            max_size = min(lowest_bit, 1 << (remaining.bit_length() - 1))
            # 计算前缀长度
            prefix_len = 32 - (max_size.bit_length() - 1)
            
            prefixes.append(f"{ipaddress.ip_address(current)}/{prefix_len}")
            current += max_size
        
        return prefixes


class IntervalTree:
    """区间树 - 用于高效查询IP段"""
    
    def __init__(self):
        self.intervals: List[Tuple[int, int, IPLocation]] = []
        self.sorted = False
    
    def add(self, location: IPLocation):
        """添加区间"""
        self.intervals.append((location.ip_start, location.ip_end, location))
        self.sorted = False
    
    def build(self):
        """构建索引（排序）"""
        # 按起始IP排序
        self.intervals.sort(key=lambda x: x[0])
        self.sorted = True
    
    def query(self, ip_int: int) -> Optional[IPLocation]:
        """查询IP所在区间（返回优先级最高的）"""
        if not self.sorted:
            self.build()
        
        # 二分查找可能的区间
        # 找到起始位置 <= ip_int 的最后一个区间
        idx = bisect.bisect_right(self.intervals, (ip_int, float('inf'), None)) - 1
        
        if idx < 0:
            return None
        
        # 检查这个区间是否包含该IP
        start, end, loc = self.intervals[idx]
        if start <= ip_int <= end:
            return loc
        
        # 可能有多个区间包含，向前检查（处理重叠）
        best_result = None
        for i in range(idx, -1, -1):
            start, end, loc = self.intervals[i]
            if end < ip_int:
                break
            if start <= ip_int <= end:
                # 返回优先级最高的
                if best_result is None or loc.source > best_result.source:
                    best_result = loc
        
        return best_result
    
    def query_all(self, ip_int: int) -> List[IPLocation]:
        """查询IP所在的所有区间"""
        if not self.sorted:
            self.build()
        
        results = []
        # 近似定位
        idx = bisect.bisect_right(self.intervals, (ip_int, float('inf'), None))
        
        # 检查前后可能的区间
        for i in range(max(0, idx - 10), min(len(self.intervals), idx + 10)):
            start, end, loc = self.intervals[i]
            if start <= ip_int <= end:
                results.append(loc)
        
        # 按优先级排序
        results.sort(key=lambda x: x.source, reverse=True)
        return results


class IPLocationDatabase:
    """IP定位数据库 - SQLite存储"""
    
    def __init__(self, db_path: str = "ip_locations.db"):
        self.db_path = db_path
        self.conn = sqlite3.connect(db_path)
        self.conn.row_factory = sqlite3.Row
        self._init_tables()
        self.interval_tree = IntervalTree()
        self._loaded = False
    
    def _init_tables(self):
        """初始化数据库表"""
        cursor = self.conn.cursor()
        
        # 各层原始数据表
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS raw_l1_authoritative (
                ip_start INTEGER,
                ip_end INTEGER,
                source TEXT,           -- 'geofeed', 'aws', 'aliyun', 'tencent', 'gcp'
                country TEXT,
                region TEXT,
                city TEXT,
                latitude REAL,
                longitude REAL,
                raw_data TEXT,
                imported_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY (ip_start, ip_end, source)
            )
        ''')
        
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS raw_l2_asn_mapping (
                ip_start INTEGER,
                ip_end INTEGER,
                asn INTEGER,
                source TEXT,           -- 'caida', 'bgp', 'whois'
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY (ip_start, ip_end)
            )
        ''')
        
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS raw_l3_asn_info (
                asn INTEGER PRIMARY KEY,
                org_name TEXT,
                country TEXT,
                city TEXT,
                latitude REAL,
                longitude REAL,
                facilities TEXT,       -- JSON: [{"city": "北京", "lat": x, "lon": y}]
                source TEXT,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS raw_l4_ptr (
                ip INTEGER PRIMARY KEY,
                ptr_record TEXT,
                domain_pattern TEXT,
                inferred_country TEXT,
                inferred_city TEXT,
                confidence INTEGER
            )
        ''')
        
        # 融合后的最终表
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS merged_ip_locations (
                ip_start INTEGER,
                ip_end INTEGER,
                -- L1 原始
                l1_source TEXT,
                l1_country TEXT,
                l1_city TEXT,
                l1_lat REAL,
                l1_lon REAL,
                -- L2
                l2_asn INTEGER,
                l2_source TEXT,
                -- L3 原始
                l3_country TEXT,
                l3_city TEXT,
                l3_lat REAL,
                l3_lon REAL,
                -- L4 原始
                l4_ptr TEXT,
                l4_country TEXT,
                l4_city TEXT,
                -- 最终结果
                final_country TEXT,
                final_city TEXT,
                final_lat REAL,
                final_lon REAL,
                final_source TEXT,     -- 'L1', 'L3', 'L4', 'unknown'
                confidence INTEGER,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY (ip_start, ip_end)
            )
        ''')
        
        # 创建索引
        cursor.execute('CREATE INDEX IF NOT EXISTS idx_l1_ip ON raw_l1_authoritative(ip_start, ip_end)')
        cursor.execute('CREATE INDEX IF NOT EXISTS idx_l2_ip ON raw_l2_asn_mapping(ip_start, ip_end)')
        cursor.execute('CREATE INDEX IF NOT EXISTS idx_l2_asn ON raw_l2_asn_mapping(asn)')
        cursor.execute('CREATE INDEX IF NOT EXISTS idx_l3_asn ON raw_l3_asn_info(asn)')
        cursor.execute('CREATE INDEX IF NOT EXISTS idx_l4_ip ON raw_l4_ptr(ip)')
        cursor.execute('CREATE INDEX IF NOT EXISTS idx_merged_ip ON merged_ip_locations(ip_start, ip_end)')
        
        self.conn.commit()
    
    # ==================== L1 导入 ====================
    
    def import_geofeed(self, csv_path: str, batch_size: int = 1000):
        """导入 Geofeed CSV"""
        import csv
        
        cursor = self.conn.cursor()
        batch = []
        count = 0
        error_count = 0
        
        # 尝试多种编码
        encodings = ['utf-8', 'gbk', 'gb2312', 'utf-8-sig', 'latin-1', 'cp1252']
        f = None
        used_encoding = None
        
        for encoding in encodings:
            try:
                f = open(csv_path, 'r', encoding=encoding)
                # 尝试读取前几行验证
                sample = f.read(4096)
                f.seek(0)
                # 检查是否包含乱码特征
                if '\x00' in sample or (encoding == 'latin-1' and '�' in sample):
                    f.close()
                    continue
                used_encoding = encoding
                print(f"使用编码: {encoding}")
                break
            except UnicodeDecodeError:
                if f:
                    f.close()
                continue
        
        if not f or not used_encoding:
            raise ValueError("无法识别文件编码，请手动指定")
        
        # 先读取表头看看
        first_line = f.readline().strip()
        f.seek(0)
        print(f"CSV表头: {first_line[:100]}")
        
        try:
            # 检测分隔符：尝试读取第一行数据
            sample_line = f.readline()
            f.seek(0)
            
            delimiter = ','
            if '\t' in sample_line:
                delimiter = '\t'
                print("检测到制表符分隔")
            
            # 如果没有表头，使用默认字段名
            has_header = 'ip_prefix' in sample_line.lower() or '192.' in sample_line or '213.' in sample_line
            
            if has_header and 'ip_prefix' in sample_line.lower():
                # 有标准表头
                reader = csv.DictReader(f, delimiter=delimiter)
            else:
                # 无表头，指定字段名
                print("无表头，使用默认字段名")
                fieldnames = ['ip_prefix', 'country_code', 'region_code', 'city']
                reader = csv.DictReader(f, delimiter=delimiter, fieldnames=fieldnames)
            
            # 打印实际解析的字段名
            fieldnames = reader.fieldnames
            print(f"解析的字段: {fieldnames}")
            
            for row in reader:
                prefix = row.get('ip_prefix', '').strip()
                if not prefix or prefix.startswith('#') or not prefix[0].isdigit():
                    continue
                
                try:
                    ip_start, ip_end = IPConverter.prefix_to_range(prefix)
                    batch.append((
                        ip_start, ip_end, 'geofeed',
                        row.get('country_code', '').strip(),
                        row.get('region_code', '').strip(),
                        row.get('city', '').strip(),
                        None, None,
                        json.dumps(row)
                    ))
                    
                    if len(batch) >= batch_size:
                        cursor.executemany('''
                            INSERT OR REPLACE INTO raw_l1_authoritative 
                            (ip_start, ip_end, source, country, region, city, latitude, longitude, raw_data)
                            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                        ''', batch)
                        count += len(batch)
                        batch = []
                        
                except Exception as e:
                    error_count += 1
                    if error_count <= 3:
                        print(f"解析错误: {e}, prefix={prefix}")
                    continue
            
            if batch:
                cursor.executemany('''
                    INSERT OR REPLACE INTO raw_l1_authoritative 
                    (ip_start, ip_end, source, country, region, city, latitude, longitude, raw_data)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                ''', batch)
                count += len(batch)
        finally:
            f.close()
        
        self.conn.commit()
        print(f"Geofeed 导入完成: {count} 条, 错误: {error_count} 条")
        return count
    
    def import_aws_ip_ranges(self, json_path: str):
        """导入 AWS IP Ranges JSON"""
        with open(json_path, 'r') as f:
            data = json.load(f)
        
        cursor = self.conn.cursor()
        count = 0
        
        # 区域代码到位置的映射（简化版，实际需要完整映射表）
        region_mapping = {
            'ap-northeast-1': ('JP', 'Tokyo'),
            'ap-northeast-2': ('KR', 'Seoul'),
            'ap-southeast-1': ('SG', 'Singapore'),
            'ap-southeast-2': ('AU', 'Sydney'),
            'ap-south-1': ('IN', 'Mumbai'),
            'eu-west-1': ('IE', 'Dublin'),
            'eu-west-2': ('GB', 'London'),
            'eu-west-3': ('FR', 'Paris'),
            'eu-central-1': ('DE', 'Frankfurt'),
            'us-east-1': ('US', 'N. Virginia'),
            'us-east-2': ('US', 'Ohio'),
            'us-west-1': ('US', 'N. California'),
            'us-west-2': ('US', 'Oregon'),
            'cn-north-1': ('CN', 'Beijing'),
            'cn-northwest-1': ('CN', 'Ningxia'),
        }
        
        for prefix in data.get('prefixes', []):
            try:
                ip_prefix = prefix['ip_prefix']
                region = prefix.get('region', '')
                ip_start, ip_end = IPConverter.prefix_to_range(ip_prefix)
                
                country, city = region_mapping.get(region, ('', region))
                
                cursor.execute('''
                    INSERT OR REPLACE INTO raw_l1_authoritative 
                    (ip_start, ip_end, source, country, region, city, latitude, longitude, raw_data)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                ''', (ip_start, ip_end, 'aws', country, region, city, None, None, json.dumps(prefix)))
                count += 1
                
            except Exception:
                continue
        
        self.conn.commit()
        print(f"AWS 导入完成: {count} 条")
        return count
    
    # ==================== L2 导入 ====================
    
    def import_caida_pfx2as(self, file_path: str):
        """导入 CAIDA pfx2as 文件"""
        import gzip
        
        cursor = self.conn.cursor()
        opener = gzip.open if file_path.endswith('.gz') else open
        
        count = 0
        batch = []
        
        with opener(file_path, 'rt') as f:
            for line in f:
                parts = line.strip().split('\t')
                if len(parts) >= 3:
                    try:
                        ip_start = int(parts[0])
                        prefix_len = int(parts[1])
                        asn = int(parts[2])
                        
                        # 计算结束IP
                        ip_end = ip_start + (1 << (32 - prefix_len)) - 1
                        
                        batch.append((ip_start, ip_end, asn, 'caida'))
                        
                        if len(batch) >= 5000:
                            cursor.executemany('''
                                INSERT OR REPLACE INTO raw_l2_asn_mapping 
                                (ip_start, ip_end, asn, source)
                                VALUES (?, ?, ?, ?)
                            ''', batch)
                            count += len(batch)
                            batch = []
                            
                    except (ValueError, IndexError):
                        continue
        
        if batch:
            cursor.executemany('''
                INSERT OR REPLACE INTO raw_l2_asn_mapping 
                (ip_start, ip_end, asn, source)
                VALUES (?, ?, ?, ?)
            ''', batch)
            count += len(batch)
        
        self.conn.commit()
        print(f"CAIDA pfx2as 导入完成: {count} 条")
        return count
    
    # ==================== L3 导入 ====================
    
    def import_peeringdb_facilities(self, json_data: List[Dict]):
        """导入 PeeringDB 设施数据"""
        cursor = self.conn.cursor()
        
        for fac in json_data:
            asn = fac.get('asn')
            if not asn:
                continue
            
            facilities = json.dumps([{
                'city': fac.get('city', ''),
                'country': fac.get('country', ''),
                'lat': fac.get('latitude'),
                'lon': fac.get('longitude')
            }])
            
            cursor.execute('''
                INSERT OR REPLACE INTO raw_l3_asn_info 
                (asn, org_name, country, city, latitude, longitude, facilities, source)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ''', (
                asn,
                fac.get('name', ''),
                fac.get('country', ''),
                fac.get('city', ''),
                fac.get('latitude'),
                fac.get('longitude'),
                facilities,
                'peeringdb'
            ))
        
        self.conn.commit()
        print(f"PeeringDB 导入完成: {len(json_data)} 条")
    
    # ==================== 融合逻辑 ====================
    
    def merge_all(self):
        """执行四层融合"""
        cursor = self.conn.cursor()
        
        # 清空旧结果
        cursor.execute('DELETE FROM merged_ip_locations')
        
        # 获取所有需要处理的IP段（L1 + L2有ASN的 + L4有PTR的）
        cursor.execute('''
            SELECT DISTINCT ip_start, ip_end FROM (
                SELECT ip_start, ip_end FROM raw_l1_authoritative
                UNION
                SELECT ip_start, ip_end FROM raw_l2_asn_mapping
                UNION
                SELECT ip, ip FROM raw_l4_ptr
            )
            ORDER BY ip_start
        ''')
        
        all_ranges = cursor.fetchall()
        print(f"待融合区间数: {len(all_ranges)}")
        
        merged_count = 0
        batch = []
        
        for row in all_ranges:
            ip_start, ip_end = row['ip_start'], row['ip_end']
            result = self._merge_single_range(ip_start, ip_end)
            
            if result:
                batch.append(result)
                
                if len(batch) >= 1000:
                    self._insert_merged_batch(batch)
                    merged_count += len(batch)
                    batch = []
                    if merged_count % 10000 == 0:
                        print(f"已融合 {merged_count} 条...")
        
        if batch:
            self._insert_merged_batch(batch)
            merged_count += len(batch)
        
        self.conn.commit()
        print(f"融合完成: {merged_count} 条")
        return merged_count
    
    def _merge_single_range(self, ip_start: int, ip_end: int) -> Optional[Tuple]:
        """融合单个IP段"""
        cursor = self.conn.cursor()
        
        # 尝试 L1
        cursor.execute('''
            SELECT source, country, city, region, latitude, longitude
            FROM raw_l1_authoritative
            WHERE ip_start <= ? AND ip_end >= ?
            ORDER BY 
                CASE source WHEN 'geofeed' THEN 1 ELSE 2 END,
                imported_at DESC
            LIMIT 1
        ''', (ip_start, ip_end))
        
        l1 = cursor.fetchone()
        
        # 尝试 L2 + L3
        l2_asn = None
        l3 = None
        
        cursor.execute('''
            SELECT asn, source FROM raw_l2_asn_mapping
            WHERE ip_start <= ? AND ip_end >= ?
            LIMIT 1
        ''', (ip_start, ip_end))
        
        l2 = cursor.fetchone()
        if l2:
            l2_asn = l2['asn']
            cursor.execute('''
                SELECT country, city, latitude, longitude
                FROM raw_l3_asn_info
                WHERE asn = ?
                LIMIT 1
            ''', (l2_asn,))
            l3 = cursor.fetchone()
        
        # 尝试 L4 (仅对 /32 单IP)
        l4 = None
        if ip_start == ip_end:
            cursor.execute('''
                SELECT ptr_record, inferred_country, inferred_city, confidence
                FROM raw_l4_ptr
                WHERE ip = ?
                LIMIT 1
            ''', (ip_start,))
            l4 = cursor.fetchone()
        
        # 决定最终结果
        final_country, final_city, final_lat, final_lon = None, None, None, None
        final_source = 'unknown'
        confidence = 0
        
        if l1:
            # L1 优先
            final_country = l1['country']
            final_city = l1['city']
            final_lat = l1['latitude']
            final_lon = l1['longitude']
            final_source = 'L1'
            confidence = 5
        elif l3:
            # L3 次之
            final_country = l3['country']
            final_city = l3['city']
            final_lat = l3['latitude']
            final_lon = l3['longitude']
            final_source = 'L3'
            confidence = 3
        elif l4:
            # L4 兜底
            final_country = l4['inferred_country']
            final_city = l4['inferred_city']
            final_source = 'L4'
            confidence = l4['confidence'] or 2
        
        return (
            ip_start, ip_end,
            l1['source'] if l1 else None,
            l1['country'] if l1 else None,
            l1['city'] if l1 else None,
            l1['latitude'] if l1 else None,
            l1['longitude'] if l1 else None,
            l2_asn,
            l2['source'] if l2 else None,
            l3['country'] if l3 else None,
            l3['city'] if l3 else None,
            l3['latitude'] if l3 else None,
            l3['longitude'] if l3 else None,
            l4['ptr_record'] if l4 else None,
            l4['inferred_country'] if l4 else None,
            l4['inferred_city'] if l4 else None,
            final_country, final_city, final_lat, final_lon,
            final_source, confidence
        )
    
    def _insert_merged_batch(self, batch: List[Tuple]):
        """批量插入融合结果"""
        cursor = self.conn.cursor()
        cursor.executemany('''
            INSERT INTO merged_ip_locations 
            (ip_start, ip_end, l1_source, l1_country, l1_city, l1_lat, l1_lon,
             l2_asn, l2_source, l3_country, l3_city, l3_lat, l3_lon,
             l4_ptr, l4_country, l4_city,
             final_country, final_city, final_lat, final_lon, final_source, confidence)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ''', batch)
    
    # ==================== 查询接口 ====================
    
    def load_to_memory(self):
        """加载到内存区间树（加速查询）"""
        cursor = self.conn.cursor()
        cursor.execute('''
            SELECT ip_start, ip_end, final_country, final_city, 
                   final_lat, final_lon, final_source, confidence
            FROM merged_ip_locations
        ''')
        
        self.interval_tree = IntervalTree()
        count = 0
        
        for row in cursor.fetchall():
            loc = IPLocation(
                ip_start=row['ip_start'],
                ip_end=row['ip_end'],
                country=row['final_country'] or '',
                city=row['final_city'] or '',
                latitude=row['final_lat'],
                longitude=row['final_lon'],
                source=DataSource.L1_AUTHORITATIVE if row['final_source'] == 'L1' else
                       DataSource.L3_ASN_INFO if row['final_source'] == 'L3' else
                       DataSource.L4_PTR if row['final_source'] == 'L4' else
                       DataSource.UNKNOWN,
                source_detail=row['final_source'],
                confidence=row['confidence'] or 0
            )
            self.interval_tree.add(loc)
            count += 1
        
        self.interval_tree.build()
        self._loaded = True
        print(f"内存加载完成: {count} 条区间")
    
    def query(self, ip: str) -> Optional[IPLocation]:
        """查询IP位置"""
        if not self._loaded:
            self.load_to_memory()
        
        ip_int = IPConverter.ip_to_int(ip)
        return self.interval_tree.query(ip_int)
    
    def query_detail(self, ip: str) -> Dict:
        """详细查询（返回各层信息）"""
        cursor = self.conn.cursor()
        ip_int = IPConverter.ip_to_int(ip)
        
        result = {
            'ip': ip,
            'ip_int': ip_int,
            'layers': {}
        }
        
        # L1
        cursor.execute('''
            SELECT * FROM raw_l1_authoritative
            WHERE ip_start <= ? AND ip_end >= ?
        ''', (ip_int, ip_int))
        l1 = cursor.fetchall()
        if l1:
            result['layers']['L1'] = [dict(row) for row in l1]
        
        # L2
        cursor.execute('''
            SELECT * FROM raw_l2_asn_mapping
            WHERE ip_start <= ? AND ip_end >= ?
        ''', (ip_int, ip_int))
        l2 = cursor.fetchall()
        if l2:
            result['layers']['L2'] = [dict(row) for row in l2]
        
        # L3
        if l2:
            asn = l2[0]['asn']
            cursor.execute('SELECT * FROM raw_l3_asn_info WHERE asn = ?', (asn,))
            l3 = cursor.fetchone()
            if l3:
                result['layers']['L3'] = dict(l3)
        
        # L4
        cursor.execute('SELECT * FROM raw_l4_ptr WHERE ip = ?', (ip_int,))
        l4 = cursor.fetchone()
        if l4:
            result['layers']['L4'] = dict(l4)
        
        # 最终结果
        cursor.execute('''
            SELECT * FROM merged_ip_locations
            WHERE ip_start <= ? AND ip_end >= ?
        ''', (ip_int, ip_int))
        merged = cursor.fetchone()
        if merged:
            result['final'] = dict(merged)
        
        return result
    
    def close(self):
        """关闭数据库"""
        self.conn.close()


# ==================== 便捷函数 ====================

def create_db(db_path: str = "ip_locations.db") -> IPLocationDatabase:
    """创建数据库实例"""
    return IPLocationDatabase(db_path)


def quick_query(ip: str, db_path: str = "ip_locations.db") -> Optional[Dict]:
    """快速查询（无需管理实例）"""
    db = IPLocationDatabase(db_path)
    try:
        result = db.query(ip)
        if result:
            return {
                'ip': ip,
                'ip_range': f"{IPConverter.int_to_ip(result.ip_start)} - {IPConverter.int_to_ip(result.ip_end)}",
                'country': result.country,
                'city': result.city,
                'latitude': result.latitude,
                'longitude': result.longitude,
                'source': result.source_detail,
                'confidence': result.confidence
            }
        return None
    finally:
        db.close()


if __name__ == '__main__':
    # 测试代码
    print("IP 定位系统核心模块")
    print("=" * 50)
    
    # 测试 IP 转换
    print("\n1. IP 转换测试:")
    ip = "1.2.3.4"
    ip_int = IPConverter.ip_to_int(ip)
    print(f"   {ip} -> {ip_int}")
    print(f"   {ip_int} -> {IPConverter.int_to_ip(ip_int)}")
    
    # 测试前缀转换
    print("\n2. 前缀转换测试:")
    prefix = "192.168.0.0/24"
    start, end = IPConverter.prefix_to_range(prefix)
    print(f"   {prefix} -> {start} - {end}")
    
    # 测试区间树
    print("\n3. 区间树测试:")
    tree = IntervalTree()
    tree.add(IPLocation(16777216, 16777471, "US", "", source=DataSource.L1_AUTHORITATIVE))
    tree.add(IPLocation(16777472, 16777727, "CN", "Beijing", source=DataSource.L1_AUTHORITATIVE))
    tree.build()
    
    test_ip = IPConverter.ip_to_int("1.0.0.100")
    result = tree.query(test_ip)
    print(f"   查询 1.0.0.100: {result.country if result else 'Not found'}")
    
    print("\n模块测试完成!")
