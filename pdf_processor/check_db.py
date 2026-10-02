from database import Database
db = Database('research.db')
res = db.query_library(page=1, limit=3, has_strategy='true')
print('Total matching:', res['total'])
for it in res['items']:
    print(it['file_name'], '| has_strat:', it['has_strategy'], '| Family:', it['strategy_family'], '| Sharpe:', it['sharpe_ratio'])
filters = db.get_library_filters()
print('Filter total:', filters['total_count'])
print('Filter has_strategy:', filters['has_strategy_count'])
print('Filter families count:', len(filters['families']))
print('Filter assets count:', len(filters['asset_classes']))
