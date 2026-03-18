"""
IP 定位系统使用示例
"""

from ip_locator_core import (
    IPLocationDatabase, 
    IPConverter, 
    DataSource,
    quick_query
)


def demo_basic_usage():
    """基础使用演示"""
    print("=" * 60)
    print("IP 定位系统 - 使用示例")
    print("=" * 60)
    
    # 1. 创建/打开数据库
    print("\n1. 初始化数据库...")
    db = IPLocationDatabase("demo.db")
    
    # 2. 导入 Geofeed 数据
    print("\n2. 导入 Geofeed 数据...")
    # db.import_geofeed("path/to/geofeed.csv")
    print("   (请替换为实际的 Geofeed 文件路径)")
    
    # 3. 导入 AWS IP 段
    print("\n3. 导入 AWS IP 段...")
    # db.import_aws_ip_ranges("path/to/aws.json")
    print("   (请替换为实际的 AWS JSON 文件路径)")
    
    # 4. 导入 CAIDA pfx2as
    print("\n4. 导入 CAIDA pfx2as...")
    # db.import_caida_pfx2as("path/to/pfx2as.gz")
    print("   (请替换为实际的 pfx2as 文件路径)")
    
    # 5. 执行融合
    print("\n5. 执行数据融合...")
    # db.merge_all()
    print("   (融合各层数据，生成最终结果)")
    
    # 6. 加载到内存
    print("\n6. 加载到内存索引...")
    # db.load_to_memory()
    print("   (构建区间树，加速查询)")
    
    # 7. 查询示例
    print("\n7. 查询示例...")
    # result = db.query("8.8.8.8")
    # print(f"   8.8.8.8 -> {result}")
    
    db.close()
    print("\n完成!")


def demo_ip_conversion():
    """IP 转换演示"""
    print("\n" + "=" * 60)
    print("IP 转换工具演示")
    print("=" * 60)
    
    test_cases = [
        "1.2.3.4",
        "8.8.8.8",
        "192.168.1.1",
        "255.255.255.255",
        "0.0.0.0"
    ]
    
    print("\nIP 转整数:")
    for ip in test_cases:
        ip_int = IPConverter.ip_to_int(ip)
        back = IPConverter.int_to_ip(ip_int)
        print(f"  {ip:>15} -> {ip_int:>10} -> {back}")
    
    print("\n前缀转范围:")
    prefixes = ["192.168.0.0/24", "10.0.0.0/8", "172.16.0.0/16"]
    for prefix in prefixes:
        start, end = IPConverter.prefix_to_range(prefix)
        print(f"  {prefix:>15} -> {start:>10} - {end:>10}")
        print(f"                   ({IPConverter.int_to_ip(start)} - {IPConverter.int_to_ip(end)})")


def demo_interval_tree():
    """区间树演示"""
    print("\n" + "=" * 60)
    print("区间树查询演示")
    print("=" * 60)
    
    from ip_locator_core import IntervalTree, IPLocation
    
    tree = IntervalTree()
    
    # 添加一些测试区间
    locations = [
        IPLocation(16777216, 16777471, "US", "California", source=DataSource.L1_AUTHORITATIVE, confidence=5),      # 1.0.0.0/24
        IPLocation(16777472, 16777727, "JP", "Tokyo", source=DataSource.L1_AUTHORITATIVE, confidence=5),          # 1.0.1.0/24
        IPLocation(16777728, 16778239, "CN", "Beijing", source=DataSource.L3_ASN_INFO, confidence=3),             # 1.0.2.0/23
    ]
    
    for loc in locations:
        tree.add(loc)
    
    tree.build()
    
    # 查询测试
    test_ips = ["1.0.0.100", "1.0.1.50", "1.0.2.10", "1.0.5.1"]
    
    print("\n查询结果:")
    for ip in test_ips:
        ip_int = IPConverter.ip_to_int(ip)
        result = tree.query(ip_int)
        if result:
            print(f"  {ip:>12} -> {result.country:>4}, {result.city:>12} (来源: {result.source.name}, 置信度: {result.confidence})")
        else:
            print(f"  {ip:>12} -> 未找到")


if __name__ == '__main__':
    # 运行演示
    demo_ip_conversion()
    demo_interval_tree()
    demo_basic_usage()
