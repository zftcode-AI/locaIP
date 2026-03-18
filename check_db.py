import sqlite3
conn = sqlite3.connect('ip_locations.db')
cursor = conn.cursor()

cursor.execute('SELECT COUNT(*) FROM raw_l1_authoritative WHERE source = "geofeed"')
print('L1 Geofeed:', cursor.fetchone()[0])

cursor.execute('SELECT COUNT(*) FROM merged_ip_locations')
merged = cursor.fetchone()[0]
print('Merged:', merged)

if merged > 0:
    cursor.execute('SELECT ip_start, ip_end, final_country, final_city FROM merged_ip_locations LIMIT 3')
    print('\n样本:')
    for r in cursor.fetchall():
        print(f'  {r[0]}-{r[1]}: {r[2]}, {r[3]}')

conn.close()
