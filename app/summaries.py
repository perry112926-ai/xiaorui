"""Versioned internal summary names; old stored proposals remain readable."""
ALIASES = {'操作':'action','车型':'vehicle','预估费用':'estimated_fee','取消费用':'cancel_fee',
           '原因':'reason','实际上车点':'origin','实际下车点':'destination','支付提醒':'payment_note',
           '报价变化':'quote_change','商品':'product','数量':'quantity',
           'store_name':'store','store_address':'address','product_name':'product','take_way':'fulfillment'}
LABELS = {'action':'操作','vehicle':'车型','estimated_fee':'预估费用','cancel_fee':'取消费用','reason':'原因',
          'origin':'实际上车点','destination':'实际下车点','payment_note':'支付提醒','quote_change':'报价变化',
          'city':'城市','contact':'联系人','phone':'联系电话','privacy':'信息用途','store':'门店','product':'商品',
          'quantity':'数量','fulfillment':'取餐方式','phone_tail':'收餐电话尾号','address':'地址',
          'address_detail':'门牌','choices':'套餐内容','attributes':'规格','tableware':'餐具','remark':'给商家的备注',
          'fee_breakdown':'费用明细','payment':'支付说明','fee_note':'费用说明','defaults':'搭配说明',
          'cancel_fee_yuan':'取消费用','amount_yuan':'总价','amount_cents':'总额（分）','fees':'费用分项'}

def normalize_summary(summary):
    # Explicit canonical keys win over an older alias in mixed-version records.
    result = {k:v for k,v in summary.items() if k not in ALIASES}
    for key,value in summary.items():
        if key in ALIASES:
            result.setdefault(ALIASES[key],value)
    return result
