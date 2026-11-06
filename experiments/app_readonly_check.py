"""Live adapter integration check. Only discovery, menu, detail and price calls."""
import asyncio
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from app.mcd import McdService


async def main():
    service = McdService()
    stores = await service.search_stores('上海', '人民广场')
    store = next(s for s in stores if s['open'])
    products = await service.menu(store['code'])
    product = next(p for p in products if p['name'] == '板烧鸡腿堡三件套')
    detail = await service.detail(store['code'], product['code'])
    selected = []
    for row in detail.get('rounds', []):
        choice = next(c for c in row['choices'] if c.get('isDefault') == 1)
        selected.append({'round_id': str(row['id']), 'code': choice['code'], 'quantity': 1})
    prepared = await service.prepare_plan({
        'store_code': store['code'], 'product_code': product['code'],
        'quantity': 1, 'rounds': selected,
    })
    assert prepared['amount_cents'] > 0
    assert prepared['request']['storeCode'] == store['code']
    assert len(prepared['summary']['choices']) == len(selected)
    report = {'ok': True, 'live': True, 'orders_created': 0,
              'test_location': '上海人民广场（非用户位置）',
              'stores': len(stores), 'products': len(products),
              'amount_cents': prepared['amount_cents'], 'summary': prepared['summary']}
    path = ROOT / '.local-data/probes/mcd-probe/app-adapter-check.json'
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n')
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    asyncio.run(main())
