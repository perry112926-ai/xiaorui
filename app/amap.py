"""Fixed official Amap REST endpoints; query-only, no mock fallback."""
import os
import re
import math
import time
from pathlib import Path
from urllib.parse import urlencode
import httpx
from dotenv import dotenv_values
from pydantic import BaseModel, ConfigDict, Field
from typing import Literal
from app.life_services import _credential_filter

ROOT=Path(__file__).resolve().parents[1]


def accessibility_boundary(text):
    if (re.search(r'轮椅|无障碍|无台阶|直梯|电梯',text)
            and re.search(r'导航|路线|怎么走|地铁|站口|出口|全程|保证',text)):
        return ('高德普通路线无法核实全程无台阶、轮椅通行或电梯是否开放，我不能保证，也不能推荐未经核实的具体出口。'
                '请先向目的地或车站工作人员确认无障碍通道；您需要我再查一条普通路线作参考吗？')
    return None


def weather_precision_boundary(text):
    if (re.search(r'天气|下雨|降雨|气温|风力',text)
            and re.search(r'(精确|精准|准确).{0,12}(小时|分钟|几点|整点)|逐小时|每小时',text)):
        return ('目前高德接入的是每日白天／夜间预报，无法精确判断某个整点是否下雨，'
                '也没有逐小时雨量、降雨雷达或概率数据。我可以查当天白天或夜间预报供您参考。')
    return None


class Args(BaseModel):
    model_config=ConfigDict(extra='forbid',str_strip_whitespace=True)


class Search(Args):
    keyword:str=Field(min_length=1,max_length=100)
    city:str=Field(default='北京',min_length=1,max_length=30)
    purpose:Literal['origin','destination']='destination'


class Geocode(Args):
    address:str=Field(min_length=1,max_length=200)
    city:str=Field(default='北京',min_length=1,max_length=30)
    purpose:Literal['origin','destination']='destination'


class Route(Args):
    origin_index:int=Field(ge=1,le=5,strict=True)
    destination_index:int=Field(ge=1,le=5,strict=True)
    mode:Literal['walking','driving','transit']='walking'
    transit_preference:Literal['fastest','least_walking','least_transfers']='least_walking'


class Weather(Args):
    city:str=Field(default='北京',min_length=1,max_length=30)
    forecast:bool=Field(default=False,strict=True)


class Nearby(Args):
    keyword:str=Field(min_length=1,max_length=100)
    center_index:int=Field(ge=1,le=5,strict=True)
    radius:int=Field(default=1000,ge=100,le=5000,strict=True)


SCHEMAS={
 'amap_current_location':(Args,'读取本轮有效的浏览器授权定位并用高德逆地理编码核对所在城市和地址，保存为本轮origin。没有授权或已过期时询问地标，不猜位置、不保存为家。'),
 'amap_search_places':(Search,'用高德官方API搜索真实地点，保存本轮起点或终点候选供用户选择。默认北京，不猜当前位置。'),
 'amap_geocode':(Geocode,'用高德官方地理编码将用户明确提供的地址解析为地点候选；家必须来自已确认资料，不能猜地址。'),
 'amap_route':(Route,'按用户确认的本轮起终点序号规划高德步行walking、驾车driving或公交地铁transit路线。公交默认少步行，可选少换乘。具体线路、站点、耗时只据返回内容，不能从记忆补齐；不保证电梯/无障碍，不是持续导航，不叫车。'),
 'amap_weather':(Weather,'查询指定城市高德天气，含官方报告时间。现在用forecast=false；明天/后天等必须forecast=true，按返回日期回答，不能拿实时天气当预报；无逐小时降雨或空气质量。'),
 'amap_nearby':(Nearby,'按用户确认的本轮起点序号，在真实坐标周边按距离搜索医院、药店、公厕、公园等。必须先查origin候选，不能把普通文字搜索当最近。distance_meters为直线距离，不是步行距离；不保证营业、库存、挂号或无障碍。'),
}


def configured():
    return bool(os.environ.get('AMAP_KEY') or dotenv_values(ROOT/'.env').get('AMAP_KEY'))


