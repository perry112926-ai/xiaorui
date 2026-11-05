"""Provider-backed food candidates keep price units and selection identity."""
import unittest
from app.agent import choice_cards


class ProductCardTests(unittest.TestCase):
    def test_official_photo_and_yuan_price_are_structured_without_submission(self):
        cards=choice_cards({'products':[{'index':7,'name':'麦香鱼套餐','image':'https://example.com/fish.png','menu_price_yuan':'28.5'}]})
        self.assertEqual(cards[0]['image'],'https://example.com/fish.png')
        self.assertEqual(cards[0]['price_yuan'],'28.50')
        self.assertEqual(cards[0]['kind'],'product')
        self.assertIn('第7个商品',cards[0]['prompt'])
        self.assertIn('先不要执行交易',cards[0]['prompt'])

    def test_missing_invalid_and_zero_prices_never_fabricate_a_quote(self):
        for price in (None,'','unknown','NaN','Infinity',-1,'22.123'):
            card=choice_cards({'products':[{'name':'测试餐品','menu_price_yuan':price}]})[0]
            self.assertEqual(card['kind'],'product')
            self.assertNotIn('price_yuan',card)
        self.assertEqual(choice_cards({'products':[{'name':'测试餐品','menu_price_yuan':0}]})[0]['price_yuan'],'0.00')

    def test_store_and_vehicle_cards_remain_generic(self):
        self.assertNotIn('kind',choice_cards({'stores':[{'name':'测试店','open':False}]})[0])
        self.assertNotIn('kind',choice_cards({'vehicles':[{'productName':'快车','priceText':'20'}]})[0])
