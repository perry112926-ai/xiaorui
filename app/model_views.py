"""Positive output contracts for model-visible data, separate from host/UI state.

Unknown fields disappear at every depth. Scalars cannot smuggle an object through
an allowed leaf, and internal payloads/quotes are never model-visible containers.
"""
from app.summaries import normalize_summary, LABELS
from app.profile_card import BY_KEY
import math

SCALAR = object()
SCALAR_MAP = object()


def project(value, schema):
    if schema is SCALAR:
        if type(value) is float and not math.isfinite(value):return None
        return value if value is None or type(value) in (str,int,float,bool) else None
    if schema is SCALAR_MAP:
        return {k:project(v,SCALAR) for k,v in value.items() if isinstance(k,str) and type(v) in (str,int,float,bool)} if isinstance(value,dict) else {}
    if isinstance(schema,list):
        return [project(item,schema[0]) for item in value[:100]] if isinstance(value,list) else []
    if not isinstance(value,dict):
        return {}
    return {key:project(value[key],child) for key,child in schema.items() if key in value}


def fields(names):
    return {key:SCALAR for key in names.split()}

LOCATION = fields('lng lat longitude latitude')
PLACE = {**fields('index name display_name address city location distance distance_meters open hours accuracy_meters'), 'location':LOCATION}
CHOICE = fields('code name label title subtitle quantity index round_id round')
ROUND = {**fields('id name minQuantity maxQuantity'), 'choices':[CHOICE]}
ATTRIBUTE = {**fields('attribute name'), 'selected':[SCALAR], 'options':[SCALAR]}
PRODUCT = {**fields('index product_index name productName image pictureUrl menu_price_yuan quoted_price_yuan amount_cents recommendation_id meal_type fee_breakdown fulfillment'),
           'choices':[SCALAR], 'rounds':[ROUND], 'attributes':[ATTRIBUTE]}
SUMMARY = {**{key:SCALAR for key in LABELS}, 'choices':[SCALAR], 'attributes':[ATTRIBUTE], 'fees':fields('deliveryPrice packingPrice tablewarePrice realDeliveryPrice deliveryFee packingFee tablewareFee')}
DRIVER = fields('name carPlate driverName phone carColor carBrand carModel')
ORDER = {**fields('address_id success order_id orderId orderStatus orderStatusName status statusCode statusText statusName paid checked_at cancelled takeMealCodeInfo takeMealTime aboutTime orderPayAmount totalAmount realTotalAmount pickupCode expectDeliveryTime riderNickName takeWay cancelFee cancelFeeCents canCancel'), 'driver':DRIVER}
ORDER['from']=PLACE
ORDER['to']=PLACE
ORDER['map']=fields('distanceKm eta')
ORDER['last_status']={**ORDER}
UI_ORDER={**ORDER,'payment_url':SCALAR}

PLAN = {**fields('id provider action status version amount_cents expires_at created_at error execution_enabled confirmation_text summary_version'),
        'summary':SUMMARY, 'order':ORDER}
WEATHER = fields('city weather temperature winddirection windpower humidity reporttime')
CAST = fields('date week dayweather nightweather daytemp nighttemp daywind nightwind daypower nightpower')
FORECAST = {**fields('city reporttime'), 'casts':[CAST]}
ADDRESS = fields('index address addressDetail detail city contactName phone gender phone_tail addressId')
VEHICLE = fields('index productName productCategory priceText priceDiscounted')
LEG = fields('type name line departure arrival departure_stop arrival_stop intermediate_stops ride_stops walking_distance distance distance_meters duration instruction')
ROUTE = {**fields('distance_meters duration_seconds walking_meters walking_distance_meters cost cost_yuan'), 'legs':[LEG], 'steps':[LEG], 'instructions':[SCALAR]}
PROFILE = {**fields('version forget_epoch'), 'facts':SCALAR_MAP, 'confirmed_fields':{key:SCALAR for key in BY_KEY}}
TASK = {**fields('id status input error created_at updated_at conversation_id'), 'result':{'text':SCALAR}}
COMMON = {**fields('error next note history_policy mode purpose ready saved forgotten key order_created paid cancelled needs_setup needs_choices needs_tableware needs_location over_budget cart_changes_applied preflighted within_budget_count amount_cents status summary speech_text product name accuracy_meters center radius_meters origin destination map_url preference source'),
          'stores':[PLACE], 'places':[PLACE], 'products':[PRODUCT], 'meals':[PRODUCT], 'vehicles':[VEHICLE],
          'addresses':[ADDRESS], 'draft':ADDRESS, 'missing_fields':[SCALAR], 'take_ways':[CHOICE],
          'cart':[{**fields('index name quantity'), 'choices':[CHOICE]}], 'rounds':[ROUND],
          'attributes':[ATTRIBUTE], 'plan':PLAN, 'order':ORDER, 'orders':[PLAN], 'records':[PLAN],
          'actual_places':{'from':PLACE,'to':PLACE}, 'weather':[WEATHER], 'forecasts':[FORECAST],
          'routes':[ROUTE], 'preview':{**fields('payMoney totalMoney totalAmount amount orderPayAmount'), 'productList':[PRODUCT]},
          'estimate':{**fields('distanceKm eta'),'from':PLACE,'to':PLACE,'items':[VEHICLE]},
          'profile':PROFILE, 'tasks':[TASK], 'task':TASK}
