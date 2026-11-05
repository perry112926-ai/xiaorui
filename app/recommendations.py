"""Budget-filtered self-pickup recommendations from real, freshly quoted meals."""
from decimal import Decimal, InvalidOperation
from app.money import format_cents
import asyncio


def _hint_cents(product):
    try:
        value = Decimal(str(product.get('price_yuan', '')))
        if not value.is_finite() or value <= 0:
            return None
        return int(value * 100)
    except (InvalidOperation, ValueError, TypeError):
        return None


def default_rounds(detail):
    """Only use explicit server defaults; never invent required meal choices."""
    rounds = detail.get('rounds')
    if not isinstance(rounds, list) or not rounds:
        return None
    selections = []
    for row in rounds:
        if row.get('minQuantity') != 1 or row.get('maxQuantity') != 1:
            return None
        defaults = [c for c in row.get('choices', []) if c.get('isDefault') == 1]
        if len(defaults) != 1 or not defaults[0].get('code') or 'id' not in row:
            return None
        selections.append({'round_id': str(row['id']),
                           'code': str(defaults[0]['code']), 'quantity': 1})
    if len({r['round_id'] for r in selections}) != len(selections):
        return None
    return selections


async def recommend(service, store_code, budget_cents=3500, limit=3):
    store = service.stores.get(store_code)
    if not store:
        raise ValueError('请先搜索并选择门店。')
    if store.get('open') is False:
        raise ValueError('这家门店目前未营业，请换一家。')
    products = await service.menu(store_code)
    candidates = []
    seen = set()
    for product in products:
        name = product.get('name', '')
        hint = _hint_cents(product)
        code = product.get('code')
        if (not code or code in seen or hint is None or hint > budget_cents
                or not any(word in name for word in ('套餐', '三件套', '单人餐'))):
            continue
        seen.add(code)
        candidates.append((hint, product))
    candidates.sort(key=lambda item: item[0])
    recommendations = []
    failed_requests = 0

    async def quoted(product):
        try:
            detail = await service.detail(store_code, product['code'])
            selections = default_rounds(detail)
            if selections is None:
                return None, False
            request = {'store_code': store_code, 'product_code': product['code'],
                       'quantity': 1, 'rounds': selections}
            # This computes a quote only; it never persists a confirmation plan.
            prepared = await service.prepare_plan(request)
            amount = prepared['amount_cents']
            if type(amount) is not int or amount <= 0:
                raise RuntimeError('核价金额无效。')
            if amount > budget_cents:
                return None, False
            return ({
                'product_code': product['code'], 'name': prepared['summary']['product_name'],
                'image': product.get('image'), 'amount_cents': amount,
                'choices': prepared['summary']['choices'], 'request': request,
            }, False)
        except ValueError:
            return None, False
        except RuntimeError:
            return None, True

    # Three concurrent read-only candidates; mutations are never parallelized.
    bounded = candidates[:5]
    batch_size = min(3, limit)
    for offset in range(0, len(bounded), batch_size):
        batch = await asyncio.gather(*(quoted(p) for _, p in bounded[offset:offset+batch_size]))
        for recommendation, failed in batch:
            failed_requests += int(failed)
            if recommendation is not None:
                recommendations.append(recommendation)
        if len(recommendations) >= limit:
            break
    recommendations = recommendations[:limit]
    if not recommendations and failed_requests:
        raise RuntimeError('套餐查询或核价未完成，请稍后重试。')
    if recommendations:
        parts = [f'{chr(65+i)}，{r["name"]}，{format_cents(r['amount_cents'])}元'
                 for i, r in enumerate(recommendations)]
        cheapest = min(range(len(recommendations)), key=lambda i: recommendations[i]['amount_cents'])
        speech = ('这次找到' + str(len(recommendations)) + '份可到店自取的套餐。'
                  + '；'.join(parts) + '。这几份里，'
                  + chr(65 + cheapest) + '价格最低。您想选哪份？')
    else:
        speech = '这次没有找到预算内、可核实组合的到店自取套餐。可以提高预算或换一家门店。'
    return {'recommendations': recommendations, 'speech_text': speech,
            'store': {key: store.get(key, '') for key in ('code', 'name', 'address')},
            'mode': 'pickup'}
