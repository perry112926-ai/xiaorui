"""Public-place real Amap contract checks. Requires --live; never writes."""
import argparse
import asyncio
import json
import logging
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4
from app.amap import Amap


async def main():
    client=Amap();session=SimpleNamespace(services={});records=[]
    async def check(label,name,args,condition):
        result=await client.dispatch(session,name,args)
        passed=bool(condition(result))
        records.append({'id':label,'passed':passed,'tool':name,'args':args,'result':result})
        print(json.dumps({'id':label,'passed':passed,'error':result.get('error')},ensure_ascii=False),flush=True)
    await check('current_weather','amap_weather',{'city':'北京'},lambda r:bool(r.get('weather')) and bool(r['weather'][0].get('reporttime')))
    await check('dated_forecast','amap_weather',{'city':'广州','forecast':True},lambda r:bool(r.get('forecasts')) and len(r['forecasts'][0]['casts'])>=3)
    await check('real_origin','amap_search_places',{'keyword':'北京西站北广场','purpose':'origin'},lambda r:bool(r.get('places')))
    for keyword in ('药店','公共厕所','医院','公园'):
        await check('nearby_'+keyword,'amap_nearby',{'keyword':keyword,'center_index':1,'radius':1000},
                    lambda r:'error' not in r and all('distance_meters' in p for p in r.get('places',[])))
    await check('geocode_destination','amap_geocode',{'address':'北京市中国国家博物馆','purpose':'destination'},lambda r:bool(r.get('places')))
    for mode in ('walking','driving','transit'):
        await check(mode,'amap_route',{'origin_index':1,'destination_index':1,'mode':mode},
                    lambda r:bool(r.get('routes')) and bool(r['routes'][0].get('duration_seconds')))
    # Pure arbitrary text; Chinese words such as “测试公园” can legitimately
    # produce fuzzy POI matches and are not a valid zero-result assertion.
    await check('empty_search','amap_search_places',{'keyword':'QXZVTJPLMABCDEFGHJKL999789012345','purpose':'destination'},lambda r:r.get('places')==[])
    await check('empty_cannot_reuse_previous_destination','amap_route',{'origin_index':1,'destination_index':1},lambda r:'error' in r)
    directory=Path('.local-data/amap-contract')/uuid4().hex;directory.mkdir(parents=True);directory.chmod(0o700)
    path=directory/'report.json';path.write_text(json.dumps(records,ensure_ascii=False,indent=2));path.chmod(0o600)
    print('Report:',path,flush=True)
    return 0 if all(r['passed'] for r in records) else 1


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--live',action='store_true');args=parser.parse_args()
    if not args.live:parser.error('Use --live for public official API queries.')
    logging.disable(logging.CRITICAL)
    raise SystemExit(asyncio.run(main()))