class Amap:
    def __init__(self,client_factory=None,location_provider=None):
        self.client_factory=client_factory or httpx.AsyncClient
        self.location_provider=location_provider

    async def get(self,path,params):
        if path not in {'/v3/place/text','/v3/place/around','/v3/geocode/geo','/v3/geocode/regeo','/v3/weather/weatherInfo','/v3/direction/transit/integrated','/v5/direction/walking','/v5/direction/driving'}:
            raise ValueError('未开放的高德接口。')
        key=os.environ.get('AMAP_KEY') or dotenv_values(ROOT/'.env').get('AMAP_KEY')
        if not key:raise ValueError('高德尚未配置，请家人在本地 .env 填写 Web服务类型 AMAP_KEY。')
        _credential_filter.secrets.add(key)
        try:
            async with self.client_factory(timeout=15,follow_redirects=False) as client:
                response=await client.get('https://restapi.amap.com'+path,params={**params,'key':key,'output':'JSON'})
                response.raise_for_status()
                data=response.json()
        except Exception:
            raise ValueError('高德连接或响应异常，请稍后再查，没有使用假路线。') from None
        if not isinstance(data,dict) or str(data.get('status'))!='1':
            raise ValueError('高德未接受查询，请核对 Key 类型、服务权限和额度。')
        return data

    async def dispatch(self,session,name,arguments,owner=None):
        try:
            args=SCHEMAS[name][0].model_validate(arguments)
            state=session.services.setdefault('amap',{})
            if name=='amap_current_location':
                state.pop('origin',None)
                point=self.location_provider(owner) if self.location_provider else None
                if not point:return {'error':'没有当前有效定位，请点击定位授权或告诉我附近地标。','needs_location':True}
                location=f'{point["longitude"]:.6f},{point["latitude"]:.6f}'
                data=await self.get('/v3/geocode/regeo',{'location':location,'extensions':'base'})
                address=data.get('regeocode',{});components=address.get('addressComponent',{})
                city=components.get('city')
                if not isinstance(city,str) or not city:
                    province=components.get('province')
                    city=province if isinstance(province,str) and province.endswith('市') else None
                label=address.get('formatted_address')
                if not label or not city:raise ValueError('高德未能核对定位所在城市，请提供地标。')
                origin={'name':label,'address':label,'city':city,'location':location,
                        'expires_at':point['received_at']+120}
                if origin['expires_at']<time.time():raise ValueError('本轮定位已过期，请重新定位。')
                state['origin']=[origin]
                return {'places':[dict(origin,index=1)],'purpose':'origin','accuracy_meters':point['accuracy'],
                    'note':'本轮授权定位附近，须核对实际起点，不能当作家；精度可能不足以辨别门口或道路两侧。'}
            if name=='amap_nearby':
                state.pop('destination',None)
                origins=state.get('origin',[])
                if args.center_index>len(origins):raise ValueError('请先查询并确认本轮所在地点，不能猜测附近或最近。')
                origin=origins[args.center_index-1]
                if origin.get('expires_at',float('inf'))<time.time():raise ValueError('中心点定位已过期，请重新定位或查询地标。')
                data=await self.get('/v3/place/around',{'location':origin['location'],'keywords':args.keyword,
                    'radius':args.radius,'sortrule':'distance','offset':5})
                candidates=[]
                for item in data.get('pois',[])[:5]:
                    if not item.get('location') or not item.get('name'):continue
                    candidates.append({'name':item['name'],'address':item.get('address'),
                        'location':item['location'],'distance_meters':item.get('distance'),
                        'city':item.get('cityname') or origin.get('city')})
                state['destination']=candidates
                return {'center':origin['name'],'radius_meters':args.radius,
                    'places':[dict(p,index=i+1) for i,p in enumerate(candidates)],
                    'note':'按中心点直线距离排序，不是步行距离；不能据此保证营业、药品库存、急诊能力、无障碍或适合健康状况。请用户选择后再查实际步行路线。'}
            if name in {'amap_search_places','amap_geocode'}:
                state.pop(args.purpose,None)
                if name=='amap_search_places':
                    data=await self.get('/v3/place/text',{'keywords':args.keyword,'city':args.city,'citylimit':'true','offset':5})
                    rows=data.get('pois',[])
                else:
                    data=await self.get('/v3/geocode/geo',{'address':args.address,'city':args.city})
                    rows=data.get('geocodes',[])
                candidates=[]
                for item in rows[:5]:
                    location=item.get('location','')
                    if not isinstance(location,str) or len(location.split(','))!=2:continue
                    lng,lat=map(float,location.split(','))
                    if not (-180<=lng<=180 and -90<=lat<=90):continue
                    candidates.append({'name':item.get('name') or item.get('formatted_address'),
                        'address':item.get('address') or item.get('formatted_address'),
                        'location':location,'adcode':item.get('adcode'),'city':args.city})
                state[args.purpose]=candidates
                return {'places':[dict(p,index=i+1) for i,p in enumerate(candidates)],'purpose':args.purpose,
                    'next':'文字检索可能返回模糊匹配，不能把不相符的名称当作命中。请用户核对名称和地址，不自动把同名地点当作目的地；没有符合需求的结果就说明未找到。'}
            if name=='amap_weather':
                geo=await self.get('/v3/geocode/geo',{'address':args.city,'city':args.city})
                cities=geo.get('geocodes',[])
                if len(cities)!=1 or not cities[0].get('adcode'):raise ValueError('城市不明确，请提供省市或区县。')
                data=await self.get('/v3/weather/weatherInfo',{'city':cities[0]['adcode'],'extensions':'all' if args.forecast else 'base'})
                if args.forecast:
                    forecasts=data.get('forecasts',[])
                    if not forecasts:raise ValueError('高德未返回天气预报，不能用实时天气代替。')
                    return {'forecasts':[{'city':p.get('city'),'reporttime':p.get('reporttime'),
                        'casts':[{k:c.get(k) for k in ('date','week','dayweather','nightweather','daytemp','nighttemp','daywind','nightwind','daypower','nightpower')} for c in p.get('casts',[])[:4]]} for p in forecasts[:3]],
                        'note':'按实际预报日期回答，预报可能变化，不能保证一定不下雨。不代表逐小时天气、实时降雨雷达或空气质量。'}
                if not data.get('lives'):raise ValueError('高德未返回实时天气，不能推测天气。')
                return {'weather':[{k:p.get(k) for k in ('city','weather','temperature','winddirection','windpower','humidity','reporttime')} for p in data.get('lives',[])[:3]]}
            origins=state.get('origin',[]);destinations=state.get('destination',[])
            if args.origin_index>len(origins) or args.destination_index>len(destinations):raise ValueError('请先查询并确认本轮起点和目的地。')
            origin=origins[args.origin_index-1];destination=destinations[args.destination_index-1]
            if origin.get('expires_at',float('inf'))<time.time():raise ValueError('起点定位已过期，请重新定位或查询地标。')
            if args.mode=='transit':
                if not origin.get('city') or not destination.get('city'):raise ValueError('公交起终点城市缺失，请重新查询地点。')
                data=await self.get('/v3/direction/transit/integrated',{'origin':origin['location'],'destination':destination['location'],
                    'city':origin['city'],'cityd':destination['city'],'strategy':{'fastest':0,'least_walking':3,'least_transfers':2}[args.transit_preference],'extensions':'all'})
                transits=data.get('route',{}).get('transits',[])
                if not transits:raise ValueError('当前高德没有返回可用公交方案，不能推测线路或改成驾车。')
                routes=[]
                for transit in transits[:3]:
                    legs=[]
                    for segment in transit.get('segments',[]):
                        walk=segment.get('walking')
                        if isinstance(walk,dict) and walk.get('distance'):
                            legs.append({'type':'walking','distance_meters':walk['distance']})
                        bus=segment.get('bus')
                        # Multiple buslines within one segment are alternatives,
                        # not consecutive transfers. Present the first option.
                        for line in (bus.get('buslines',[]) if isinstance(bus,dict) else [])[:1]:
                            via=str(line.get('via_num',''))
                            legs.append({'type':'transit','line':line.get('name'),
                                'departure_stop':line.get('departure_stop',{}).get('name'),
                                'arrival_stop':line.get('arrival_stop',{}).get('name'),
                                'intermediate_stops':line.get('via_num'),
                                'ride_stops':int(via)+1 if via.isdecimal() else None})
                    routes.append({'distance_meters':transit.get('distance'),'duration_seconds':transit.get('duration'),
                        'walking_distance_meters':transit.get('walking_distance'),'cost_yuan':transit.get('cost'),'legs':legs[:20]})
                def walking(route):
                    try:
                        n=float(route.get('walking_distance_meters'))
                        return n if math.isfinite(n) and n>=0 else float('inf')
                    except (ValueError,TypeError):return float('inf')
                if args.transit_preference=='least_walking':routes.sort(key=walking)
                if args.transit_preference=='least_transfers':routes.sort(key=lambda r:sum(leg['type']=='transit' for leg in r['legs']))
                return {'origin':origin['name'],'destination':destination['name'],'mode':'transit','routes':routes,
                    'preference':args.transit_preference,
                    'map_url':'https://uri.amap.com/navigation?'+urlencode({'from':origin['location']+','+origin['name'],
                        'to':destination['location']+','+destination['name'],'mode':'bus','src':'xiaorui','coordinate':'gaode',
                        'policy':{'fastest':0,'least_walking':2,'least_transfers':1}[args.transit_preference]}),
                    'note':'高德当前公交方案，默认少步行；线路、步行量与耗时以本次结果为准，不保证班次实时、电梯开放、无台阶或轮椅通行。没有返回的地铁出口不能推测。'}
            data=await self.get('/v5/direction/'+args.mode,{'origin':origin['location'],'destination':destination['location'],'show_fields':'cost'})
            paths=data.get('route',{}).get('paths',[])
            if not paths:raise ValueError('当前没有可用路线，请换地点或出行方式。')
            return {'origin':origin['name'],'destination':destination['name'],'mode':args.mode,
                'routes':[{'distance_meters':p.get('distance'),'duration_seconds':p.get('cost',{}).get('duration'),
                    'instructions':[s['instruction'] for s in p.get('steps',[])[:12] if s.get('instruction')]} for p in paths[:3]],
                'map_url':'https://uri.amap.com/navigation?'+urlencode({'from':origin['location']+','+origin['name'],'to':destination['location']+','+destination['name'],'mode':'walk' if args.mode=='walking' else 'car','src':'xiaorui','coordinate':'gaode'}),
                'note':'高德路线规划快照，不是实时逐步导航，不会叫车。'}
        except ValueError as exc:
            from pydantic import ValidationError
            return {'error':'请补充正确的地点、城市或候选序号。' if isinstance(exc,ValidationError) else str(exc)}
        except Exception:
            return {'error':'高德返回的数据暂不支持，没有生成假路线或天气。'}