COMMON['summary'] = SUMMARY
# Each provider has an explicit surface. An arbitrary provider object is never
# traversed merely because one of its children has a familiar name.
BASE_KEYS=set('error next note history_policy mode purpose ready saved forgotten key order_created paid cancelled needs_setup needs_choices needs_tableware needs_location over_budget cart_changes_applied preflighted within_budget_count amount_cents status speech_text product name accuracy_meters source'.split())
def surface(keys):
    return {key:COMMON[key] for key in BASE_KEYS|set(keys.split())}
TOOL_OUTPUTS = {
    'mcd':surface('stores products meals addresses draft missing_fields take_ways cart rounds attributes plan order orders records summary'),
    'didi':surface('places vehicles actual_places plan order records estimate summary'),
    'luckin':surface('stores products attributes plan order records preview summary'),
    'amap':surface('places weather forecasts routes center radius_meters origin destination map_url preference'),
    'personal_profile':{**PROFILE,'saved':SCALAR,'forgotten':SCALAR,'key':SCALAR,'profile':PROFILE,'error':SCALAR,'history_policy':SCALAR},
    'task_records':{'tasks':[TASK],'task':TASK,'error':SCALAR},
}
LEGACY_OUTPUTS={name:TOOL_OUTPUTS['mcd'] for name in ('search_stores','recommend_meals','choose_meal','cancel_plan')}
TOOL_OUTPUTS.update(LEGACY_OUTPUTS)
FLIGHT_SEGMENT=fields('depCityName arrCityName depStationName arrStationName depTerm arrTerm depDateTime arrDateTime marketingTransportName marketingTransportNo seatClassName duration')
TOOL_OUTPUTS['fliggy_search_flights']={**fields('error source checked_at order_created paid note next'),
    'flights':[{**fields('index ticket_price_yuan booking_url'),'journeys':[{**fields('type'),'segments':[FLIGHT_SEGMENT]}]}]}



def project_result(value, tool=None):
    if isinstance(value,list):
        return [project_result(item,tool) for item in value[:100]]
    if not isinstance(value,dict):
        return project(value,SCALAR)
    key = tool.split('_',1)[0] if tool else 'mcd'
    schema = TOOL_OUTPUTS.get(tool,TOOL_OUTPUTS.get(key,{'error':SCALAR}))
    result = project(value,schema)
    for plan_key in ('plan',):
        if isinstance(value.get(plan_key),dict) and 'summary' in value[plan_key]:
            result[plan_key]['summary']=project(normalize_summary(value[plan_key]['summary']),SUMMARY)
    return result


def project_plans(values):
    return [project({**p,'summary':normalize_summary(p.get('summary',{}))},PLAN) for p in values]


def project_services(services):
    schemas = {
        'mcd':{**COMMON, **fields('city mode budget_cents'), 'selected_store':PLACE,'selected_address':ADDRESS,
               'products':[PRODUCT], 'address_draft':ADDRESS,'checkout_preferences':fields('needTableware remark takeWayCode'),
               'recommended_meals':[PRODUCT]},
        'didi':{'origin':[PLACE],'destination':[PLACE],'estimate':{'items':[VEHICLE],'from':PLACE,'to':PLACE}},
        'luckin':{'stores':[PLACE],'products':[PRODUCT]},
        'amap':{'origin':[PLACE],'destination':[PLACE]},
    }
    normalized={**services}
    for domain in ('mcd','luckin','didi'):
        if not isinstance(services.get(domain),dict):continue
        state={**services[domain]}
        if isinstance(state.get('stores'),list):
            state['stores']=[{**row,'name':row.get('name') or row.get('storeName') or row.get('deptName'),
                              'open':row.get('open',row.get('businessStatus')),'index':i+1}
                             for i,row in enumerate(state['stores']) if isinstance(row,dict)]
        if isinstance(state.get('products'),list):
            state['products']=[{**row,'index':i+1} for i,row in enumerate(state['products']) if isinstance(row,dict)]
        normalized[domain]=state
    return project(normalized,schemas)
